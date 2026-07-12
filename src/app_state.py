# app_state.py

class AppState:
    """Manages the application's current state, including display, weather, and touch information."""
    __slots__ = (
        "last_minute", "last_day", "last_touch_time",
        "current_weather", "current_weather_last_updated", "current_weather_last_attempted",
        "weather_forecast", "weather_forecast_last_updated", "weather_forecast_last_attempted",
        "current_temperature", "current_humidity", "sensor_last_updated_ms",
        "is_first_run", "partial_update", "display_image_path", "current_event_date",
    )
    def __init__(self):
        self.last_minute = -1
        self.last_day = -1
        self.last_touch_time = -1

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
        self.display_image_path = ""
        self.current_event_date = ""
