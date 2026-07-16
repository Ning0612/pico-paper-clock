# main.py
import time
import gc
from wifi_manager import wifi_manager, create_lan_config_server
from netutils import sync_time
from discord_notifier import send_lan_ip


# Keep the first TLS allocation ahead of the display, sensor, weather, and
# controller imports.  Those modules are intentionally loaded below only
# after the startup webhook has had its low-memory window.
_startup_wlan = wifi_manager()
_startup_lan_ip = None
_startup_network_connected = bool(_startup_wlan and _startup_wlan.isconnected())
_startup_discord_sent = False
if _startup_network_connected:
    _startup_lan_ip = _startup_wlan.ifconfig()[0]
    _startup_wlan = None
    gc.collect()
    sync_time()
    _startup_discord_sent = send_lan_ip(_startup_lan_ip) is True
    from discord_notifier import send_presence_session, send_presence_summary
    from presence_manager import PresenceManager

    startup_presence = PresenceManager(
        discord_sender=send_presence_summary,
        session_sender=send_presence_session
    )
    flushed = startup_presence.flush_startup_discord()
    if flushed:
        print("Info: Flushed {} pending Discord notification(s) before app init.".format(flushed))
    startup_presence = None
    gc.collect()
_startup_wlan = None


def main():
    """Main function to initialize and run the Pico Clock Weather Display application."""
    from display_manager import update_page_loading
    from app_state import AppState
    from hardware_manager import HardwareManager
    from app_controller import AppController
    from image_manager import image_store

    recovered = image_store.recover_partial_uploads()

    if recovered:
        print("Recovered {} interrupted image transaction(s).".format(recovered))

    # Initial display and hardware setup follows the memory-sensitive webhook.
    update_page_loading(False)
    app_state = AppState()
    hardware = HardwareManager()

    controller = AppController(app_state, hardware, None, _startup_lan_ip)
    controller.startup_discord_sent = _startup_discord_sent

    if _startup_network_connected:
        controller.lan_server = create_lan_config_server()

    while True:
        controller.run_main_loop()
        time.sleep(1)


if __name__ == "__main__":
    main()
