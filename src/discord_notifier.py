import gc
import network
import socket
import ssl

from config_manager import config_manager

FULL_DAY_SECONDS = 24 * 60 * 60
PRESENCE_BAR_WIDTH = 15
DISCORD_GC_THRESHOLD = 4096


def _write_all(sock, data):
    offset = 0
    data_length = len(data)
    while offset < data_length:
        written = sock.write(data[offset:])
        if not written:
            raise OSError("Discord socket closed during write.")
        offset += written

def _discord_payload(message):
    buf = bytearray(b'{"content":"')
    for c in message:
        o = ord(c)
        if c == '"':
            buf.extend(b'\\"')
        elif c == '\\':
            buf.extend(b'\\\\')
        elif c == '\n':
            buf.extend(b'\\n')
        elif c == '\r':
            buf.extend(b'\\r')
        elif c == '\t':
            buf.extend(b'\\t')
        elif 0x20 <= o <= 0x7E:
            buf.append(o)
        else:
            buf.extend('\\u{:04x}'.format(o).encode())
    buf.extend(b'"}')
    return bytes(buf)


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
        parts = webhook_url.split("/", 3)
        if len(parts) != 4 or parts[0] != "https:":
            raise ValueError("Discord webhook URL must use https.")
        host = parts[2]
        path = "/" + parts[3]
        addr_info = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
        address = addr_info[-1]

        raw_socket = socket.socket(addr_info[0], addr_info[1], addr_info[2])
        raw_socket.settimeout(10)
        raw_socket.connect(address)
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
    total_seconds = max(0, min(int(total_seconds), FULL_DAY_SECONDS))
    desk_percent = int((total_seconds * 100 + FULL_DAY_SECONDS // 2) // FULL_DAY_SECONDS)
    away_percent = 100 - desk_percent
    desk_units = int((total_seconds * PRESENCE_BAR_WIDTH + FULL_DAY_SECONDS // 2) // FULL_DAY_SECONDS)
    away_units = PRESENCE_BAR_WIDTH - desk_units
    return away_percent, "[" + chr(0x2591) * away_units + chr(0x2588) * desk_units + "]", desk_percent


def _presence_summary_message(date, total_seconds, longest_seconds, session_count):
    display_date = _display_date(date)
    away_percent, bar, desk_percent = _presence_bar(total_seconds)
    return (
        "{}\n"
        "\u96e2\u958b {}% {} \u66f8\u684c\u524d {}%\n"
        "\u66f8\u684c\u524d {} / \u6700\u9577\u4e00\u6b21 {} / \u6b21\u6578 {}"
    ).format(
        display_date,
        away_percent,
        bar,
        desk_percent,
        _format_duration(total_seconds),
        _format_duration(longest_seconds),
        session_count
    )


def _presence_session_message(start_date, start_time, end_date, end_time, duration_seconds):
    start_text = "{} {}".format(_display_date(start_date), _display_time(start_time))
    if start_date == end_date:
        end_text = _display_time(end_time)
    else:
        end_text = "{} {}".format(_display_date(end_date), _display_time(end_time))
    return "{} ~ {}\n\u7e3d\u5171\u6301\u7e8c {}".format(
        start_text,
        end_text,
        _format_duration(duration_seconds)
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
        message = "Pico Paper Clock connected: http://{}".format(ip_address)
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
        message = _presence_summary_message(
            date, total_seconds, longest_seconds, session_count
        )
        payload = _discord_payload(message)
        status_code, _ = _post_discord_webhook(webhook_url, payload)
        if status_code in (200, 204):
            print("Success: Discord presence summary sent.")
            return True
        print("Error: Presence summary failed. Status code: {}".format(status_code))
    except MemoryError:
        print("Error: Memory allocation failed during presence summary.")
        return None
    except Exception as e:
        print("Error: Presence summary failed. Details: {}".format(e))
        if "ENOMEM" in str(e):
            return None
    finally:
        payload = None
        gc.collect()

    return False
