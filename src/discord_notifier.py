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
