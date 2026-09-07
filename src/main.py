# main.py
import time
import gc
from wifi_manager import wifi_manager, create_lan_config_server
from netutils import sync_time, get_local_time
from config_manager import config_manager


# Keep the first TLS allocation ahead of the display, sensor, weather, and
# controller imports.  Those modules are intentionally loaded below only
# after the startup webhook has had its low-memory window.
_startup_wlan = wifi_manager()
_startup_lan_ip = None
_startup_network_connected = bool(_startup_wlan and _startup_wlan.isconnected())
_startup_discord_sent = False
_startup_discord_enabled = bool(config_manager.get_global("discord_webhook_url", ""))
# Consumed before the connected check, not inside it: the note describes *this*
# boot, and one that comes up without a link has no notice to suppress.  Leaving
# it behind would apply it to some later boot that has every reason to announce.
_autoreset_ip = ""
if _startup_discord_enabled:
    from discord_notifier import consume_autoreset_ip
    _autoreset_ip = consume_autoreset_ip()
if _startup_network_connected:
    _startup_lan_ip = _startup_wlan.ifconfig()[0]
    _startup_wlan = None
    gc.collect()
    sync_time()
    # A memory auto-reset buys exactly one usable TLS window, and the online
    # notice would spend it repeating an address the user was already told.
    # Skip it in that case and let the pending backlog below have the window --
    # the whole point of the reboot.  The note is consumed on read, so a power
    # cycle or a changed address still announces normally.
    #
    # "Unchanged" means the same IPv4 string, deliberately: a different network
    # that hands out the same address would also be skipped, but the announced
    # URL still works there, and the note only ever survives from an auto-reset
    # to the boot it caused -- moving the device involves a power cycle, which
    # clears it.
    if _startup_discord_enabled:
        from discord_notifier import send_lan_ip, send_presence_session, send_presence_summary

        if _startup_lan_ip and _autoreset_ip == _startup_lan_ip:
            print("Info: LAN IP unchanged after a memory auto-reset; skipping the online notice.")
            # Marked sent so the controller does not retry it every 30 s either.
            _startup_discord_sent = True
        else:
            _startup_discord_sent = send_lan_ip(_startup_lan_ip) is True

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


# Fetch weather while only the low-dependency startup modules are resident.
# Loading the display, sensor, image catalog and controller first fragments the
# heap enough for the Pico W TLS allocation to fail even when mem_free is large.
_startup_weather_current = None
_startup_weather_forecast = None
_startup_weather_timezone = 8
if _startup_network_connected:
    try:
        from weather import fetch_weather_bundle

        _startup_weather_latitude = config_manager.get("weather.latitude")
        _startup_weather_longitude = config_manager.get("weather.longitude")
        _startup_weather_timezone = config_manager.get("user.timezone_offset", 8)
        startup_weather_bundle = fetch_weather_bundle(
            _startup_weather_latitude,
            _startup_weather_longitude,
            days_limit=5,
            timezone_offset=_startup_weather_timezone,
        )
        if startup_weather_bundle:
            _startup_weather_current, _startup_weather_forecast = startup_weather_bundle
        startup_weather_bundle = None
    except Exception as e:
        print("Warning: Startup weather prefetch failed. Details: {}".format(e))
    finally:
        gc.collect()


def main():
    """Main function to initialize and run the Pico Clock Weather Display application."""
    global _startup_weather_current, _startup_weather_forecast
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
    startup_weather_ms = time.ticks_ms()
    startup_weather_prefetched = bool(_startup_weather_current or _startup_weather_forecast)
    if startup_weather_prefetched:
        # _handle_date_change() treats last_day == -1 as a new day and clears
        # all weather state.  Seed it here so a successful low-memory startup
        # fetch is used by the first display pass instead of being fetched again
        # after the display modules have fragmented the heap.
        app_state.last_day = get_local_time(offset=_startup_weather_timezone * 3600)[2]
    if _startup_weather_current:
        app_state.current_weather = _startup_weather_current
        app_state.current_weather_last_updated = startup_weather_ms
        app_state.current_weather_last_attempted = startup_weather_ms
    if _startup_weather_forecast:
        app_state.weather_forecast = _startup_weather_forecast
        app_state.weather_forecast_last_updated = startup_weather_ms
        app_state.weather_forecast_last_attempted = startup_weather_ms
    _startup_weather_current = None
    _startup_weather_forecast = None
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
