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
        print(f"CSRF validation failed: expected={CSRF_TOKEN}, got={token}")
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


HTML_SIDEBAR_END = b"<button class=\"btn btn-primary\" onclick=\"createNewProfile()\" style=\"white-space:nowrap;\">➕ 新增</button></div></div><div class=\"main-content\"><div class=\"container\"><h1>設定檔編輯</h1><form id=\"profile-form\" action=\"/save_profile\" method=\"get\">"



HTML_ERROR_PAGE_PREFIX = b"HTTP/1.0 400 Bad Request\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><head><meta charset=\"utf-8\"><title>錯誤</title></head><body><h1>儲存失敗</h1><p>"
HTML_ERROR_PAGE_SUFFIX = b"</p><a href=\"/\">返回</a></body></html>"

HTML_RESET_ERROR_PREFIX = b"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><head><meta charset=\"utf-8\"><title>錯誤</title></head><body><h1>重置失敗</h1><p>"
HTML_RESET_ERROR_SUFFIX = b"</p><a href=\"/\">返回</a></body></html>"

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

def send_html_page(cl, networks, current_profile=None):
    """Sends configuration HTML page using chunked sending with improved stability and UI."""

    # Get all profiles
    profiles = []
    for profile_name in config_manager.list_profiles():
        profile = config_manager.get_profile(profile_name)
        if profile:
            profiles.append(profile)

    # Current active profile
    if not current_profile:
        current_profile = config_manager.get_active_profile()

    # Global settings
    api_key = config_manager.get_global("weather_api_key", "")
    ap_ssid = config_manager.get("ap_mode.ssid", "Pi_Clock_AP")
    ap_password = config_manager.get("ap_mode.password", "12345678")
    discord_webhook_url = config_manager.get_global("discord_webhook_url", "")
    lan_admin_username = config_manager.get_global("lan_admin.username", "admin")
    adc_value = machine.ADC(machine.Pin(26)).read_u16()

    # Current profile settings
    profile_name = current_profile.get("name", "") if current_profile else ""
    wifi_ssid = current_profile.get("wifi", {}).get("ssid", "") if current_profile else ""
    location = current_profile.get("weather_location", "Taipei") if current_profile else "Taipei"
    birthday = current_profile.get("user", {}).get("birthday", "0101") if current_profile else "0101"
    image_interval = current_profile.get("user", {}).get("image_interval_min", 2) if current_profile else 2
    light_threshold = current_profile.get("user", {}).get("light_threshold", 56000) if current_profile else 56000
    timezone = current_profile.get("user", {}).get("timezone_offset", 8) if current_profile else 8
    chime_enabled = "checked" if (current_profile and current_profile.get("chime", {}).get("enabled", False)) else ""
    chime_interval = current_profile.get("chime", {}).get("interval", "hourly") if current_profile else "hourly"
    chime_pitch = current_profile.get("chime", {}).get("pitch", 880) if current_profile else 880
    chime_volume = current_profile.get("chime", {}).get("volume", 80) if current_profile else 80

    # 1. Send header and CSS (使用 send_chunk)
    _send_file_chunks(cl, '/html/header.bin')

    # 2. Send profile selector (UI 改良：手機版下拉選單)
    active_profile_name = config_manager.get_active_profile_name()

    # 使用 <select> 下拉選單取代橫向捲動的 <div> 列表（事件綁定在 JavaScript 中）
    send_chunk(cl, '<select id="profile-select">'.encode('utf-8'))

    send_chunk(cl, '<option value="" disabled>-- 切換設定檔 --</option>'.encode('utf-8'))

    for p in profiles:
        # selected 指向正在編輯的設定檔
        selected = "selected" if p["name"] == profile_name else ""

        # 顯示設定檔名稱，加上狀態標籤
        option_text = p["name"]
        if p["name"] == active_profile_name and p["name"] == profile_name:
            # 既是啟用的又是正在編輯的
            option_text += " ●"
        elif p["name"] == active_profile_name:
            # 僅是啟用的
            option_text += " (啟用)"
        elif p["name"] == profile_name:
            # 僅是正在編輯的
            option_text += " ●"

        send_chunk(cl, f'<option value="{html_escape(p["name"])}" {selected}>{html_escape(option_text)}</option>'.encode('utf-8'))

    send_chunk(cl, b'</select>')

    # 3. Send sidebar end and form start (包含新增按鈕)
    send_chunk(cl, HTML_SIDEBAR_END)

    # 4. Send form fields (全部改用 send_chunk)
    # Phase 3: CSRF Token (隱藏欄位)
    send_chunk(cl, f'<input type="hidden" name="csrf_token" value="{CSRF_TOKEN}">'.encode('utf-8'))
    send_chunk(cl, f'<input type="hidden" id="original_profile_name" name="original_profile_name" value="{html_escape(profile_name)}">'.encode('utf-8'))
    send_chunk(cl, b'<div class="button-group"><button type="button" class="btn btn-primary" onclick="window.location.href=\'/dashboard\'">&#26700;&#21069;&#29376;&#24907;&#20736;&#34920;&#26495;</button></div>')
    send_chunk(cl, f'<fieldset><legend>設定檔資訊</legend><div class="form-group"><label for="profile_name">設定檔名稱:</label><input id="profile_name" name="profile_name" value="{html_escape(profile_name)}" required></div></fieldset>'.encode('utf-8'))

    # WiFi section
    send_chunk(cl, '<fieldset><legend>Wi-Fi 連線</legend><div class="form-group"><label for="ssid">SSID:</label><select id="ssid" name="ssid">'.encode('utf-8'))
    for net in networks:
        ssid = net['ssid'] if isinstance(net, dict) else net
        sel = "selected" if ssid == wifi_ssid else ""
        send_chunk(cl, f'<option value="{html_escape(ssid)}" {sel}>{html_escape(ssid)}</option>'.encode('utf-8'))
    # 密碼欄位不顯示已儲存密碼（安全性改進）
    send_chunk(cl, '</select></div><div class="form-group"><label for="password">密碼:</label><input type="password" id="password" name="password" placeholder="已設定（留空表示不修改）"></div></fieldset>'.encode('utf-8'))

    # Weather section
    send_chunk(cl, f'<fieldset><legend>天氣與個人化</legend><div class="form-group"><label for="location">天氣地點:</label><input id="location" name="location" value="{html_escape(location)}"></div><div class="form-group"><label for="birthday">生日 (MMDD):</label><input id="birthday" name="birthday" value="{html_escape(birthday)}"></div></fieldset>'.encode('utf-8'))

    # System settings
    send_chunk(cl, f'<fieldset><legend>系統設定</legend><div class="form-group"><label for="image_interval_min">圖片輪播間隔 (分鐘):</label><input type="number" id="image_interval_min" name="image_interval_min" value="{html_escape(str(image_interval))}"></div><div class="form-group"><label for="light_threshold">光感臨界值 (ADC):</label><input type="number" id="light_threshold" name="light_threshold" value="{html_escape(str(light_threshold))}"><p class="info">目前光感值: <span class="adc-value" id="adc-value">{html_escape(str(adc_value))}</span></p></div><div class="form-group"><label for="timezone_offset">時區偏移 (小時):</label><input type="number" id="timezone_offset" name="timezone_offset" value="{html_escape(str(timezone))}"></div></fieldset>'.encode('utf-8'))

    # Chime settings
    hourly_sel = "selected" if chime_interval == "hourly" else ""
    half_sel = "selected" if chime_interval == "half_hourly" else ""
    send_chunk(cl, f'<fieldset><legend>定時響聲</legend><div class="form-group" style="display:flex;align-items:center;"><input type="checkbox" id="chime_enabled" name="chime_enabled" value="true" {chime_enabled}><label for="chime_enabled" style="margin-bottom:0;">啟用定時響聲</label></div><div class="form-group"><label for="chime_interval">響聲間隔:</label><select id="chime_interval" name="chime_interval"><option value="hourly" {hourly_sel}>每小時</option><option value="half_hourly" {half_sel}>每半小時</option></select></div><div class="form-group"><label for="chime_pitch">音高 (Hz):</label><input type="number" id="chime_pitch" name="chime_pitch" value="{html_escape(str(chime_pitch))}"></div><div class="form-group"><label for="chime_volume">音量 (0-100):</label><input type="number" id="chime_volume" name="chime_volume" value="{html_escape(str(chime_volume))}"><button type="button" class="btn btn-warning" onclick="testChime()">🔊 測試響聲</button></div></fieldset>'.encode('utf-8'))

    # Global settings (Phase 2: 敏感資訊保護 - 不顯示已儲存密碼)
    # API Key 顯示遮罩或留空
    api_key_display = f"{api_key[:7]}...{api_key[-4:]}" if api_key and len(api_key) > 11 else ("已設定" if api_key else "")
    send_chunk(cl, f'<fieldset><legend>全局設定 (所有設定檔共用)</legend><div class="form-group"><label for="api_key">天氣 API Key:</label><input type="text" id="api_key" name="api_key" value="{html_escape(api_key_display)}" placeholder="留空表示不修改" readonly></div><div class="form-group"><label for="ap_mode_ssid">AP 模式 SSID:</label><input id="ap_mode_ssid" name="ap_mode_ssid" value="{html_escape(ap_ssid)}"></div><div class="form-group"><label for="ap_mode_password">AP 模式密碼:</label><input type="password" id="ap_mode_password" name="ap_mode_password" placeholder="已設定（留空表示不修改）"></div></fieldset>'.encode('utf-8'))

    send_chunk(cl, f'<fieldset><legend>LAN Admin & Discord</legend><div class="form-group"><label for="discord_webhook_url">Discord Webhook URL:</label><input type="url" id="discord_webhook_url" name="discord_webhook_url" value="{html_escape(discord_webhook_url)}" placeholder="https://discord.com/api/webhooks/..."></div><div class="form-group"><label for="lan_admin_username">LAN Admin Username:</label><input id="lan_admin_username" name="lan_admin_username" value="{html_escape(lan_admin_username)}"></div><div class="form-group"><label for="lan_admin_password">LAN Admin Password:</label><input type="password" id="lan_admin_password" name="lan_admin_password" placeholder="Leave blank to keep current password"></div></fieldset>'.encode('utf-8'))

    # Send footer with JavaScript
    _send_file_chunks(cl, '/html/footer.bin')

def _read_http_request(cl, max_request_size=4096):
    cl_file = cl.makefile("rwb", 0)
    request_lines = []
    request_size = 0

    while True:
        try:
            line = cl_file.readline()
            if not line or line == b"\r\n":
                break
            request_size += len(line)
            if request_size > max_request_size:
                print("Warning: Request too large, rejecting.")
                cl.send(b"HTTP/1.0 413 Request Entity Too Large\r\n\r\n")
                return None
            request_lines.append(line.decode())
        except OSError:
            break

    return "".join(request_lines)

def _get_query_params(request):
    if "?" not in request:
        return {}
    query_start = request.find("?") + 1
    query_end = request.find(" ", query_start)
    query_string = request[query_start:query_end]
    return parse_query_string(query_string)

def _expected_basic_auth_header():
    username = config_manager.get_global("lan_admin.username", "admin") or "admin"
    password = config_manager.get_global("lan_admin.password", "admin") or "admin"
    token = ubinascii.b2a_base64((username + ":" + password).encode()).decode().strip()
    return "Authorization: Basic " + token

def _send_auth_required(cl):
    cl.send(b'HTTP/1.0 401 Unauthorized\r\nWWW-Authenticate: Basic realm="Pi Clock LAN Admin"\r\n\r\nUnauthorized')

def _is_lan_authorized(request):
    return _expected_basic_auth_header() in request

def _get_page_networks(require_auth=False):
    if not require_auth:
        return scan_networks()

    active_profile = config_manager.get_active_profile()
    ssid = active_profile.get("wifi", {}).get("ssid", "") if active_profile else ""
    return [{"ssid": ssid, "rssi": 0}] if ssid else []


def _send_json(cl, value):
    cl.send(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
    cl.send(ujson.dumps(value).encode())


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

    profile_data = {
        "name": new_name,
        "wifi": {
            "ssid": params.get("ssid", ""),
            "password": wifi_password
        },
        "weather_location": params.get("location", "Taipei"),
        "user": {
            "birthday": params.get("birthday", "0101"),
            "light_threshold": int(params.get("light_threshold", "56000")),
            "image_interval_min": int(params.get("image_interval_min", "2")),
            "timezone_offset": int(params.get("timezone_offset", "8"))
        },
        "chime": {
            "enabled": params.get("chime_enabled") == "true",
            "interval": params.get("chime_interval", "hourly"),
            "pitch": int(params.get("chime_pitch", "880")),
            "volume": int(params.get("chime_volume", "80"))
        }
    }

    config_manager.update_profile(original_name, profile_data)

    api_key_input = params.get("api_key", "")
    if api_key_input and not api_key_input.startswith("å·²è¨­å®š") and "..." not in api_key_input:
        config_manager.set_global("weather_api_key", api_key_input)

    config_manager.set_global("ap_mode.ssid", params.get("ap_mode_ssid", "Pi_Clock_AP"))

    ap_password_input = params.get("ap_mode_password", "")
    if ap_password_input:
        config_manager.set_global("ap_mode.password", ap_password_input)

    config_manager.set_global("discord_webhook_url", params.get("discord_webhook_url", ""))
    config_manager.set_global("lan_admin.username", params.get("lan_admin_username", "admin") or "admin")

    lan_admin_password = params.get("lan_admin_password", "")
    if lan_admin_password:
        config_manager.set_global("lan_admin.password", lan_admin_password)

    config_manager.set_active_profile(new_name)
    config_manager.set_last_connected_profile(new_name)

def handle_config_request(cl, request, require_auth=False):
    if not request:
        cl.close()
        return

    print(f"Request: {request[:100] + '...' if len(request) > 100 else request}")

    if require_auth and not _is_lan_authorized(request):
        _send_auth_required(cl)
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
            send_html_page(cl, _get_page_networks(require_auth), profile)
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
        if not new_name:
            cl.send(b"HTTP/1.0 400 Bad Request\r\n\r\nInvalid profile name")
            cl.close()
            return

        base_profile = config_manager.get_active_profile()
        new_profile = {
            "name": new_name,
            "wifi": {"ssid": "", "password": ""},
            "weather_location": base_profile.get("weather_location", "Taipei") if base_profile else "Taipei",
            "user": base_profile.get("user", {
                "birthday": "0101",
                "light_threshold": 56000,
                "image_interval_min": 2,
                "timezone_offset": 8
            }) if base_profile else {
                "birthday": "0101",
                "light_threshold": 56000,
                "image_interval_min": 2,
                "timezone_offset": 8
            },
            "chime": base_profile.get("chime", {
                "enabled": True,
                "interval": "hourly",
                "pitch": 880,
                "volume": 80
            }) if base_profile else {
                "enabled": True,
                "interval": "hourly",
                "pitch": 880,
                "volume": 80
            }
        }

        try:
            config_manager.add_profile(new_profile)
            cl.send(("HTTP/1.0 302 Found\r\nLocation: /edit_profile?name=" + new_name + "\r\n\r\n").encode())
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
        send_html_page(cl, _get_page_networks(require_auth))
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
            cl.settimeout(5.0)
            request = _read_http_request(cl)
            handle_config_request(cl, request, require_auth=True)
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
    """Runs a simple web server to handle configuration requests with multi-profile support."""
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)

    print(f"Web server listening on {addr}")

    # Initialize hardware manager for unified button handling
    hardware = HardwareManager()

    def reset_callback(button_index):
        """Callback function for button long press reset."""
        print(f"Button {button_index+1} long pressed in AP mode. Resetting WiFi and AP settings...")
        s.close()
        reset_wifi_and_reboot()

    start_time = time.time()
    last_activity_time = time.time()
    timeout_duration = 600  # 10 minutes base timeout
    activity_extension = 300  # 5 minutes extension per activity

    while True:
        try:
            # Check for button long press
            if hardware.handle_button_long_press(reset_callback):
                return

            # Check timeout
            current_time = time.time()
            time_since_start = current_time - start_time
            time_since_activity = current_time - last_activity_time

            effective_timeout = timeout_duration
            if time_since_activity < activity_extension:
                effective_timeout = timeout_duration + activity_extension

            if time_since_start > effective_timeout:
                print(f"Info: AP mode timeout ({effective_timeout/60:.1f} minutes). Using last connected profile and restarting.")
                s.close()
                # Set active profile to last connected if available
                last_profile = config_manager.get_last_connected_profile_name()
                if last_profile:
                    try:
                        config_manager.set_active_profile(last_profile)
                        print(f"Info: Switched to last connected profile: {last_profile}")
                    except:
                        pass
                machine.reset()

            s.settimeout(1.0)

            try:
                cl, addr = s.accept()
                last_activity_time = time.time()
                print(f"Info: Client connected from {addr}.")
            except OSError:
                continue

            cl.settimeout(10.0)

            try:
                cl_file = cl.makefile("rwb", 0)
                request = ""
                max_request_size = 4096  # 4KB limit for longer global setting URLs

                while True:
                    try:
                        line = cl_file.readline()
                        if not line or line == b"\r\n":
                            break
                        # Check request size limit
                        if len(request) + len(line) > max_request_size:
                            print("Warning: Request too large, rejecting.")
                            cl.send(b"HTTP/1.0 413 Request Entity Too Large\r\n\r\n")
                            cl.close()
                            break
                        request += line.decode()
                    except OSError:
                        break

                print(f"Request: {request[:100] + '...' if len(request) > 100 else request}")

                # Handle favicon
                if "GET /favicon.ico" in request:
                    cl.send(b"HTTP/1.0 404 Not Found\r\n\r\n")
                    cl.close()
                    continue

                # Handle ADC value request
                if "GET /adc" in request:
                    adc_value = machine.ADC(machine.Pin(26)).read_u16()
                    response = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"adc\": " + str(adc_value) + "}"
                    cl.send(response.encode())
                    cl.close()
                    continue

                # Handle chime test
                if "GET /test_chime" in request:
                    last_activity_time = time.time()
                    query_start = request.find("?") + 1
                    query_end = request.find(" ", query_start)
                    query_string = request[query_start:query_end]
                    params = parse_query_string(query_string)

                    # Phase 3: CSRF 防護
                    if not verify_csrf_token(params):
                        print("Error: CSRF token validation failed for test_chime")
                        cl.send(b"HTTP/1.1 403 Forbidden\r\n\r\nCSRF token invalid")
                        cl.close()
                        continue

                    pitch = int(params.get("pitch", "880"))
                    volume = int(params.get("volume", "80"))

                    try:
                        chime_obj = Chime()
                        chime_obj.do_chime(pitch=pitch, volume=volume)
                        chime_obj.deinit()
                        cl.send(b"HTTP/1.0 200 OK\r\n\r\nOK")
                    except Exception as e:
                        print(f"Error: Chime test failed. {e}")
                        cl.send(b"HTTP/1.0 500 Internal Server Error\r\n\r\nError")
                    cl.close()
                    continue

                # Handle edit profile request
                if "GET /edit_profile?" in request:
                    query_start = request.find("?") + 1
                    query_end = request.find(" ", query_start)
                    query_string = request[query_start:query_end]
                    params = parse_query_string(query_string)
                    profile_name = params.get("name", "")

                    profile = config_manager.get_profile(profile_name)
                    if profile:
                        networks = scan_networks()
                        send_html_page(cl, networks, profile)
                    else:
                        cl.send(b"HTTP/1.0 404 Not Found\r\n\r\nProfile not found")
                    cl.close()
                    continue

                # Handle new profile request
                if "GET /new_profile?" in request:
                    query_start = request.find("?") + 1
                    query_end = request.find(" ", query_start)
                    query_string = request[query_start:query_end]
                    params = parse_query_string(query_string)

                    # Phase 3: CSRF 防護（Gemini 審查建議補強）
                    if not verify_csrf_token(params):
                        print("Error: CSRF token validation failed for new_profile")
                        cl.send(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\n\r\n")
                        cl.send(b"<h1>403 Forbidden</h1><p>CSRF token invalid.</p>")
                        cl.close()
                        continue

                    new_name = params.get("name", "")

                    if new_name:
                        # Create new profile based on last connected or active profile
                        base_profile = config_manager.get_active_profile()
                        new_profile = {
                            "name": new_name,
                            "wifi": {"ssid": "", "password": ""},
                            "weather_location": base_profile.get("weather_location", "Taipei") if base_profile else "Taipei",
                            "user": base_profile.get("user", {
                                "birthday": "0101",
                                "light_threshold": 56000,
                                "image_interval_min": 2,
                                "timezone_offset": 8
                            }) if base_profile else {
                                "birthday": "0101",
                                "light_threshold": 56000,
                                "image_interval_min": 2,
                                "timezone_offset": 8
                            },
                            "chime": base_profile.get("chime", {
                                "enabled": True,
                                "interval": "hourly",
                                "pitch": 880,
                                "volume": 80
                            }) if base_profile else {
                                "enabled": True,
                                "interval": "hourly",
                                "pitch": 880,
                                "volume": 80
                            }
                        }

                        try:
                            config_manager.add_profile(new_profile)
                            # Redirect to edit this new profile
                            redirect = "HTTP/1.0 302 Found\r\nLocation: /edit_profile?name=" + new_name + "\r\n\r\n"
                            cl.send(redirect.encode())
                        except ValueError as e:
                            cl.send(b"HTTP/1.0 400 Bad Request\r\n\r\nProfile name already exists")
                    else:
                        cl.send(b"HTTP/1.0 400 Bad Request\r\n\r\nInvalid profile name")
                    cl.close()
                    continue

                # Handle delete profile request
                if "GET /delete_profile?" in request:
                    query_start = request.find("?") + 1
                    query_end = request.find(" ", query_start)
                    query_string = request[query_start:query_end]
                    params = parse_query_string(query_string)

                    # Phase 3: CSRF 防護
                    if not verify_csrf_token(params):
                        print("Error: CSRF token validation failed for delete_profile")
                        cl.send(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\n\r\n")
                        cl.send(b"<h1>403 Forbidden</h1><p>CSRF token invalid.</p>")
                        cl.close()
                        continue

                    profile_name = params.get("name", "")

                    try:
                        config_manager.delete_profile(profile_name)
                        # Redirect to home
                        redirect = "HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n"
                        cl.send(redirect.encode())
                    except ValueError as e:
                        cl.send(("HTTP/1.0 400 Bad Request\r\n\r\n" + str(e)).encode())
                    cl.close()
                    continue

                # Handle factory reset request
                if "GET /factory_reset" in request:
                    last_activity_time = time.time()
                    print("WARNING: Factory reset requested!")

                    # Phase 3: CSRF 防護 (factory reset 需要 token)
                    # 解析 query string (如果有)
                    params = {}
                    if "?" in request:
                        query_start = request.find("?") + 1
                        query_end = request.find(" ", query_start)
                        query_string = request[query_start:query_end]
                        params = parse_query_string(query_string)

                    if not verify_csrf_token(params):
                        print("Error: CSRF token validation failed for factory_reset")
                        cl.send(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\n\r\n")
                        cl.send(b"<h1>403 Forbidden</h1><p>CSRF token invalid. Cannot perform factory reset.</p>")
                        cl.close()
                        continue

                    try:
                        # Perform factory reset
                        factory_reset()

                        # Send success page (compressed constant)
                        _send_file_chunks(cl, '/html/reset.bin')
                        cl.close()

                        # Restart system
                        update_display_Restart()
                        print("Factory reset complete. Restarting in 5 seconds...")
                        time.sleep(5)
                        s.close()
                        machine.reset()

                    except Exception as e:
                        print(f"Error: Factory reset failed. {e}")
                        # Send error page using chunked sending
                        cl.send(HTML_RESET_ERROR_PREFIX)
                        cl.send(str(e).encode('utf-8'))
                        cl.send(HTML_RESET_ERROR_SUFFIX)
                        cl.close()
                        continue

                # Handle save profile request
                if "GET /save_profile?" in request:
                    last_activity_time = time.time()
                    print("Info: Saving profile...")

                    query_start = request.find("?") + 1
                    query_end = request.find(" ", query_start)
                    query_string = request[query_start:query_end]
                    params = parse_query_string(query_string)

                    # Phase 3: CSRF 防護
                    if not verify_csrf_token(params):
                        print("Error: CSRF token validation failed for save_profile")
                        cl.send(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\n\r\n")
                        cl.send(b"<h1>403 Forbidden</h1><p>CSRF token invalid. Please reload the page.</p>")
                        cl.close()
                        continue

                    try:
                        original_name = params.get("original_profile_name", "")
                        new_name = params.get("profile_name", "")

                        # 取得原始設定檔資料（用於保留密碼）
                        original_profile = config_manager.get_profile(original_name)

                        # Phase 2 安全改進：空密碼不覆蓋已儲存密碼
                        wifi_password = params.get("password", "")
                        if not wifi_password and original_profile:
                            # 保留原密碼
                            wifi_password = original_profile.get("wifi", {}).get("password", "")

                        # Build profile data
                        profile_data = {
                            "name": new_name,
                            "wifi": {
                                "ssid": params.get("ssid", ""),
                                "password": wifi_password
                            },
                            "weather_location": params.get("location", "Taipei"),
                            "user": {
                                "birthday": params.get("birthday", "0101"),
                                "light_threshold": int(params.get("light_threshold", "56000")),
                                "image_interval_min": int(params.get("image_interval_min", "2")),
                                "timezone_offset": int(params.get("timezone_offset", "8"))
                            },
                            "chime": {
                                "enabled": params.get("chime_enabled") == "true",
                                "interval": params.get("chime_interval", "hourly"),
                                "pitch": int(params.get("chime_pitch", "880")),
                                "volume": int(params.get("chime_volume", "80"))
                            }
                        }

                        # Update profile
                        config_manager.update_profile(original_name, profile_data)

                        # Phase 2 安全改進：僅在有值時更新全局設定
                        api_key_input = params.get("api_key", "")
                        # 忽略遮罩值和空值
                        if api_key_input and not api_key_input.startswith("已設定") and "..." not in api_key_input:
                            config_manager.set_global("weather_api_key", api_key_input)

                        # AP SSID 總是更新
                        config_manager.set_global("ap_mode.ssid", params.get("ap_mode_ssid", "Pi_Clock_AP"))

                        # AP 密碼僅在有輸入時更新
                        ap_password_input = params.get("ap_mode_password", "")
                        if ap_password_input:
                            config_manager.set_global("ap_mode.password", ap_password_input)

                        config_manager.set_global("discord_webhook_url", params.get("discord_webhook_url", ""))
                        lan_admin_username = params.get("lan_admin_username", "admin") or "admin"
                        config_manager.set_global("lan_admin.username", lan_admin_username)
                        lan_admin_password = params.get("lan_admin_password", "")
                        if lan_admin_password:
                            config_manager.set_global("lan_admin.password", lan_admin_password)

                        # Set as active profile and update last connected
                        # This ensures the device will prioritize this profile on next restart
                        config_manager.set_active_profile(new_name)
                        config_manager.set_last_connected_profile(new_name)

                        print(f"Success: Profile '{new_name}' saved and activated.")

                        # Send success page (compressed constant)
                        _send_file_chunks(cl, '/html/success.bin')
                        cl.close()

                        update_display_Restart()
                        print("Info: Restarting in 5 seconds...")
                        time.sleep(5)
                        s.close()
                        machine.reset()

                    except Exception as e:
                        print(f"Error: Failed to save profile. {e}")
                        # Send error page using chunked sending
                        cl.send(HTML_ERROR_PAGE_PREFIX)
                        cl.send(str(e).encode('utf-8'))
                        cl.send(HTML_ERROR_PAGE_SUFFIX)
                        cl.close()
                        continue

                # Default: show main page
                try:
                    networks = scan_networks()
                    send_html_page(cl, networks)
                    cl.close()
                except Exception as e:
                    print(f"Error: Failed to send page. {e}")
                    try:
                        cl.close()
                    except:
                        pass

            except Exception as e:
                print(f"Error: Client handling error. {e}")
                try:
                    cl.close()
                except:
                    pass
                continue

        except Exception as e:
            print(f"Error: Server error. {e}")
            continue
        finally:
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
