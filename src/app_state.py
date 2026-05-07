# app_state.py

class AppState:
    """Manages the application's current state, including display, weather, and touch information."""
    def __init__(self):
        self.last_minute = -1
        self.last_day = -1
        self.last_touch_time = -1

        self.image_offset = 0

        self.current_weather = None
        self.current_weather_last_updated = -1
        self.current_weather_last_attempted = -1

        self.weather_forecast = None
        self.weather_forecast_last_updated = -1
        self.weather_forecast_last_attempted = -1
        
        # DHT22 local sensor data
        self.current_temperature = None
        self.current_humidity = None
        self.sensor_last_updated_ms = -1
        
        self.is_first_run = True
        self.partial_update = False
        self.image_name_list = []
        self.display_image_path = ""

        self.event_image_list = []
        self.event_image_offset = 0
        self.current_event_date = ""
