import gc
import network
import urequests

from config_manager import config_manager

JSON_HEADERS = {"Content-Type": "application/json"}
FULL_DAY_SECONDS = 24 * 60 * 60
PRESENCE_BAR_WIDTH = 20

def _discord_payload(message):
    message = message.replace("\\", "\\\\")
    message = message.replace('"', '\\"')
    message = message.replace("\r", "\\r").replace("\n", "\\n")
    return ('{"content":"%s"}' % message).encode("utf-8")


def _post_discord_webhook(webhook_url, payload):
    response = None
    try:
        gc.collect()
        response = urequests.post(webhook_url, data=payload, headers=JSON_HEADERS, timeout=10)
        detail = ""
        if response.status_code not in (200, 204):
            try:
                raw = getattr(response, "raw", None)
                if raw:
                    data = raw.read(160)
                    if data:
                        detail = data.decode() if hasattr(data, "decode") else str(data)
            except Exception:
                detail = ""
            if detail and len(detail) > 120:
                detail = detail[:120] + "..."
        return response.status_code, detail
    finally:
        if response:
            try:
                response.close()
            except:
                pass
        response = None
        gc.collect()


def _format_duration(seconds):
    seconds = max(0, int(seconds))
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
    return away_percent, chr(0x25A1) * away_units + chr(0x25A0) * desk_units, desk_percent


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
        message = "Pi Paper Clock connected: {}".format(ip_address)
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
        status_code, _ = _post_discord_webhook(webhook_url, payload)
        if status_code in (200, 204):
            print("Success: Discord presence session sent.")
            return True
        print("Error: Presence session failed. Status code: {}".format(status_code))
    except MemoryError:
        print("Error: Memory allocation failed during presence session.")
    except Exception as e:
        print("Error: Presence session failed. Details: {}".format(e))
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

    date = parts[0]
    total_seconds = int(parts[1])
    transitions = int(parts[2])
    longest_seconds = int(parts[3]) if len(parts) >= 4 else total_seconds
    session_count = int(parts[4]) if len(parts) >= 5 else (transitions + 1) // 2

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
    except Exception as e:
        print("Error: Presence summary failed. Details: {}".format(e))
    finally:
        payload = None
        gc.collect()

    return False
