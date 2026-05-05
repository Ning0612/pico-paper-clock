import gc
import network
import ujson
import urequests

from config_manager import config_manager


def send_lan_ip(ip_address):
    """Sends the LAN configuration URL to Discord when a webhook is configured."""
    webhook_url = config_manager.get_global("discord_webhook_url", "")
    if not webhook_url:
        print("Info: Discord webhook is not configured. Skipping LAN IP notification.")
        return False

    if not network.WLAN(network.STA_IF).isconnected():
        print("Warning: No internet connection. Skipping Discord notification.")
        return False

    response = None
    try:
        message = "Pi Paper Clock connected: http://{}/".format(ip_address)
        payload = ujson.dumps({"content": message})
        headers = {"Content-Type": "application/json"}
        response = urequests.post(webhook_url, data=payload, headers=headers, timeout=10)
        if response.status_code in (200, 204):
            print("Success: Discord LAN IP notification sent.")
            return True
        print("Error: Discord notification failed. Status code: {}".format(response.status_code))
    except MemoryError:
        print("Error: Memory allocation failed during Discord notification.")
    except Exception as e:
        print("Error: Discord notification failed. Details: {}".format(e))
    finally:
        if response:
            try:
                response.close()
            except:
                pass
        gc.collect()

    return False


def send_presence_summary(summary_line):
    """Sends a daily desk presence summary to Discord.

    summary_line format: YYYYMMDD,total_seconds,transition_count
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
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    display_date = "{}-{}-{}".format(date[0:4], date[4:6], date[6:8])

    response = None
    try:
        message = "Desk presence for {}: {}h {}m at desk, {} state changes.".format(
            display_date, hours, minutes, transitions
        )
        payload = ujson.dumps({"content": message})
        headers = {"Content-Type": "application/json"}
        response = urequests.post(webhook_url, data=payload, headers=headers, timeout=10)
        if response.status_code in (200, 204):
            print("Success: Discord presence summary sent.")
            return True
        print("Error: Presence summary failed. Status code: {}".format(response.status_code))
    except MemoryError:
        print("Error: Memory allocation failed during presence summary.")
    except Exception as e:
        print("Error: Presence summary failed. Details: {}".format(e))
    finally:
        if response:
            try:
                response.close()
            except:
                pass
        gc.collect()

    return False
