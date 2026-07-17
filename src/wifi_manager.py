# wifi_manager.py
import network
import socket
import time
import machine
import gc
import hashlib
import os
import ujson
import ubinascii
from config_manager import config_manager

API_VERSION = 1
_REBOOT_REQUESTED = False
# Pico W flash writes and Wi-Fi scheduling can make a normal 2-5 KiB upload
# span several seconds; keep a finite slow-client deadline without rejecting it.
REQUEST_READ_DEADLINE_MS = 8000
_REQUEST_DEADLINE = None

SESSION_COOKIE_NAME = "pico_clock_session_v1"
SESSION_IDLE_TIMEOUT_MS = 30 * 60 * 1000
SESSION_ABSOLUTE_TIMEOUT_MS = 24 * 60 * 60 * 1000
LOGIN_FAILURE_WINDOW_MS = 5 * 60 * 1000
LOGIN_FAILURE_LIMIT = 10
MAX_LOGIN_FAILURE_KEYS = 16
PASSWORD_MIN_LENGTH = 8
FIXED_ADMIN_USERNAME = "admin"
PBKDF2_TARGET_MS = 250
PBKDF2_PROBE_ITERATIONS = 64
PBKDF2_MIN_ITERATIONS = 64
PBKDF2_MAX_ITERATIONS = 65535

_CURRENT_SESSION_TOKEN = None
_SESSION_START_MS = None
_SESSION_LAST_ACTIVITY_MS = None
_SESSION_CSRF_TOKEN = None
_LOGIN_FAILURES = {}
_RESET_FAILURES = {}


def get_presence_manager():
    from presence_manager import get_presence_manager as _get_presence_manager
    return _get_presence_manager()


def iter_lines(path):
    from presence_manager import iter_lines as _iter_lines
    return _iter_lines(path)


def _ticks_add(value, delta):
    if hasattr(time, "ticks_add"):
        return time.ticks_add(value, delta)
    return value + delta


def _ticks_diff(new, old):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(new, old)
    return new - old


def _request_now_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _apply_request_deadline(cl):
    if _REQUEST_DEADLINE is None:
        raise OSError("Request deadline is not initialized.")
    remaining = _ticks_diff(_REQUEST_DEADLINE, _request_now_ms())
    if remaining <= 0:
        raise OSError("Request read deadline exceeded.")
    cl.settimeout(max(0.001, remaining / 1000.0))


class _DeadlineStream:
    def __init__(self, stream):
        self.stream = stream

    def readinto(self, buffer, length=None):
        _apply_request_deadline(self.stream)
        if length is None:
            return self.stream.readinto(buffer)
        try:
            return self.stream.readinto(buffer, length)
        except TypeError:
            return self.stream.readinto(memoryview(buffer)[:length])

def _random_token(byte_count=16):
    """Returns a CSPRNG-backed opaque token; never falls back to a clock."""
    return ubinascii.hexlify(os.urandom(byte_count)).decode()


def _constant_time_equal(left, right):
    """Compares text/bytes without a length-dependent early exit."""
    if isinstance(left, str):
        left = left.encode("utf-8")
    if isinstance(right, str):
        right = right.encode("utf-8")
    if left is None:
        left = b""
    if right is None:
        right = b""
    size = max(len(left), len(right))
    difference = len(left) ^ len(right)
    for index in range(size):
        left_byte = left[index] if index < len(left) else 0
        right_byte = right[index] if index < len(right) else 0
        difference |= left_byte ^ right_byte
    return difference == 0


def _hmac_sha256(key, value):
    if not isinstance(key, (bytes, bytearray)):
        key = key.encode("utf-8")
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    inner = bytearray(64)
    outer = bytearray(64)
    for index in range(64):
        byte = key[index] if index < len(key) else 0
        inner[index] = byte ^ 0x36
        outer[index] = byte ^ 0x5C
    digest = hashlib.sha256()
    digest.update(inner)
    digest.update(value)
    inner_digest = digest.digest()
    digest = hashlib.sha256()
    digest.update(outer)
    digest.update(inner_digest)
    return digest.digest()


def _pbkdf2_sha256(password, salt, iterations):
    if isinstance(password, str):
        password = password.encode("utf-8")
    block = salt + bytes((0, 0, 0, 1))
    current = _hmac_sha256(password, block)
    result = bytearray(current)
    for _ in range(1, iterations):
        current = _hmac_sha256(password, current)
        for index in range(len(result)):
            result[index] ^= current[index]
    return bytes(result)


def _calibrate_pbkdf2_iterations():
    """Selects a device-specific cost in the documented 100-500 ms range."""
    salt = os.urandom(16)
    started = _request_now_ms()
    _pbkdf2_sha256("calibration", salt, PBKDF2_PROBE_ITERATIONS)
    elapsed = max(1, _ticks_diff(_request_now_ms(), started))
    estimate = int(PBKDF2_PROBE_ITERATIONS * PBKDF2_TARGET_MS / elapsed)
    return min(PBKDF2_MAX_ITERATIONS, max(PBKDF2_MIN_ITERATIONS, estimate))


def _password_hash(password):
    salt = os.urandom(16)
    iterations = _calibrate_pbkdf2_iterations()
    derived = _pbkdf2_sha256(password, salt, iterations)
    return "pbkdf2-sha256${}${}${}".format(
        iterations,
        ubinascii.hexlify(salt).decode(),
        ubinascii.hexlify(derived).decode(),
    )


def _password_matches(password, record):
    if not isinstance(record, str) or not record:
        return False
    if not record.startswith("pbkdf2-sha256$"):
        return _constant_time_equal(password, record)
    parts = record.split("$")
    if len(parts) != 4:
        return False
    try:
        iterations = int(parts[1])
        if iterations < PBKDF2_MIN_ITERATIONS or iterations > PBKDF2_MAX_ITERATIONS:
            return False
        salt = ubinascii.unhexlify(parts[2].encode())
        expected = ubinascii.unhexlify(parts[3].encode())
    except (ValueError, TypeError):
        return False
    actual = _pbkdf2_sha256(password, salt, iterations)
    return _constant_time_equal(actual, expected)


def _admin_username():
    return FIXED_ADMIN_USERNAME


def _admin_password_record():
    return config_manager.get_global("lan_admin.password", "") or ""


def _admin_password_configured():
    return bool(_admin_password_record())


def _migrate_legacy_password():
    """Upgrade pre-session plaintext records when the config API supports writes."""
    record = _admin_password_record()
    if not record or record.startswith("pbkdf2-sha256$"):
        return
    if getattr(config_manager, "read_only", False) or not hasattr(config_manager, "set_global"):
        return
    try:
        config_manager.set_global("lan_admin.password", _password_hash(record))
        print("Info: Migrated LAN admin password to PBKDF2-HMAC-SHA256.")
    except Exception as exc:
        print("Warning: LAN admin password migration deferred: {}".format(exc))


def _clear_session():
    global _CURRENT_SESSION_TOKEN, _SESSION_START_MS
    global _SESSION_LAST_ACTIVITY_MS, _SESSION_CSRF_TOKEN
    _CURRENT_SESSION_TOKEN = None
    _SESSION_START_MS = None
    _SESSION_LAST_ACTIVITY_MS = None
    _SESSION_CSRF_TOKEN = None


def _start_session():
    global _CURRENT_SESSION_TOKEN, _SESSION_START_MS
    global _SESSION_LAST_ACTIVITY_MS, _SESSION_CSRF_TOKEN
    now = _request_now_ms()
    _CURRENT_SESSION_TOKEN = _random_token(16)
    _SESSION_CSRF_TOKEN = _random_token(16)
    _SESSION_START_MS = now
    _SESSION_LAST_ACTIVITY_MS = now
    return _CURRENT_SESSION_TOKEN, _SESSION_CSRF_TOKEN


def _cookie_value(request, name):
    cookie_header = _request_headers(request).get("cookie", "")
    for item in cookie_header.split(";"):
        if "=" not in item:
            continue
        key, value = item.strip().split("=", 1)
        if key == name:
            return value
    return ""


def _session_authorized(request, touch=True):
    global _SESSION_LAST_ACTIVITY_MS
    if _CURRENT_SESSION_TOKEN is None or _SESSION_CSRF_TOKEN is None:
        return False
    token = _cookie_value(request, SESSION_COOKIE_NAME)
    if not _constant_time_equal(token, _CURRENT_SESSION_TOKEN):
        return False
    now = _request_now_ms()
    if _ticks_diff(now, _SESSION_START_MS) > SESSION_ABSOLUTE_TIMEOUT_MS:
        _clear_session()
        return False
    if _ticks_diff(now, _SESSION_LAST_ACTIVITY_MS) > SESSION_IDLE_TIMEOUT_MS:
        _clear_session()
        return False
    if touch:
        _SESSION_LAST_ACTIVITY_MS = now
    return True


def _request_csrf_valid(request, params=None):
    if not _session_authorized(request):
        return False
    params = params or {}
    headers = _request_headers(request)
    token = headers.get("x-csrf-token") or params.get("csrf_token", "")
    return _constant_time_equal(token, _SESSION_CSRF_TOKEN)


def verify_csrf_token(params):
    """Verifies the per-process pre-auth CSRF token."""
    token = params.get("csrf_token", "")
    is_valid = _constant_time_equal(token, CSRF_TOKEN)
    if not is_valid:
        print("CSRF validation failed.")
    return is_valid


CSRF_TOKEN = _random_token(16)
_migrate_legacy_password()

def reset_wifi_and_reboot():
    """Sets force AP mode flag and reboots to enter configuration mode."""
    from display_manager import update_display_Restart

    print("Long press detected. Entering AP mode for configuration...")

    # Set force AP mode flag
    config_manager.set_global("force_ap_mode", True)

    # Display restart message
    update_display_Restart()
    print("Entering AP mode. System will restart...")
    time.sleep(2)
    machine.reset()

def factory_reset():
    """Performs a complete factory reset - deletes all profiles and restores defaults."""
    print("FACTORY RESET: Deleting all configurations and restoring defaults...")

    # Delete config file completely
    try:
        import os
        os.remove('config.json')
        print("Config file deleted.")
    except:
        pass

    # Reinitialize config manager with defaults
    config_manager.config = config_manager._get_default_config()
    config_manager._save_config()
    _clear_session()

    print("Factory reset complete. Default configuration restored.")
    return True


def unquote(string):
    """Decodes URL-encoded strings (MicroPython compatible) with UTF-8 support."""
    if not string:
        return ""

    res = bytearray()
    i = 0
    n = len(string)

    while i < n:
        char = string[i]
        if char == '%' and i + 2 < n:
            try:
                hex_value = int(string[i+1:i+3], 16)
                res.append(hex_value)
                i += 3
            except ValueError:
                res.append(ord('%'))
                i += 1
        elif char == '+':
            res.append(ord(' '))
            i += 1
        else:
            codepoint = ord(char)
            if codepoint < 256:
                res.append(codepoint)
            else:
                res.extend(char.encode('utf-8'))
            i += 1

    try:
        return res.decode('utf-8')
    except:
        return string

def parse_query_string(query_string):
    """Parses a URL query string into a dictionary."""
    params = {}

    if not query_string:
        return params

    # Split pairs by '&'
    pairs = query_string.split('&')

    for pair in pairs:
        if '=' in pair:
            key, value = pair.split('=', 1)
            params[key] = unquote(value)
        else:
            params[pair] = ''

    return params

def html_escape(text):
    """Escapes HTML special characters to prevent XSS attacks.

    Args:
        text: String to escape (will be converted to string if not)

    Returns:
        Escaped string safe for HTML insertion

    Example:
        >>> html_escape('<script>alert("XSS")</script>')
        '&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;'
    """
    if not isinstance(text, str):
        text = str(text)
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

def scan_networks():
    """Scans for available Wi-Fi networks and returns with signal strength."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    nets = sta.scan()
    unique_networks = {}
    for ssid_bytes, bssid, channel, rssi, authmode, hidden in nets:
        try:
            ssid = ssid_bytes.decode('utf-8')
            if ssid and (ssid not in unique_networks or rssi > unique_networks[ssid]):
                unique_networks[ssid] = rssi
        except UnicodeError:
            pass

    return [{"ssid": ssid, "rssi": rssi} for ssid, rssi in unique_networks.items()]


def _send_file_chunks(cl, path):
    try:
        with open(path, 'rb') as f:
            while True:
                buf = f.read(512)
                if not buf:
                    break
                send_chunk(cl, buf)
    except OSError as e:
        print("Error serving {}: {}".format(path, e))


def _send_html_file(cl, path):
    """Send a generated gzip HTML asset with its browser decoding header."""
    send_chunk(cl, b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                    b"Content-Encoding: gzip\r\nCache-Control: no-store\r\n\r\n")
    _send_file_chunks(cl, path)

def send_chunk(cl, data):
    """
    可靠地分段傳送資料，並加入微小延遲以防止緩衝區溢位。
    解決頁面載入不全或傳送失敗的問題。
    """
    if isinstance(data, str):
        data = data.encode('utf-8')

    mv = memoryview(data)
    total_sent = 0
    chunk_size = 512
    try:
        while total_sent < len(mv):
            try:
                chunk_end = min(total_sent + chunk_size, len(mv))
                sent = cl.send(mv[total_sent:chunk_end])
                if sent == 0:
                    raise OSError("Socket connection broken")
                total_sent += sent
                # 關鍵：每次傳送後暫停 10ms，讓 Pico W 的網路堆疊有時間清空緩衝區
                time.sleep(0.01)
            except OSError as e:
                print(f"Error sending chunk: {e}")
                break
    finally:
        del mv


def _read_http_request(cl, max_request_size=4096):
    global _REQUEST_DEADLINE
    _REQUEST_DEADLINE = _ticks_add(_request_now_ms(), REQUEST_READ_DEADLINE_MS)
    cl_file = cl.makefile("rwb", 0)
    request_data = bytearray()
    complete = False

    while True:
        try:
            _apply_request_deadline(cl)
            line = cl_file.readline()
            if line == b"\r\n":
                complete = True
                break
            if not line:
                break
            if len(request_data) + len(line) > max_request_size:
                print("Warning: Request too large, rejecting.")
                cl.send(b"HTTP/1.0 413 Request Entity Too Large\r\n\r\n")
                return None
            request_data.extend(line)
        except OSError:
            break

    if not complete:
        try:
            cl.send(b"HTTP/1.0 408 Request Timeout\r\nConnection: close\r\n\r\n")
        except OSError:
            pass
        return None

    try:
        return request_data.decode()
    except UnicodeError:
        cl.send(b"HTTP/1.0 400 Bad Request\r\n\r\n")
        return None

def _get_query_params(request):
    if "?" not in request:
        return {}
    query_start = request.find("?") + 1
    query_end = request.find(" ", query_start)
    if query_end < 0:
        query_end = len(request)
    query_string = request[query_start:query_end]
    return parse_query_string(query_string)


def _read_request_body(cl, request, maximum=4096):
    headers = _request_headers(request)
    if "transfer-encoding" in headers or "_duplicate_content-length" in headers:
        raise ValueError("Invalid HTTP body framing.")
    if "content-length" not in headers:
        raise ValueError("Content-Length is required.")
    length = int(headers["content-length"])
    if length < 0 or length > maximum:
        raise ValueError("Request body is too large.")
    body = bytearray(length)
    offset = 0
    while offset < length:
        _apply_request_deadline(cl)
        view = memoryview(body)[offset:]
        try:
            count = cl.readinto(view, len(view))
        except TypeError:
            count = cl.readinto(view)
        if not count:
            raise ValueError("Request body ended early.")
        offset += count
    return body.decode()


def _config_payload(profile_name=None):
    profile = config_manager.get_profile(profile_name) if profile_name else config_manager.get_active_profile()
    if not profile:
        profile = config_manager.get_active_profile()
    safe_profile = {
        "name": profile.get("name", "") if profile else "",
        "wifi": {"ssid": profile.get("wifi", {}).get("ssid", "") if profile else ""},
        "weather_location": profile.get("weather_location", "Taipei") if profile else "Taipei",
        "user": profile.get("user", {}) if profile else {},
        "chime": profile.get("chime", {}) if profile else {},
    }
    return {
        "csrf_token": _SESSION_CSRF_TOKEN or "",
        "profiles": config_manager.list_profiles(),
        "active_profile": config_manager.get_active_profile_name(),
        "profile": safe_profile,
        "global": {
            "ap_mode_ssid": config_manager.get_global("ap_mode.ssid", "Pi_Clock_AP"),
            "weather_api_key_configured": bool(config_manager.get_global("weather_api_key", "")),
            "discord_webhook_configured": bool(config_manager.get_global("discord_webhook_url", "")),
            "lan_admin_username": FIXED_ADMIN_USERNAME,
        },
    }


def _handle_config_api(cl, request, require_auth):
    from image_manager import ImageStoreError

    global _REBOOT_REQUESTED
    method, target = _request_line(request)
    path = target.split("?", 1)[0]
    if path == "/api/v1/config" and method == "GET":
        params = _get_query_params(target)
        _send_json_status(cl, 200, _config_payload(params.get("profile")))
        return True
    if path == "/api/v1/networks" and method == "GET":
        try:
            _send_json_status(cl, 200, {"networks": _get_page_networks(require_auth)})
        except Exception as exc:
            print("Wi-Fi scan error: {}".format(exc))
            _send_json_status(cl, 500, {"error": "scan_failed", "message": "Unable to scan Wi-Fi networks."})
        return True
    if path == "/api/v1/config" and method == "POST":
        try:
            body = _read_request_body(cl, request)
            params = parse_query_string(body)
            if not _request_csrf_valid(request, params):
                _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
                return True
            _save_settings_from_params(params)
            _REBOOT_REQUESTED = True
            _send_json_status(cl, 200, {"saved": True, "restart_scheduled": True})
        except (ValueError, ImageStoreError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_config", "message": str(exc)})
        except Exception as exc:
            print("Config API error: {}".format(exc))
            _send_json_status(cl, 500, {"error": "save_failed", "message": "Unable to save configuration."})
        return True
    return False


def _consume_reboot_request():
    global _REBOOT_REQUESTED
    requested = _REBOOT_REQUESTED
    _REBOOT_REQUESTED = False
    return requested

def _reset_failure_key(client_key):
    return "reset:" + (client_key or "unknown")


def _failure_is_limited(store, key, limit):
    now = _request_now_ms()
    values = store.get(key, [])
    values = [value for value in values if _ticks_diff(now, value) <= LOGIN_FAILURE_WINDOW_MS]
    store[key] = values
    return len(values) >= limit


def _record_failure(store, key, limit):
    now = _request_now_ms()
    if key not in store and len(store) >= MAX_LOGIN_FAILURE_KEYS:
        oldest = min(store, key=lambda item: store[item][-1] if store[item] else now)
        del store[oldest]
    values = store.get(key, [])
    values = [value for value in values if _ticks_diff(now, value) <= LOGIN_FAILURE_WINDOW_MS]
    values.append(now)
    store[key] = values[-limit:]


def _clear_failure(store, key):
    store.pop(key, None)


def _set_admin_password(password):
    if len(password) < PASSWORD_MIN_LENGTH or len(password) > 128:
        raise ValueError("管理密碼必須為 8-128 個字元。")
    if getattr(config_manager, "read_only", False):
        raise ValueError("目前設定檔為唯讀，無法設定管理密碼。")
    config_manager.set_global("lan_admin.password", _password_hash(password))
    _clear_session()


def _safe_redirect(value):
    if (
        not value or
        not value.startswith("/") or
        value.startswith("//") or
        "\\" in value or
        any(ord(char) < 32 for char in value)
    ):
        return "/"
    return value


def _session_cookie(token, clear=False):
    if clear:
        return "{}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0".format(SESSION_COOKIE_NAME)
    return "{}={}; Path=/; HttpOnly; SameSite=Strict".format(SESSION_COOKIE_NAME, token)


def _is_lan_authorized(request):
    return _session_authorized(request)


def _auth_required_for_request(require_auth):
    setup_complete = config_manager.get_global("setup_complete", False)
    return require_auth or setup_complete or _admin_password_configured()


def _request_is_api(target):
    path = target.split("?", 1)[0]
    return path.startswith("/api/") or path.startswith("/presence/") or path == "/adc"


def _send_auth_required(cl, api=False):
    if api:
        _send_json_status(cl, 401, {"error": "auth_required", "message": "請先登入管理介面。"})
    else:
        send_chunk(cl, b"HTTP/1.0 302 Found\r\nLocation: /login\r\nCache-Control: no-store\r\n\r\n")


def _handle_auth_api(cl, request, client_key):
    method, target = _request_line(request)
    path = target.split("?", 1)[0]
    if path == "/api/v1/auth/status" and method == "GET":
        _send_json_status(cl, 200, {
            "setup_required": not _admin_password_configured(),
            "authenticated": _session_authorized(request),
            "username": _admin_username(),
            "csrf_token": CSRF_TOKEN,
        })
        return True
    if path == "/api/v1/auth/session" and method == "GET":
        if not _is_lan_authorized(request):
            _send_auth_required(cl, api=True)
        else:
            _send_json_status(cl, 200, {
                "authenticated": True,
                "username": _admin_username(),
                "csrf_token": _SESSION_CSRF_TOKEN,
            })
        return True
    if path == "/api/v1/auth/login" and method == "POST":
        try:
            body = _read_request_body(cl, request)
            params = parse_query_string(body)
        except (ValueError, TypeError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_request", "message": str(exc)})
            return True
        if not verify_csrf_token(params):
            _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
            return True
        if _failure_is_limited(_LOGIN_FAILURES, client_key, LOGIN_FAILURE_LIMIT):
            _send_json_status(cl, 429, {"error": "rate_limited", "message": "登入嘗試過多，請 5 分鐘後再試。"})
            return True
        password = params.get("password", "")
        setup_required = not _admin_password_configured()
        valid = False
        try:
            if setup_required:
                password_confirm = params.get("password_confirm", "")
                valid = (
                    _constant_time_equal(password, password_confirm) and
                    len(password) >= PASSWORD_MIN_LENGTH
                )
                if valid:
                    _set_admin_password(password)
            else:
                valid = (
                    _password_matches(password, _admin_password_record())
                )
                if valid and not _admin_password_record().startswith("pbkdf2-sha256$"):
                    _set_admin_password(password)
        except (ValueError, OSError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_credentials", "message": str(exc)})
            return True
        if not valid:
            _record_failure(_LOGIN_FAILURES, client_key, LOGIN_FAILURE_LIMIT)
            _send_json_status(cl, 401, {"error": "invalid_credentials", "message": "帳號或密碼不正確。"})
            return True
        _clear_failure(_LOGIN_FAILURES, client_key)
        session_token, csrf_token = _start_session()
        _send_json_status(
            cl,
            200,
            {"authenticated": True, "csrf_token": csrf_token, "redirect": _safe_redirect(params.get("next"))},
            {"Set-Cookie": _session_cookie(session_token)},
        )
        return True
    if path == "/api/v1/auth/logout" and method == "POST":
        if not _is_lan_authorized(request):
            _send_auth_required(cl, api=True)
            return True
        if not _request_csrf_valid(request):
            _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
            return True
        _clear_session()
        _send_json_status(cl, 200, {"authenticated": False}, {"Set-Cookie": _session_cookie("", clear=True)})
        return True
    return False

def _get_page_networks(require_auth=False):
    return scan_networks()


def _send_json(cl, value):
    cl.send(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n")
    cl.send(ujson.dumps(value).encode())


def _send_json_status(cl, status, value, extra_headers=None):
    reason = {
        200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized",
        403: "Forbidden", 404: "Not Found", 409: "Conflict", 411: "Length Required",
        413: "Payload Too Large", 429: "Too Many Requests", 500: "Internal Server Error",
        507: "Insufficient Storage",
    }.get(status, "Error")
    header = "HTTP/1.0 {} {}\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n".format(status, reason)
    for name, header_value in (extra_headers or {}).items():
        header += "{}: {}\r\n".format(name, header_value)
    header += "\r\n"
    send_chunk(cl, header)
    send_chunk(cl, ujson.dumps(value))


def _request_line(request):
    try:
        method, target, _ = request.split("\r\n", 1)[0].split(" ", 2)
        return method, target
    except (ValueError, AttributeError):
        return "", ""


def _request_headers(request):
    headers = {}
    try:
        for line in request.split("\r\n")[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            name = name.strip().lower()
            value = value.strip()
            if name in headers:
                headers["_duplicate_" + name] = "1"
            headers[name] = value
    except Exception:
        pass
    return headers


def _api_error_status(code):
    return {
        "invalid_name": 400,
        "invalid_event": 400,
        "invalid_collection": 400,
        "invalid_size": 413,
        "incomplete_upload": 400,
        "exists": 409,
        "not_found": 404,
        "insufficient_storage": 507,
    }.get(code, 500)


def _parse_image_resource(path):
    from image_manager import ImageStoreError

    parts = [part for part in path.split("/") if part]
    if len(parts) < 5 or parts[:3] != ["api", "v1", "images"]:
        raise ImageStoreError("not_found", "Image resource was not found.")
    collection = parts[3]
    preview = parts[-1] == "preview"
    if preview:
        parts = parts[:-1]
    if collection in ("custom", "login") and len(parts) == 5:
        return collection, None, parts[4], preview
    if collection == "events" and len(parts) == 6:
        return collection, parts[4], parts[5], preview
    raise ImageStoreError("not_found", "Image resource was not found.")


def _send_image_list(cl, collection, event):
    from image_manager import filesystem_free, image_store

    send_chunk(cl, b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{"items":[')
    first = True
    for filename, size in image_store.iter_images(collection, event):
        if not first:
            send_chunk(cl, b",")
        item = {"name": filename, "bytes": size, "collection": collection}
        if event:
            item["event"] = event
        send_chunk(cl, ujson.dumps(item))
        first = False
    send_chunk(cl, '],"fs_free":' + str(filesystem_free()) + ",\"catalog_generation\":" + str(image_store.catalog_generation) + "}")


def _handle_image_api(cl, request, require_auth=False):
    from image_manager import IMAGE_SPECS, ImageStoreError, filesystem_free, image_store

    method, target = _request_line(request)
    path = target.split("?", 1)[0]
    if path == "/api/v1/device" and method == "GET":
        specs = {}
        for name, spec in IMAGE_SPECS.items():
            specs[name] = {"width": spec[0], "height": spec[1], "bytes": spec[2]}
        _send_json_status(cl, 200, {
            "device": "pi-paper-clock",
            "api_version": API_VERSION,
            "heap_free": gc.mem_free(),
            "fs_free": filesystem_free(),
            "image_types": specs,
        })
        return True

    if not path.startswith("/api/v1/images"):
        return False

    image_mutation = method in ("PUT", "POST", "DELETE")
    if (image_mutation or _auth_required_for_request(require_auth)) and not _is_lan_authorized(request):
        _send_auth_required(cl, api=True)
        return True

    headers = _request_headers(request)
    if "transfer-encoding" in headers or "_duplicate_content-length" in headers:
        _send_json_status(cl, 400, {"error": "invalid_framing", "message": "Only one identity Content-Length is supported."})
        return True
    if method in ("PUT", "POST", "DELETE") and headers.get("x-pico-clock-api") != "1":
        _send_json_status(cl, 400, {"error": "client_header_required", "message": "X-Pico-Clock-API: 1 is required."})
        return True
    if image_mutation and not _request_csrf_valid(request):
        _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
        return True

    try:
        if path == "/api/v1/images" and method == "GET":
            params = _get_query_params(target)
            collection = params.get("collection", "custom")
            event = params.get("event") if collection == "events" else None
            # Validate before writing response headers.
            from image_manager import image_directory
            image_directory(collection, event)
            _send_image_list(cl, collection, event)
            return True

        collection, event, filename, preview_action = _parse_image_resource(path)
        if method == "PUT" and not preview_action:
            if "content-length" not in headers:
                _send_json_status(cl, 411, {"error": "length_required", "message": "Content-Length is required."})
                return True
            try:
                content_length = int(headers["content-length"])
            except ValueError:
                raise ImageStoreError("invalid_size", "Content-Length is invalid.")
            params = _get_query_params(target)
            result = image_store.upload(
                _DeadlineStream(cl),
                collection,
                filename,
                content_length,
                event=event,
                overwrite=params.get("overwrite", "0") == "1",
                preview=params.get("preview", "0") == "1",
            )
            _send_json_status(cl, 200 if result["replaced"] else 201, result)
            return True

        if method == "DELETE" and not preview_action:
            deleted = image_store.delete(collection, filename, event)
            _send_json_status(cl, 200, {"deleted": deleted, "catalog_generation": image_store.catalog_generation})
            return True

        if method == "POST" and preview_action:
            queued = image_store.queue_preview(collection, filename, event)
            _send_json_status(cl, 200, {"preview_queued": True, "path": queued})
            return True
        raise ImageStoreError("not_found", "Image API route was not found.")
    except ImageStoreError as exc:
        _send_json_status(cl, _api_error_status(exc.code), {"error": exc.code, "message": exc.message})
        return True
    except Exception as exc:
        print("Image API error: {}".format(exc))
        _send_json_status(cl, 500, {"error": "internal_error", "message": "Image operation failed."})
        return True


def _presence_epoch(date_value, time_value):
    try:
        return int(time.mktime((
            int(date_value[0:4]),
            int(date_value[4:6]),
            int(date_value[6:8]),
            int(time_value[0:2]),
            int(time_value[2:4]),
            int(time_value[4:6]),
            0, 0
        )))
    except Exception:
        return 0


def _send_presence_lines(cl, kind):
    manager = get_presence_manager()
    response_buffer = bytearray(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n[")
    if manager:
        path = "presence_daily.log" if kind == "daily" else "presence_events.log"
        first = True
        for line in iter_lines(path):
            try:
                parts = line.split(",")
                if kind == "daily" and len(parts) >= 3:
                    item = '{{"d":"{}","sec":{},"n":{}}}'.format(parts[0], int(parts[1]), int(parts[2]))
                elif kind == "events" and len(parts) >= 4:
                    item = '{{"d":"{}","t":"{}","s":{},"a":{},"e":{}}}'.format(
                        parts[0], parts[1], int(parts[2]), int(parts[3]), _presence_epoch(parts[0], parts[1])
                    )
                else:
                    continue
            except (ValueError, TypeError, IndexError):
                print("Warning: Skipping malformed presence {} line.".format(kind))
                continue
            if not first:
                response_buffer.extend(b",")
            response_buffer.extend(item.encode())
            if len(response_buffer) >= 512:
                send_chunk(cl, response_buffer)
                response_buffer = bytearray()
            first = False
    response_buffer.extend(b"]")
    if response_buffer:
        send_chunk(cl, response_buffer)


def _presence_sessions(limit=40):
    """Return recent desk sessions derived from the event log."""
    manager = get_presence_manager()
    status = manager.get_status() if manager else {}
    current_state = bool(status.get("state"))
    now_epoch = int(status.get("now_epoch") or 0)
    sessions = []
    start = None

    for line in iter_lines("presence_events.log"):
        try:
            parts = line.split(",")
            if len(parts) < 4:
                continue
            event_date, event_time = parts[0], parts[1]
            event_state = int(parts[2])
            event_epoch = _presence_epoch(event_date, event_time)
            if not event_epoch:
                continue
            if event_state:
                if start is None:
                    start = (event_date, event_time, event_epoch)
            elif start is not None:
                duration = max(0, event_epoch - start[2])
                sessions.append({
                    "sd": start[0], "st": start[1],
                    "ed": event_date, "et": event_time, "sec": duration,
                })
                if len(sessions) > limit:
                    sessions.pop(0)
                start = None
        except (ValueError, TypeError, IndexError):
            continue

    if start is not None and current_state and now_epoch:
        now = time.localtime(now_epoch)
        end_date = "{:04d}{:02d}{:02d}".format(now[0], now[1], now[2])
        end_time = "{:02d}{:02d}{:02d}".format(now[3], now[4], now[5])
        sessions.append({
            "sd": start[0], "st": start[1],
            "ed": end_date, "et": end_time,
            "sec": max(0, now_epoch - start[2]),
        })
        if len(sessions) > limit:
            sessions.pop(0)
    return sessions


def _send_presence_sessions(cl):
    _send_json(cl, _presence_sessions())


def _send_presence_dashboard(cl):
    _send_html_file(cl, '/html/dashboard.bin')

def _save_settings_from_params(params):
    original_name = params.get("original_profile_name", "")
    new_name = params.get("profile_name", "")
    original_profile = config_manager.get_profile(original_name)

    wifi_password = params.get("password", "")
    if not wifi_password and original_profile:
        wifi_password = original_profile.get("wifi", {}).get("password", "")

    if not new_name or len(new_name) > 32 or any(ord(char) < 32 for char in new_name):
        raise ValueError("Profile name must contain 1-32 characters.")

    def bounded_int(name, default, minimum, maximum):
        value = int(params.get(name, str(default)))
        if value < minimum or value > maximum:
            raise ValueError("{} must be between {} and {}.".format(name, minimum, maximum))
        return value

    birthday_value = params.get("birthday", "0101")
    from image_manager import validate_event
    if validate_event(birthday_value) == "birthday":
        raise ValueError("Birthday must use MMDD format.")

    profile_data = {
        "name": new_name,
        "wifi": {
            "ssid": params.get("ssid", ""),
            "password": wifi_password
        },
        "weather_location": params.get("location", "Taipei"),
        "user": {
            "birthday": birthday_value,
            "light_threshold": bounded_int("light_threshold", 56000, 0, 65535),
            "presence_timeout_min": bounded_int("presence_timeout_min", 3, 1, 60),
            "image_interval_min": bounded_int("image_interval_min", 2, 1, 60),
            "timezone_offset": bounded_int("timezone_offset", 8, -12, 14)
        },
        "chime": {
            "enabled": params.get("chime_enabled") == "true",
            "interval": params.get("chime_interval", "hourly"),
            "pitch": bounded_int("chime_pitch", 880, 100, 5000),
            "volume": bounded_int("chime_volume", 80, 0, 100)
        }
    }

    api_key_input = params.get("api_key", "")
    ap_password_input = params.get("ap_mode_password", "")
    if ap_password_input and not 8 <= len(ap_password_input) <= 63:
        raise ValueError("AP password must contain 8-63 characters.")
    lan_admin_password = params.get("lan_admin_password", "")
    password_changed = bool(lan_admin_password)
    if password_changed and not PASSWORD_MIN_LENGTH <= len(lan_admin_password) <= 128:
        raise ValueError("管理密碼必須為 8-128 個字元。")
    global_updates = {
        "ap_mode.ssid": params.get("ap_mode_ssid", "Pi_Clock_AP"),
        "lan_admin.username": FIXED_ADMIN_USERNAME,
    }
    if api_key_input and not api_key_input.startswith("已設定") and "..." not in api_key_input:
        global_updates["weather_api_key"] = api_key_input
    elif params.get("clear_weather_api_key") == "true":
        global_updates["weather_api_key"] = ""
    if ap_password_input:
        global_updates["ap_mode.password"] = ap_password_input
    if lan_admin_password:
        global_updates["lan_admin.password"] = _password_hash(lan_admin_password)
    discord_webhook = params.get("discord_webhook_url", "")
    if discord_webhook:
        global_updates["discord_webhook_url"] = discord_webhook
    elif params.get("clear_discord_webhook") == "true":
        global_updates["discord_webhook_url"] = ""
    if profile_data["wifi"]["ssid"]:
        global_updates["setup_complete"] = True

    config_manager.apply_profile_update(
        original_name,
        profile_data,
        global_updates=global_updates,
        activate=True,
        mark_connected=True,
    )
    if password_changed:
        _clear_session()

def handle_config_request(cl, request, require_auth=False, client_key="unknown"):
    from display_manager import update_display_Restart

    if not request:
        cl.close()
        return

    method, target = _request_line(request)
    path = target.split("?", 1)[0]
    print("Request: {} {}".format(method, target.split("?", 1)[0]))

    if method == "GET" and path == "/login":
        _send_html_file(cl, "/html/login.bin")
        cl.close()
        return

    if _handle_auth_api(cl, request, client_key):
        cl.close()
        return

    if _handle_image_api(cl, request, require_auth):
        cl.close()
        return

    if path == "/favicon.ico":
        cl.send(b"HTTP/1.0 404 Not Found\r\nCache-Control: no-store\r\n\r\n")
        cl.close()
        return

    auth_required = _auth_required_for_request(require_auth)
    if not _admin_password_configured() and path != "/":
        _send_auth_required(cl, api=_request_is_api(target))
        cl.close()
        return

    if auth_required and not _is_lan_authorized(request):
        _send_auth_required(cl, api=_request_is_api(target))
        cl.close()
        return

    if method == "GET" and path == "/images":
        _send_html_file(cl, "/html/images.bin")
        cl.close()
        return

    if _handle_config_api(cl, request, require_auth):
        cl.close()
        return

    if method == "GET" and path == "/":
        if not _admin_password_configured():
            send_chunk(cl, b"HTTP/1.0 302 Found\r\nLocation: /login\r\nCache-Control: no-store\r\n\r\n")
        else:
            _send_html_file(cl, "/html/settings.bin")
        cl.close()
        return

    if method == "GET" and path in ("/desk", "/dashboard"):
        _send_presence_dashboard(cl)
        cl.close()
        return

    if method == "GET" and path in ("/api/desk/status", "/presence/status"):
        manager = get_presence_manager()
        status = manager.get_status() if manager else {"state": 0, "current_date": "", "adc": -1, "threshold": -1, "session_seconds": 0, "segment_seconds": 0, "today_seconds": 0, "last_change_date": "", "last_change_time": "", "transitions": 0, "now_epoch": 0}
        _send_json(cl, status)
        cl.close()
        return

    if method == "GET" and path in ("/api/desk/timeline", "/presence/events"):
        _send_presence_lines(cl, "events")
        cl.close()
        return

    if method == "GET" and path in ("/api/desk/daily", "/presence/daily"):
        _send_presence_lines(cl, "daily")
        cl.close()
        return

    if method == "GET" and path == "/api/desk/sessions":
        _send_presence_sessions(cl)
        cl.close()
        return

    if method == "GET" and path in ("/api/debug/adc", "/adc"):
        adc_value = machine.ADC(machine.Pin(26)).read_u16()
        response = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{\"adc\": " + str(adc_value) + "}"
        cl.send(response.encode())
        cl.close()
        return

    if method == "POST" and path == "/test_chime":
        try:
            params = parse_query_string(_read_request_body(cl, request))
        except (ValueError, TypeError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_request", "message": str(exc)})
            cl.close()
            return
        if not _request_csrf_valid(request, params):
            _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
            cl.close()
            return

        try:
            from chime import Chime

            chime_obj = Chime()
            chime_obj.do_chime(
                pitch=int(params.get("pitch", "880")),
                volume=int(params.get("volume", "80"))
            )
            chime_obj.deinit()
            _send_json_status(cl, 200, {"tested": True})
        except Exception as e:
            print("Error: Chime test failed. {}".format(e))
            _send_json_status(cl, 500, {"error": "chime_failed", "message": "測試響聲失敗。"})
        cl.close()
        return

    if method == "GET" and path == "/edit_profile":
        params = _get_query_params(request)
        profile = config_manager.get_profile(params.get("name", ""))
        if profile:
            cl.send(b"HTTP/1.0 302 Found\r\nLocation: /\r\nCache-Control: no-store\r\n\r\n")
        else:
            _send_json_status(cl, 404, {"error": "not_found", "message": "Profile not found."})
        cl.close()
        return

    if method == "POST" and path == "/new_profile":
        try:
            params = parse_query_string(_read_request_body(cl, request))
        except (ValueError, TypeError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_request", "message": str(exc)})
            cl.close()
            return
        if not _request_csrf_valid(request, params):
            _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
            cl.close()
            return

        new_name = params.get("name", "")
        if not new_name or len(new_name) > 32 or any(ord(char) < 32 for char in new_name):
            _send_json_status(cl, 400, {"error": "invalid_name", "message": "Profile name is invalid."})
            cl.close()
            return

        base_profile = config_manager.get_active_profile()
        new_profile = {
            "name": new_name,
            "wifi": {"ssid": "", "password": ""},
            "weather_location": base_profile.get("weather_location", "Taipei") if base_profile else "Taipei",
            "user": dict(base_profile.get("user", {
                "birthday": "0101",
                "light_threshold": 56000,
                "presence_timeout_min": 3,
                "image_interval_min": 2,
                "timezone_offset": 8
            })) if base_profile else {
                "birthday": "0101",
                "light_threshold": 56000,
                "presence_timeout_min": 3,
                "image_interval_min": 2,
                "timezone_offset": 8
            },
            "chime": dict(base_profile.get("chime", {
                "enabled": True,
                "interval": "hourly",
                "pitch": 880,
                "volume": 80
            })) if base_profile else {
                "enabled": True,
                "interval": "hourly",
                "pitch": 880,
                "volume": 80
            }
        }

        try:
            config_manager.add_profile(new_profile)
            _send_json_status(cl, 200, {"saved": True})
        except ValueError as exc:
            _send_json_status(cl, 400, {"error": "invalid_name", "message": str(exc)})
        cl.close()
        return

    if method == "POST" and path == "/delete_profile":
        try:
            params = parse_query_string(_read_request_body(cl, request))
        except (ValueError, TypeError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_request", "message": str(exc)})
            cl.close()
            return
        if not _request_csrf_valid(request, params):
            _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
            cl.close()
            return

        try:
            config_manager.delete_profile(params.get("name", ""))
            _send_json_status(cl, 200, {"deleted": True})
        except ValueError as e:
            _send_json_status(cl, 400, {"error": "invalid_profile", "message": str(e)})
        cl.close()
        return

    if method == "POST" and path == "/factory_reset":
        try:
            params = parse_query_string(_read_request_body(cl, request))
        except (ValueError, TypeError) as exc:
            _send_json_status(cl, 400, {"error": "invalid_request", "message": str(exc)})
            cl.close()
            return
        if not _request_csrf_valid(request, params):
            _send_json_status(cl, 403, {"error": "csrf", "message": "CSRF token is invalid."})
            cl.close()
            return
        reset_key = _reset_failure_key(client_key)
        if _failure_is_limited(_RESET_FAILURES, reset_key, 3):
            _send_json_status(cl, 429, {"error": "rate_limited", "message": "重置嘗試過多，請稍後再試。"})
            cl.close()
            return
        if not _constant_time_equal(params.get("confirmation", ""), "RESET"):
            _record_failure(_RESET_FAILURES, reset_key, 3)
            _send_json_status(cl, 400, {"error": "confirmation_required", "message": "請輸入 RESET 確認。"})
            cl.close()
            return
        _clear_failure(_RESET_FAILURES, reset_key)

        try:
            factory_reset()
            _send_html_file(cl, '/html/reset.bin')
            cl.close()
            update_display_Restart()
            time.sleep(5)
            machine.reset()
        except Exception as e:
            print("Error: Factory reset failed. {}".format(e))
            _send_json_status(cl, 500, {"error": "reset_failed", "message": "完全重置失敗。"})
            cl.close()
        return

    _send_json_status(cl, 404, {"error": "not_found", "message": "Page not found."})
    cl.close()

class LanConfigServer:
    def __init__(self):
        addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(addr)
        self.socket.listen(1)
        self.socket.settimeout(0)
        print(f"LAN web server listening on {addr}")

    def poll(self):
        cl = None
        had_client = False
        try:
            cl, addr = self.socket.accept()
            had_client = True
            print(f"Info: LAN client connected from {addr}.")
            cl.settimeout(3.0)
            request = _read_http_request(cl)
            handle_config_request(cl, request, require_auth=True, client_key=addr[0])
            if _consume_reboot_request():
                from display_manager import update_display_Restart

                update_display_Restart()
                time.sleep(1)
                machine.reset()
        except OSError:
            if cl:
                try:
                    cl.close()
                except:
                    pass
        except Exception as e:
            print(f"Error: LAN server error. {e}")
            if cl:
                try:
                    cl.close()
                except:
                    pass
        finally:
            if had_client:
                gc.collect()

    def close(self):
        try:
            self.socket.close()
        except:
            pass

def create_lan_config_server():
    try:
        return LanConfigServer()
    except Exception as e:
        print(f"Error: Failed to start LAN web server. {e}")
        gc.collect()
        return None

def run_web_server():
    """Run the shared configuration server while AP-mode lifecycle hooks stay active."""
    from display_manager import update_display_Restart
    from hardware_manager import HardwareManager
    from image_manager import image_store

    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(1)
    hardware = HardwareManager()
    start_time = time.time()
    last_activity_time = start_time

    def reset_callback(button_index):
        print("Button {} long pressed in AP mode.".format(button_index + 1))
        try:
            server.close()
        except Exception:
            pass
        reset_wifi_and_reboot()

    print("AP web server listening on {}".format(addr))
    while True:
        client = None
        try:
            if hardware.handle_button_long_press(reset_callback):
                return

            now = time.time()
            timeout = 900 if now - last_activity_time < 300 else 600
            if now - start_time > timeout:
                print("Info: AP mode timeout. Restoring last connected profile.")
                last_profile = config_manager.get_last_connected_profile_name()
                if last_profile:
                    try:
                        config_manager.set_active_profile(last_profile)
                    except Exception:
                        pass
                server.close()
                machine.reset()

            server.settimeout(1.0)
            try:
                client, client_addr = server.accept()
            except OSError:
                continue

            last_activity_time = time.time()
            print("Info: AP client connected from {}.".format(client_addr))
            client.settimeout(3.0)
            request = _read_http_request(client)
            handle_config_request(client, request, require_auth=False, client_key=client_addr[0])

            preview = image_store.consume_preview()
            if preview:
                from display_manager import update_page_image_preview
                update_page_image_preview(preview[0], preview[1], preview[2])
            if _consume_reboot_request():
                from display_manager import update_display_Restart

                update_display_Restart()
                time.sleep(1)
                server.close()
                machine.reset()
        except Exception as exc:
            print("Error: AP server request failed. {}".format(exc))
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
            gc.collect()


def wifi_manager():
    """
    Main WiFi manager with multi-profile support and intelligent connection logic.
    Scans networks, matches with known profiles, tries to connect by priority.
    """
    # Check if force AP mode is enabled
    if config_manager.get_global("force_ap_mode", False):
        print("Info: Force AP mode detected. Entering AP mode directly...")
        # Clear the flag
        config_manager.set_global("force_ap_mode", False)
        # Jump directly to AP mode (skip WiFi connection attempts)
        # Set sta inactive and go to AP mode section
        sta = network.WLAN(network.STA_IF)
        sta.active(False)
        # Skip to AP mode
        ap = network.WLAN(network.AP_IF)
        ap.active(True)

        ap_ssid = config_manager.get("ap_mode.ssid", "Pi_Clock_AP")
        ap_password = config_manager.get("ap_mode.password", "12345678")

        ap.config(ssid=ap_ssid, password=ap_password)
        ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))

        from display_manager import update_display_AP

        update_display_AP(ap_ssid, ap_password, '192.168.4.1')

        print(f"Info: AP Mode enabled (forced). SSID: {ap_ssid}, IP: 192.168.4.1")

        # Start web server
        run_web_server()

        return None

    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    print("Info: Scanning for available networks...")
    available_networks = scan_networks()  # Returns list of {ssid, rssi}

    if not available_networks:
        print("Warning: No networks found in scan.")
    else:
        print(f"Info: Found {len(available_networks)} networks.")

    # Find matching profiles
    matching_profiles = []
    for net in available_networks:
        ssid = net['ssid']
        profile = config_manager.find_profile_by_ssid(ssid)
        if profile:
            matching_profiles.append({
                'profile': profile,
                'rssi': net['rssi']
            })

    if not matching_profiles:
        print("Info: No known networks found. Entering AP mode.")
    else:
        print(f"Info: Found {len(matching_profiles)} known network(s).")

        # Sort by priority:
        # 1. Last connected profile first
        # 2. Then by signal strength (rssi, higher is better)
        last_connected = config_manager.get_last_connected_profile_name()

        # Separate last connected from others
        priority_profile = None
        other_profiles = []

        for match in matching_profiles:
            if match['profile']['name'] == last_connected:
                priority_profile = match
            else:
                other_profiles.append(match)

        # Sort others by signal strength
        other_profiles.sort(key=lambda x: x['rssi'], reverse=True)

        # Build final connection order
        connection_order = []
        if priority_profile:
            connection_order.append(priority_profile)
        connection_order.extend(other_profiles)

        # Try to connect in order
        for match in connection_order:
            profile = match['profile']
            ssid = profile['wifi']['ssid']
            password = profile['wifi']['password']
            rssi = match['rssi']

            print(f"Info: Trying to connect to '{ssid}' (signal: {rssi} dBm, profile: '{profile['name']}')...")

            sta.connect(ssid, password)

            timeout = 30
            while timeout > 0 and not sta.isconnected():
                time.sleep(1)
                timeout -= 1

            if sta.isconnected():
                print(f"Success: Connected to '{ssid}'.")
                print(f"IP Address: {sta.ifconfig()[0]}")

                # Set this profile as active and last connected
                config_manager.set_active_profile(profile['name'])
                config_manager.set_last_connected_profile(profile['name'])

                print(f"Info: Active profile set to '{profile['name']}'.")
                return sta
            else:
                print(f"Warning: Failed to connect to '{ssid}'.")

    # Connection failed, start AP mode
    print("Info: Starting AP mode for configuration.")

    ap = network.WLAN(network.AP_IF)
    ap.active(True)

    ap_ssid = config_manager.get("ap_mode.ssid", "Pi_Clock_AP")
    ap_password = config_manager.get("ap_mode.password", "12345678")

    ap.config(ssid=ap_ssid, password=ap_password)
    ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))

    from display_manager import update_display_AP

    update_display_AP(ap_ssid, ap_password, '192.168.4.1')

    print(f"Info: AP Mode enabled. SSID: {ap_ssid}, IP: 192.168.4.1")

    # Start web server
    run_web_server()

    return None
