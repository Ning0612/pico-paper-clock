# wifi_manager.py
import network
import socket
import time
import machine
import gc
import ujson
import ubinascii
from display_manager import update_display_Restart, update_display_AP
from config_manager import config_manager
from chime import Chime
from hardware_manager import HardwareManager
from presence_manager import get_presence_manager, iter_lines
from image_manager import IMAGE_SPECS, ImageStoreError, filesystem_free, image_store

API_VERSION = 1
_REBOOT_REQUESTED = False
# Pico W flash writes and Wi-Fi scheduling can make a normal 2-5 KiB upload
# span several seconds; keep a finite slow-client deadline without rejecting it.
REQUEST_READ_DEADLINE_MS = 8000
_REQUEST_DEADLINE = None


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

# Phase 3: CSRF 防護 - 全域 Token (啟動時生成)
# 使用時間戳 + ADC 噪音生成隨機 token (MicroPython 相容)
def _generate_csrf_token():
    """Generates a simple CSRF token using timestamp and ADC noise."""
    try:
        # 使用 ADC 讀取（電磁噪音）和時間戳生成隨機性
        adc = machine.ADC(machine.Pin(26))
        noise = adc.read_u16()
        timestamp = time.ticks_ms()
        # 組合生成 token (16進位字串)
        token_value = (timestamp * 31 + noise) & 0xFFFFFFFF
        return hex(token_value)[2:]  # 移除 '0x' 前綴
    except:
        # 降級方案：僅使用時間戳
        return hex(time.ticks_ms() & 0xFFFFFFFF)[2:]

CSRF_TOKEN = _generate_csrf_token()

def verify_csrf_token(params):
    """Verifies CSRF token from request parameters.

    Args:
        params: Dictionary of request parameters

    Returns:
        bool: True if token is valid, False otherwise
    """
    token = params.get("csrf_token", "")
    is_valid = token == CSRF_TOKEN
    if not is_valid:
        print("CSRF validation failed.")
    return is_valid

def reset_wifi_and_reboot():
    """Sets force AP mode flag and reboots to enter configuration mode."""
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

    print("Factory reset complete. Default configuration restored.")
    return True


def unquote(string):
    """Decodes URL-encoded strings (MicroPython compatible) with UTF-8 support."""
    if not string:
        return ""

    res = []
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
            res.append(ord(char))
            i += 1

    try:
        return bytes(res).decode('utf-8')
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


HTML_ERROR_PAGE_PREFIX = "HTTP/1.0 400 Bad Request\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><head><meta charset=\"utf-8\"><title>錯誤</title></head><body><h1>儲存失敗</h1><p>".encode("utf-8")
HTML_ERROR_PAGE_SUFFIX = "</p><a href=\"/\">返回</a></body></html>".encode("utf-8")

HTML_RESET_ERROR_PREFIX = "HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><head><meta charset=\"utf-8\"><title>錯誤</title></head><body><h1>重置失敗</h1><p>".encode("utf-8")
HTML_RESET_ERROR_SUFFIX = "</p><a href=\"/\">返回</a></body></html>".encode("utf-8")

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
        "csrf_token": CSRF_TOKEN,
        "profiles": config_manager.list_profiles(),
        "active_profile": config_manager.get_active_profile_name(),
        "profile": safe_profile,
        "global": {
            "ap_mode_ssid": config_manager.get_global("ap_mode.ssid", "Pi_Clock_AP"),
            "weather_api_key_configured": bool(config_manager.get_global("weather_api_key", "")),
            "discord_webhook_configured": bool(config_manager.get_global("discord_webhook_url", "")),
            "lan_admin_username": config_manager.get_global("lan_admin.username", "admin"),
        },
    }


def _handle_config_api(cl, request, require_auth):
    global _REBOOT_REQUESTED
    method, target = _request_line(request)
    path = target.split("?", 1)[0]
    if path == "/api/v1/config" and method == "GET":
        params = _get_query_params(target)
        _send_json_status(cl, 200, _config_payload(params.get("profile")))
        return True
    if path == "/api/v1/networks" and method == "GET":
        _send_json_status(cl, 200, {"networks": _get_page_networks(require_auth)})
        return True
    if path == "/api/v1/config" and method == "POST":
        try:
            body = _read_request_body(cl, request)
            params = parse_query_string(body)
            if not verify_csrf_token(params):
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

def _expected_basic_auth_header():
    username = config_manager.get_global("lan_admin.username", "admin") or "admin"
    password = config_manager.get_global("lan_admin.password", "admin") or "admin"
    token = ubinascii.b2a_base64((username + ":" + password).encode()).decode().strip()
    return "Basic " + token

def _send_auth_required(cl):
    cl.send(b'HTTP/1.0 401 Unauthorized\r\nWWW-Authenticate: Basic realm="Pi Clock LAN Admin"\r\n\r\nUnauthorized')

def _is_lan_authorized(request):
    return _request_headers(request).get("authorization") == _expected_basic_auth_header()

def _get_page_networks(require_auth=False):
    if not require_auth:
        return scan_networks()

    active_profile = config_manager.get_active_profile()
    ssid = active_profile.get("wifi", {}).get("ssid", "") if active_profile else ""
    return [{"ssid": ssid, "rssi": 0}] if ssid else []


def _send_json(cl, value):
    cl.send(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
    cl.send(ujson.dumps(value).encode())


def _send_json_status(cl, status, value):
    reason = {
        200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized",
        403: "Forbidden", 404: "Not Found", 409: "Conflict", 411: "Length Required",
        413: "Payload Too Large", 500: "Internal Server Error",
        507: "Insufficient Storage",
    }.get(status, "Error")
    header = "HTTP/1.0 {} {}\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n".format(status, reason)
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


def _handle_image_api(cl, request):
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

    if not _is_lan_authorized(request):
        _send_auth_required(cl)
        return True

    headers = _request_headers(request)
    if "transfer-encoding" in headers or "_duplicate_content-length" in headers:
        _send_json_status(cl, 400, {"error": "invalid_framing", "message": "Only one identity Content-Length is supported."})
        return True
    if method in ("PUT", "POST", "DELETE") and headers.get("x-pico-clock-api") != "1":
        _send_json_status(cl, 400, {"error": "client_header_required", "message": "X-Pico-Clock-API: 1 is required."})
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
    cl.send(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n[")
    if manager:
        path = "presence_daily.log" if kind == "daily" else "presence_events.log"
        first = True
        for line in iter_lines(path):
            parts = line.split(",")
            if kind == "daily" and len(parts) >= 3:
                item = '{{"d":"{}","sec":{},"n":{}}}'.format(parts[0], int(parts[1]), int(parts[2]))
            elif kind == "events" and len(parts) >= 4:
                item = '{{"d":"{}","t":"{}","s":{},"a":{},"e":{}}}'.format(
                    parts[0], parts[1], int(parts[2]), int(parts[3]), _presence_epoch(parts[0], parts[1])
                )
            else:
                continue
            if not first:
                cl.send(b",")
            cl.send(item.encode())
            first = False
    cl.send(b"]")


def _send_presence_dashboard(cl):
    send_chunk(cl, b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n")
    _send_file_chunks(cl, '/html/dashboard.bin')

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
    global_updates = {
        "ap_mode.ssid": params.get("ap_mode_ssid", "Pi_Clock_AP"),
        "lan_admin.username": params.get("lan_admin_username", "admin") or "admin",
    }
    if api_key_input and not api_key_input.startswith("已設定") and "..." not in api_key_input:
        global_updates["weather_api_key"] = api_key_input
    elif params.get("clear_weather_api_key") == "true":
        global_updates["weather_api_key"] = ""
    if ap_password_input:
        global_updates["ap_mode.password"] = ap_password_input
    if lan_admin_password:
        global_updates["lan_admin.password"] = lan_admin_password
    discord_webhook = params.get("discord_webhook_url", "")
    if discord_webhook:
        global_updates["discord_webhook_url"] = discord_webhook
    elif params.get("clear_discord_webhook") == "true":
        global_updates["discord_webhook_url"] = ""

    config_manager.apply_profile_update(
        original_name,
        profile_data,
        global_updates=global_updates,
        activate=True,
        mark_connected=True,
    )

def handle_config_request(cl, request, require_auth=False):
    if not request:
        cl.close()
        return

    method, target = _request_line(request)
    print("Request: {} {}".format(method, target.split("?", 1)[0]))

    if _handle_image_api(cl, request):
        cl.close()
        return

    if method == "GET" and target.split("?", 1)[0] == "/images":
        if not _is_lan_authorized(request):
            _send_auth_required(cl)
        else:
            send_chunk(cl, b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n\r\n")
            _send_file_chunks(cl, "/html/images.bin")
        cl.close()
        return

    if require_auth and not _is_lan_authorized(request):
        _send_auth_required(cl)
        cl.close()
        return

    if _handle_config_api(cl, request, require_auth):
        cl.close()
        return

    if "GET /favicon.ico" in request:
        cl.send(b"HTTP/1.0 404 Not Found\r\n\r\n")
        cl.close()
        return

    if "GET /dashboard" in request:
        _send_presence_dashboard(cl)
        cl.close()
        return

    if "GET /presence/status" in request:
        manager = get_presence_manager()
        status = manager.get_status() if manager else {"state": 0, "adc": -1, "threshold": -1, "session_seconds": 0, "segment_seconds": 0, "today_seconds": 0, "last_change_date": "", "last_change_time": "", "transitions": 0, "now_epoch": 0}
        _send_json(cl, status)
        cl.close()
        return

    if "GET /presence/events" in request:
        _send_presence_lines(cl, "events")
        cl.close()
        return

    if "GET /presence/daily" in request:
        _send_presence_lines(cl, "daily")
        cl.close()
        return

    if "GET /adc" in request:
        adc_value = machine.ADC(machine.Pin(26)).read_u16()
        response = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"adc\": " + str(adc_value) + "}"
        cl.send(response.encode())
        cl.close()
        return

    if "GET /test_chime" in request:
        params = _get_query_params(request)
        if not verify_csrf_token(params):
            cl.send(b"HTTP/1.1 403 Forbidden\r\n\r\nCSRF token invalid")
            cl.close()
            return

        try:
            chime_obj = Chime()
            chime_obj.do_chime(
                pitch=int(params.get("pitch", "880")),
                volume=int(params.get("volume", "80"))
            )
            chime_obj.deinit()
            cl.send(b"HTTP/1.0 200 OK\r\n\r\nOK")
        except Exception as e:
            print(f"Error: Chime test failed. {e}")
            cl.send(b"HTTP/1.0 500 Internal Server Error\r\n\r\nError")
        cl.close()
        return

    if "GET /edit_profile?" in request:
        params = _get_query_params(request)
        profile = config_manager.get_profile(params.get("name", ""))
        if profile:
            cl.send(b"HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n")
        else:
            cl.send(b"HTTP/1.0 404 Not Found\r\n\r\nProfile not found")
        cl.close()
        return

    if "GET /new_profile?" in request:
        params = _get_query_params(request)
        if not verify_csrf_token(params):
            cl.send(b"HTTP/1.1 403 Forbidden\r\n\r\nCSRF token invalid")
            cl.close()
            return

        new_name = params.get("name", "")
        if not new_name or len(new_name) > 32 or any(ord(char) < 32 for char in new_name):
            cl.send(b"HTTP/1.0 400 Bad Request\r\n\r\nInvalid profile name")
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
                "image_interval_min": 2,
                "timezone_offset": 8
            })) if base_profile else {
                "birthday": "0101",
                "light_threshold": 56000,
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
            cl.send(b"HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n")
        except ValueError:
            cl.send(b"HTTP/1.0 400 Bad Request\r\n\r\nProfile name already exists")
        cl.close()
        return

    if "GET /delete_profile?" in request:
        params = _get_query_params(request)
        if not verify_csrf_token(params):
            cl.send(b"HTTP/1.1 403 Forbidden\r\n\r\nCSRF token invalid")
            cl.close()
            return

        try:
            config_manager.delete_profile(params.get("name", ""))
            cl.send(b"HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n")
        except ValueError as e:
            cl.send(("HTTP/1.0 400 Bad Request\r\n\r\n" + str(e)).encode())
        cl.close()
        return

    if "GET /factory_reset" in request:
        params = _get_query_params(request)
        if not verify_csrf_token(params):
            cl.send(b"HTTP/1.1 403 Forbidden\r\n\r\nCSRF token invalid")
            cl.close()
            return

        try:
            factory_reset()
            _send_file_chunks(cl, '/html/reset.bin')
            cl.close()
            update_display_Restart()
            time.sleep(5)
            machine.reset()
        except Exception as e:
            cl.send(HTML_RESET_ERROR_PREFIX)
            cl.send(str(e).encode('utf-8'))
            cl.send(HTML_RESET_ERROR_SUFFIX)
            cl.close()
        return

    if "GET /save_profile?" in request:
        params = _get_query_params(request)
        if not verify_csrf_token(params):
            cl.send(b"HTTP/1.1 403 Forbidden\r\n\r\nCSRF token invalid")
            cl.close()
            return

        try:
            _save_settings_from_params(params)
            _send_file_chunks(cl, '/html/success.bin')
            cl.close()
            update_display_Restart()
            time.sleep(5)
            machine.reset()
        except Exception as e:
            print(f"Error: Failed to save profile. {e}")
            cl.send(HTML_ERROR_PAGE_PREFIX)
            cl.send(str(e).encode('utf-8'))
            cl.send(HTML_ERROR_PAGE_SUFFIX)
            cl.close()
        return

    try:
        send_chunk(cl, b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n\r\n")
        _send_file_chunks(cl, "/html/settings.bin")
    except Exception as e:
        print(f"Error: Failed to send page. {e}")
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
            handle_config_request(cl, request, require_auth=True)
            if _consume_reboot_request():
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
            handle_config_request(client, request, require_auth=False)

            preview = image_store.consume_preview()
            if preview:
                from display_manager import update_page_image_preview
                update_page_image_preview(preview[0], preview[1], preview[2])
            if _consume_reboot_request():
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

    update_display_AP(ap_ssid, ap_password, '192.168.4.1')

    print(f"Info: AP Mode enabled. SSID: {ap_ssid}, IP: 192.168.4.1")

    # Start web server
    run_web_server()

    return None
