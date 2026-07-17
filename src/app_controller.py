# app_controller.py
import time
import gc
from config_manager import config_manager
from netutils import sync_time, get_local_time
from weather import fetch_current_weather, fetch_weather_forecast
from display_manager import update_page_weather, update_page_time_image, update_page_birthday, update_page_image_preview
from display_utils import release_display_workspace
from image_manager import image_catalog, image_store
from wifi_manager import reset_wifi_and_reboot
from chime import Chime
from discord_notifier import send_lan_ip, send_presence_session, send_presence_summary
from presence_manager import PresenceManager, set_presence_manager

STARTUP_DISCORD_DELAY_MS = 45 * 1000
STARTUP_DISCORD_RETRY_MS = 30 * 1000
CURRENT_WEATHER_REFRESH_MS = 3 * 60 * 1000
CURRENT_WEATHER_RETRY_MS = 10 * 60 * 1000
FORECAST_REFRESH_MS = 30 * 60 * 1000
FORECAST_RETRY_MS = 10 * 60 * 1000
CURRENT_WEATHER_MAX_AGE_MS = 30 * 60 * 1000
FORECAST_MAX_AGE_MS = 4 * 60 * 60 * 1000

class AppController:
    """Manages the application's main logic, including hardware interaction, display updates, and data fetching."""
    __slots__ = (
        "state", "hw", "lan_server", "lan_ip", "startup_discord_sent",
        "startup_discord_disabled", "startup_discord_attempted", "startup_discord_ready_ms",
        "startup_discord_last_attempt_ms", "chime", "location", "api_key",
        "time_zone_offset", "presence",
    )

    def __init__(self, state, hardware, lan_server=None, lan_ip=None):
        """Initializes the AppController.

        Args:
            state: The application's state object.
            hardware: The hardware manager object.
        """
        self.state = state
        self.hw = hardware
        self.lan_server = lan_server
        self.lan_ip = lan_ip
        self.startup_discord_sent = False
        self.startup_discord_disabled = False
        self.startup_discord_attempted = False
        self.startup_discord_ready_ms = time.ticks_add(time.ticks_ms(), STARTUP_DISCORD_DELAY_MS)
        self.startup_discord_last_attempt_ms = time.ticks_add(time.ticks_ms(), -STARTUP_DISCORD_RETRY_MS)
        self.chime = Chime(20) if config_manager.get('chime.enabled') else None
        self.location = config_manager.get("weather.location", "Taipei")
        self.api_key = config_manager.get("weather.api_key")
        self.time_zone_offset = config_manager.get("user.timezone_offset", 8)
        self.presence = PresenceManager(
            discord_sender=send_presence_summary,
            session_sender=send_presence_session
        )
        # Let the display, sensor, and server objects settle before the first
        # pending Discord retry; the startup webhook already used the safe
        # low-memory window.
        self.presence.last_retry_ms = time.ticks_ms()
        set_presence_manager(self.presence)


    def handle_touch(self, touch_state):
        # Handle touch events and switch images
        if touch_state and touch_state[0] == "Touch" and touch_state[1][0] > 168:
            image_catalog.advance()
            print("Image rotation advanced by touch.")

    def handle_buttons(self):
        """Handles button long press detection using unified hardware manager approach."""
        def reset_callback(button_index):
            """Callback function for button long press reset."""
            print(f"Button {button_index+1} long pressed in normal mode. Resetting WiFi and AP settings...")
            reset_wifi_and_reboot()
        
        # Use hardware manager's unified button handling
        self.hw.handle_button_long_press(reset_callback)

    def run_main_loop(self):
        """Executes the main application loop, handling sensor readings, time updates, and display logic."""
        weather_used_network = False
        if self.lan_server:
            self.lan_server.poll()

        preview = image_store.consume_preview()
        if preview:
            update_page_image_preview(preview[0], preview[1], preview[2])
            gc.collect()
            return

        adc_value = self.hw.get_adc_value()
        touch_state = self.hw.get_touch_state()
        t = get_local_time(offset=self.time_zone_offset*3600)

        if touch_state:
            self.state.last_touch_time = time.time()

        self.handle_buttons()

        # HTTPS/TLS needs a sufficiently large contiguous heap block.  Try
        # Discord before weather/display work can fragment the heap.
        discord_used_network = self._send_startup_discord_if_ready()
        if not discord_used_network:
            discord_used_network = self.presence.flush_discord()

        light_threshold = config_manager.get("user.light_threshold", 55000)
        presence_leave_timeout_sec = config_manager.get("user.presence_leave_timeout_sec", 180)
        presence_return_timeout_sec = config_manager.get("user.presence_return_timeout_sec", 10)
        self.presence.update(
            adc_value,
            light_threshold,
            t,
            presence_leave_timeout_sec,
            presence_return_timeout_sec,
        )
        time_since_touch = time.time() - self.state.last_touch_time if self.state.last_touch_time != -1 else 3601

        # If ambient light is below threshold (screen should be off) or time since last touch is less than 1 hour
        if adc_value <= light_threshold or time_since_touch < 3600:         
            # If date has changed
            self._handle_date_change(t[2])

            # If minute has changed, or touch occurred, or first run
            if t[4] != self.state.last_minute or touch_state is not None or self.state.is_first_run:
                self.handle_touch(touch_state)
                self._perform_chime(t)
                self._update_sensor_data()
                weather_used_network = self._update_weather()
                self._update_display(t)

                self.state.is_first_run = False
                self.state.partial_update = not self.state.partial_update
                self.state.last_minute = t[4]
        else:
            # Reset flags when screen is off to ensure full update on wake-up
            self.state.is_first_run = True
            self.state.partial_update = False

        if not weather_used_network and not discord_used_network:
            if not self._send_startup_discord_if_ready():
                if not self._startup_discord_pending():
                    self.presence.flush_discord()
        gc.collect()

    def _handle_date_change(self, current_day):
        """Invalidate daily weather data and permit an immediate refresh."""
        if current_day == self.state.last_day:
            return False

        self.state.last_day = current_day
        self.state.weather_forecast = None
        self.state.current_weather = None
        self.state.weather_forecast_last_updated = -1
        self.state.weather_forecast_last_attempted = -1
        self.state.current_weather_last_updated = -1
        self.state.current_weather_last_attempted = -1
        sync_time()
        return True

    def _send_startup_discord_if_ready(self):
        if self.startup_discord_sent or self.startup_discord_disabled or not self.lan_ip:
            return False
        if not config_manager.get_global("discord_webhook_url", ""):
            self.startup_discord_disabled = True
            return False
        if time.ticks_diff(time.ticks_ms(), self.startup_discord_ready_ms) < 0:
            return False
        if time.ticks_diff(time.ticks_ms(), self.startup_discord_last_attempt_ms) < STARTUP_DISCORD_RETRY_MS:
            return False
        print("Info: Sending delayed Discord LAN IP notification.")
        self.startup_discord_last_attempt_ms = time.ticks_ms()
        self.startup_discord_attempted = True
        release_display_workspace()
        result = send_lan_ip(self.lan_ip)
        if result is None:
            print("Warning: Discord LAN IP notification hit ENOMEM; will retry later.")
        else:
            self.startup_discord_sent = result
            if result:
                self.presence.discord_disabled = False
        return True

    def _startup_discord_pending(self):
        return (
            bool(self.lan_ip) and
            not self.startup_discord_attempted and
            not self.startup_discord_sent and
            not self.startup_discord_disabled and
            bool(config_manager.get_global("discord_webhook_url", ""))
        )

    def _update_display(self, t):
        """Updates the display content based on current state and time.

        Args:
            t (tuple): Current time tuple.
        """
        current_date = f"{t[1]:02d}{t[2]:02d}"
        birthday = config_manager.get("user.birthday", "0101")
        image_interval = config_manager.get("user.image_interval_min", 2)
        self.state.display_image_path = image_catalog.select(
            current_date,
            birthday,
            image_interval,
        )
        self.state.current_event_date = current_date
        birthday_image = (
            birthday == current_date and
            self.state.display_image_path and
            self.state.display_image_path.startswith("/image/events/birthday/")
        )

        # Page rendering logic
        if birthday_image:
            update_page_birthday(self.state.partial_update, t, self.state.display_image_path)
        elif self.state.current_weather and self.state.weather_forecast:
            update_page_weather(
                self.state.current_weather, 
                self.state.weather_forecast, 
                self.state.display_image_path, 
                self.state.partial_update, 
                t,
                dht22_temp=self.state.current_temperature,
                dht22_humidity=self.state.current_humidity
            )
        else:
            update_page_time_image(self.state.display_image_path, self.state.partial_update, t)

    def _perform_chime(self, t):
        """Plays chime sound based on configured interval."""
        if self.chime and config_manager.get('chime.enabled'):
            is_hourly = config_manager.get('chime.interval') == 'hourly'
            is_half_hourly = config_manager.get('chime.interval') == 'half_hourly'

            if t[4] == 0 and (is_hourly or is_half_hourly):
                self.chime.do_chime(
                    pitch=config_manager.get('chime.pitch', 880),
                    volume=config_manager.get('chime.volume', 80)
                )
            if t[4] == 30 and is_half_hourly:
                self.chime.do_chime(
                    pitch=config_manager.get('chime.pitch', 880),
                    volume=config_manager.get('chime.volume', 80)
                )

    def _update_weather(self):
        """Fetches and updates current weather and forecast data if needed."""
        try:
            used_network = False
            now_ms = time.ticks_ms()

            current_attempt_allowed = (
                self.state.current_weather_last_attempted < 0 or
                time.ticks_diff(now_ms, self.state.current_weather_last_attempted) > CURRENT_WEATHER_RETRY_MS
            )
            current_due = current_attempt_allowed and (
                not self.state.current_weather or
                time.ticks_diff(now_ms, self.state.current_weather_last_updated) > CURRENT_WEATHER_REFRESH_MS
            )
            if self.state.is_first_run and self.state.current_weather_last_attempted < 0:
                current_due = True

            if current_due:
                used_network = True
                self.state.current_weather_last_attempted = now_ms
                current_weather = fetch_current_weather(self.api_key, self.location)
                if current_weather:
                    self.state.current_weather = current_weather
                    self.state.current_weather_last_updated = time.ticks_ms()

            now_ms = time.ticks_ms()
            forecast_attempt_allowed = (
                self.state.weather_forecast_last_attempted < 0 or
                time.ticks_diff(now_ms, self.state.weather_forecast_last_attempted) > FORECAST_RETRY_MS
            )
            forecast_due = forecast_attempt_allowed and (
                not self.state.weather_forecast or
                time.ticks_diff(now_ms, self.state.weather_forecast_last_updated) > FORECAST_REFRESH_MS
            )
            if self.state.is_first_run and self.state.weather_forecast_last_attempted < 0:
                forecast_due = True

            if forecast_due:
                used_network = True
                self.state.weather_forecast_last_attempted = now_ms
                weather_forecast = fetch_weather_forecast(self.api_key, self.location, days_limit=5, timezone_offset=self.time_zone_offset)
                if weather_forecast:
                    self.state.weather_forecast = weather_forecast
                    self.state.weather_forecast_last_updated = time.ticks_ms()

            # Clear current weather data if older than 30 minutes
            if time.ticks_diff(time.ticks_ms(), self.state.current_weather_last_updated) > CURRENT_WEATHER_MAX_AGE_MS:
                self.state.current_weather = None

            # Clear weather forecast data if older than 4 hours
            if time.ticks_diff(time.ticks_ms(), self.state.weather_forecast_last_updated) > FORECAST_MAX_AGE_MS:
                self.state.weather_forecast = None

            return used_network
        finally:
            gc.collect()
    
    def _update_sensor_data(self):
        """Reads DHT22 sensor data and updates application state.
        
        Hardware manager handles throttling internally, so safe to call frequently.
        Only updates state on successful read; preserves old values on failure.
        """
        sensor_data = self.hw.get_temperature_humidity()
        
        if sensor_data is not None:
            # Successful read: update state
            temperature, humidity = sensor_data
            self.state.current_temperature = temperature
            self.state.current_humidity = humidity
            # Note: timestamp is managed by hardware layer's actual read time
            print(f"DHT22: {temperature}C, {humidity}%")
