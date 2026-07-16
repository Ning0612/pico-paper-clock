import gc
import network
import socket
import ssl

from config_manager import config_manager

FULL_DAY_SECONDS = 24 * 60 * 60
PRESENCE_BAR_WIDTH = 10
DISCORD_GC_THRESHOLD = 4096


def _log_heap(label):
    mem_free = getattr(gc, "mem_free", None)
    if not callable(mem_free):
        return
    try:
        free_bytes = mem_free()
        mem_alloc = getattr(gc, "mem_alloc", None)
        if callable(mem_alloc):
            print("Memory {}: free={} bytes, allocated={} bytes.".format(
                label, free_bytes, mem_alloc()
            ))
        else:
            print("Memory {}: free={} bytes.".format(label, free_bytes))
    except Exception:
        pass


def _write_all(sock, data):
    offset = 0
    data_length = len(data)
    view = memoryview(data)
    try:
        while offset < data_length:
            written = sock.write(view[offset:])
            if not written:
                raise OSError("Discord socket closed during write.")
            offset += written
    finally:
        del view

def _json_string(value):
    """Returns one JSON string encoded as a UTF-8 bytearray."""
    if not isinstance(value, str):
        value = str(value)
    buf = bytearray(b'"')
    for byte in value.encode("utf-8"):
        if byte == 0x22:
            buf.extend(b'\\"')
        elif byte == 0x5C:
            buf.extend(b'\\\\')
        elif byte == 0x08:
            buf.extend(b'\\b')
        elif byte == 0x0C:
            buf.extend(b'\\f')
        elif byte == 0x0A:
            buf.extend(b'\\n')
        elif byte == 0x0D:
            buf.extend(b'\\r')
        elif byte == 0x09:
            buf.extend(b'\\t')
        elif byte < 0x20:
            buf.extend("\\u00{:02x}".format(byte).encode())
        else:
            buf.append(byte)
    buf.extend(b'"')
    return buf


def _discord_payload(message):
    payload = bytearray(b'{"content":')
    payload.extend(_json_string(message))
    payload.append(ord('}'))
    return payload


def _presence_progress(total_seconds):
    total_seconds = max(0, int(total_seconds))
    percent = min(999, int(total_seconds * 100 / FULL_DAY_SECONDS))
    filled = min(PRESENCE_BAR_WIDTH, percent // 10)
    if percent >= 100:
        block = "🟩"
        color = 3066993
    elif percent >= 80:
        block = "🟦"
        color = 3447003
    elif percent >= 50:
        block = "🟨"
        color = 15132194
    else:
        block = "🟥"
        color = 15158332
    return block * filled + "⬜" * (PRESENCE_BAR_WIDTH - filled), percent, color


def _presence_summary_embed_payload(date, total_seconds, longest_seconds, session_count):
    progress, percent, color = _presence_progress(total_seconds)
    title = "📊 在席日報 · {}".format(_display_date(date))
    description = "{}  {}%".format(progress, percent)
    fields = (
        ("書桌前", _format_duration(total_seconds)),
        ("最長一次", _format_duration(longest_seconds)),
        ("次數", str(session_count)),
    )
    buf = bytearray(b'{"embeds":[{"title":')
    buf.extend(_json_string(title))
    buf.extend(b',"description":')
    buf.extend(_json_string(description))
    buf.extend(b',"fields":[{')
    for index, (name, value) in enumerate(fields):
        if index:
            buf.extend(b'},{')
        buf.extend(b'"name":')
        buf.extend(_json_string(name))
        buf.extend(b',"value":')
        buf.extend(_json_string(value))
        buf.extend(b',"inline":true')
    buf.extend(b'}],"color":')
    buf.extend(str(color).encode())
    buf.extend(b'}]}')
    return buf


def _post_discord_webhook(webhook_url, payload):
    raw_socket = None
    tls_socket = None
    old_threshold = None
    try:
        threshold = getattr(gc, "threshold", None)
        if threshold:
            try:
                old_threshold = threshold()
            except TypeError:
                pass
            threshold(DISCORD_GC_THRESHOLD)
        gc.collect()
        _log_heap("before Discord socket")
        parts = webhook_url.split("/", 3)
        if len(parts) != 4 or parts[0] != "https:":
            raise ValueError("Discord webhook URL must use https.")
        host = parts[2]
        path = "/" + parts[3]
        addr_info = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
        address = addr_info[-1]

        raw_socket = socket.socket(addr_info[0], addr_info[1], addr_info[2])
        del addr_info
        raw_socket.settimeout(10)
        raw_socket.connect(address)
        del address
        del parts
        gc.collect()
        _log_heap("before Discord TLS")
        tls_socket = ssl.wrap_socket(raw_socket, server_hostname=host)
        raw_socket = None

        headers = (
            "POST {} HTTP/1.1\r\n"
            "Host: {}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n\r\n"
        ).format(path, host, len(payload)).encode()
        _write_all(tls_socket, headers)
        _write_all(tls_socket, payload)

        status_line = tls_socket.readline(64)
        status_parts = status_line.split()
        if len(status_parts) < 2:
            raise OSError("Invalid Discord response.")
        status_code = int(status_parts[1])
        detail = ""
        if status_code not in (200, 204):
            try:
                data = tls_socket.read(160)
                if data:
                    detail = data.decode() if hasattr(data, "decode") else str(data)
            except Exception:
                detail = ""
            if detail and len(detail) > 120:
                detail = detail[:120] + "..."
        return status_code, detail
    finally:
        if tls_socket:
            try:
                tls_socket.close()
            except:
                pass
        if raw_socket:
            try:
                raw_socket.close()
            except:
                pass
        threshold = getattr(gc, "threshold", None)
        if threshold and old_threshold is not None:
            threshold(old_threshold)
        tls_socket = None
        raw_socket = None
        gc.collect()


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "{}s".format(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return "{}h {}m".format(hours, minutes)
    return "{}m".format(minutes)


def _display_date(date):
    return "{}-{}-{}".format(date[0:4], date[4:6], date[6:8])


def _display_time(time_value):
    return "{}:{}".format(time_value[0:2], time_value[2:4])


def _presence_bar(total_seconds):
    total_seconds = max(0, int(total_seconds))
    desk_percent = min(999, int(total_seconds * 100 // FULL_DAY_SECONDS))
    away_percent = max(0, 100 - desk_percent)
    desk_units = min(PRESENCE_BAR_WIDTH, int(total_seconds * PRESENCE_BAR_WIDTH // FULL_DAY_SECONDS))
    away_units = PRESENCE_BAR_WIDTH - desk_units
    return away_percent, "[" + chr(0x2591) * away_units + chr(0x2588) * desk_units + "]", desk_percent


def _presence_summary_message(date, total_seconds, longest_seconds, session_count):
    _, progress, percent = _presence_bar(total_seconds)
    return (
        "📊 在席日報 · {}\n"
        "{}  {}%\n"
        "書桌前 {} / 最長一次 {} / 次數 {}"
    ).format(
        _display_date(date),
        progress,
        percent,
        _format_duration(total_seconds),
        _format_duration(longest_seconds),
        session_count
    )


def _presence_session_message(start_date, start_time, end_date, end_time, duration_seconds):
    start_text = _display_time(start_time)
    end_text = _display_time(end_time)
    return "📖 書桌前時段結束\n{} → {}（{}）".format(
        start_text, end_text, _format_duration(duration_seconds)
    )


def send_lan_ip(ip_address):
    """Sends the LAN configuration URL to Discord when a webhook is configured."""
    webhook_url = config_manager.get_global("discord_webhook_url", "")
    if not webhook_url:
        print("Info: Discord webhook is not configured. Skipping LAN IP notification.")
        return False

    if not network.WLAN(network.STA_IF).isconnected():
        print("Warning: No internet connection. Skipping Discord notification.")
        return False

    status_code = -1
    try:
        message = "✅ Pi Paper Clock 已上線\nWebUI: http://{}".format(ip_address)
        payload = _discord_payload(message)
        status_code, detail = _post_discord_webhook(webhook_url, payload)
        if status_code in (200, 204):
            print("Success: Discord LAN IP notification sent.")
            return True
        if detail:
            print("Error: Discord notification failed. Status code: {}. Response: {}".format(status_code, detail))
        else:
            print("Error: Discord notification failed. Status code: {}".format(status_code))
    except MemoryError:
        print("Error: Memory allocation failed during Discord notification.")
        return None
    except Exception as e:
        print("Error: Discord notification failed. Details: {}".format(e))
        if "ENOMEM" in str(e):
            return None
    finally:
        payload = None
        gc.collect()

    return False


def send_presence_session(start_date, start_time, end_date, end_time, duration_seconds):
    """Sends a completed desk presence session to Discord."""
    webhook_url = config_manager.get_global("discord_webhook_url", "")
    if not webhook_url:
        print("Info: Discord webhook is not configured. Skipping presence session.")
        return False

    if not network.WLAN(network.STA_IF).isconnected():
        print("Warning: No internet connection. Skipping presence session.")
        return False

    status_code = -1
    try:
        message = _presence_session_message(
            start_date, start_time, end_date, end_time, duration_seconds
        )
        payload = _discord_payload(message)
        status_code, detail = _post_discord_webhook(webhook_url, payload)
        if status_code in (200, 204):
            print("Success: Discord presence session sent.")
            return True
        if detail:
            print("Error: Presence session failed. Status code: {}. Response: {}".format(status_code, detail))
        else:
            print("Error: Presence session failed. Status code: {}".format(status_code))
    except MemoryError:
        print("Error: Memory allocation failed during presence session.")
        return None
    except Exception as e:
        print("Error: Presence session failed. Details: {}".format(e))
        if "ENOMEM" in str(e):
            return None
    finally:
        payload = None
        gc.collect()

    return False


def send_presence_summary(summary_line):
    """Sends a daily desk presence summary to Discord.

    summary_line format:
    YYYYMMDD,total_seconds,transition_count,longest_session_seconds,session_count
    """
    webhook_url = config_manager.get_global("discord_webhook_url", "")
    if not webhook_url:
        print("Info: Discord webhook is not configured. Skipping presence summary.")
        return False

    if not network.WLAN(network.STA_IF).isconnected():
        print("Warning: No internet connection. Skipping presence summary.")
        return False

    parts = summary_line.split(",")
    if len(parts) < 3:
        print("Warning: Invalid presence summary format.")
        return False

    try:
        date = parts[0]
        total_seconds = int(parts[1])
        transitions = int(parts[2])
        longest_seconds = int(parts[3]) if len(parts) >= 4 else total_seconds
        session_count = int(parts[4]) if len(parts) >= 5 else (transitions + 1) // 2
    except (ValueError, IndexError):
        print("Warning: Invalid presence summary data.")
        return False

    status_code = -1
    try:
        payload = _presence_summary_embed_payload(
            date, total_seconds, longest_seconds, session_count
        )
        status_code, _ = _post_discord_webhook(webhook_url, payload)
        if status_code in (200, 204):
            print("Success: Discord presence summary sent.")
            return True
        print("Error: Presence summary failed. Status code: {}".format(status_code))
    except MemoryError:
        print("Warning: Memory allocation failed during presence summary; using L1 fallback.")
        try:
            fallback = _discord_payload(_presence_summary_message(
                date, total_seconds, longest_seconds, session_count
            ))
            status_code, _ = _post_discord_webhook(webhook_url, fallback)
            return status_code in (200, 204)
        except MemoryError:
            print("Error: Memory allocation failed during presence summary fallback.")
            return None
        except Exception as e:
            print("Error: Presence summary fallback failed. Details: {}".format(e))
            return False
    except Exception as e:
        print("Error: Presence summary failed. Details: {}".format(e))
        if "ENOMEM" in str(e):
            return None
    finally:
        payload = None
        gc.collect()

    return False
