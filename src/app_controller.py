# app_controller.py
import time
from config_manager import config_manager
from netutils import sync_time, get_local_time
from weather import fetch_current_weather, fetch_weather_forecast
from display_manager import update_page_weather, update_page_time_image, update_page_birthday
from file_manager import get_image_path, get_date_event_images, shuffle_files
from wifi_manager import reset_wifi_and_reboot
from chime import Chime
from discord_notifier import send_presence_summary
from presence_manager import PresenceManager, set_presence_manager

class AppController:
    """Manages the application's main logic, including hardware interaction, display updates, and data fetching."""
    def __init__(self, state, hardware, lan_server=None):
        """Initializes the AppController.

        Args:
            state: The application's state object.
            hardware: The hardware manager object.
        """
        self.state = state
        self.hw = hardware
        self.lan_server = lan_server
        self.chime = Chime(20) if config_manager.get('chime.enabled') else None
        self.location = config_manager.get("weather.location", "Taipei")
        self.api_key = config_manager.get("weather.api_key")
        self.time_zone_offset = config_manager.get("user.timezone_offset", 8)
        self.presence = PresenceManager(discord_sender=send_presence_summary)
        set_presence_manager(self.presence)


    def handle_touch(self, touch_state):
        # Handle touch events and switch images
        if touch_state and touch_state[0] == "Touch" and touch_state[1][0] > 168:
            if self.state.event_image_list:
                self.state.event_image_offset = (self.state.event_image_offset + 1) % len(self.state.event_image_list)
                print(f"Event image changed, offset: {self.state.event_image_offset}")
            elif self.state.image_name_list:
                self.state.image_offset = (self.state.image_offset + 1) % len(self.state.image_name_list)
                print(f"Image changed, offset: {self.state.image_offset}")

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
        if self.lan_server:
            self.lan_server.poll()

        adc_value = self.hw.get_adc_value()
        touch_state = self.hw.get_touch_state()
        t = get_local_time(offset=self.time_zone_offset*3600)

        if touch_state:
            self.state.last_touch_time = time.time()

        self.handle_buttons()

        light_threshold = config_manager.get("user.light_threshold", 55000)
        self.presence.update(adc_value, light_threshold, t)
        time_since_touch = time.time() - self.state.last_touch_time if self.state.last_touch_time != -1 else 3601

        # If ambient light is below threshold (screen should be off) or time since last touch is less than 1 hour
        if adc_value <= light_threshold or time_since_touch < 3600:         
            # If date has changed
            if t[2] != self.state.last_day:
                self.state.last_day = t[2]
                self.state.weather_forecast = None
                self.state.current_weather = None
                sync_time()

            # If minute has changed, or touch occurred, or first run
            if t[4] != self.state.last_minute or touch_state is not None or self.state.is_first_run:
                self.handle_touch(touch_state)
                self._perform_chime(t)
                self._update_weather()
                self._update_sensor_data()
                self._update_display(t)

                self.state.is_first_run = False
                self.state.partial_update = not self.state.partial_update
                self.state.last_minute = t[4]
        else:
            # Reset flags when screen is off to ensure full update on wake-up
            self.state.is_first_run = True
            self.state.partial_update = False

    def _update_display(self, t):
        """Updates the display content based on current state and time.

        Args:
            t (tuple): Current time tuple.
        """
        image_directory = "/image/custom"
        self.state.display_image_path = get_image_path(image_directory, self.state.image_name_list, self.state.image_offset)

        # Check for date-specific events
        current_date = f"{t[1]:02d}{t[2]:02d}"
        if current_date != self.state.current_event_date:
            self.state.current_event_date = current_date
            self.state.event_image_list = get_date_event_images(current_date)
            if self.state.event_image_list:
                self.state.event_image_list = shuffle_files(self.state.event_image_list)
                self.state.event_image_offset = 0
                print(f"Date event found for {current_date}, loaded {len(self.state.event_image_list)} images.")

        # Page rendering logic
        if config_manager.get("user.birthday") == current_date:
            update_page_birthday(self.state.partial_update, t)
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
        if time.ticks_diff(time.ticks_ms(), self.state.current_weather_last_updated) > 3 * 60 * 1000 or self.state.is_first_run or not self.state.current_weather:
            current_weather = fetch_current_weather(self.api_key, self.location)
            if current_weather:
                self.state.current_weather = current_weather
                self.state.current_weather_last_updated = time.ticks_ms()
        
        if time.ticks_diff(time.ticks_ms(), self.state.weather_forecast_last_updated) > 30 * 60 * 1000 or self.state.is_first_run or not self.state.weather_forecast:
            weather_forecast = fetch_weather_forecast(self.api_key, self.location, days_limit=4, timezone_offset=self.time_zone_offset)
            if weather_forecast:
                self.state.weather_forecast = weather_forecast
                self.state.weather_forecast_last_updated = time.ticks_ms()

        # Clear current weather data if older than 30 minutes
        if time.ticks_diff(time.ticks_ms(), self.state.current_weather_last_updated) > 30 * 60 * 1000:
            self.state.current_weather = None

        # Clear weather forecast data if older than 4 hours
        if time.ticks_diff(time.ticks_ms(), self.state.weather_forecast_last_updated) > 4 * 60 * 60 * 1000 :
            self.state.weather_forecast = None
    
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
        else:
            # Failed read: preserve old values (None on first failure)
            print("DHT22: Read failed, keeping previous values")
