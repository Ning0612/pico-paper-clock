# display_manager.py
from display_utils import draw_scaled_text, draw_image, display_rotated_screen
from netutils import get_local_time
from file_manager import list_files, get_image_path, shuffle_files
import random
import time

def update_page_weather(current_weather, weather_forecast, display_image_path, partial_update, t, dht22_temp=None, dht22_humidity=None):
    """Updates the display to show weather and time information with DHT22 sensor data and custom image.
    
    Args:
        current_weather: Current weather data from OpenWeather API (temp, condition)
        weather_forecast: Weather forecast list from OpenWeather API
        display_image_path: Path to custom image
        partial_update: Whether to use partial screen update
        t: Current time tuple
        dht22_temp: DHT22 local temperature (optional)
        dht22_humidity: DHT22 local humidity (optional)
    """
    def draw(canvas):
        date_str = "{:02d}/{:02d}".format(t[1], t[2])
        time_str = "{:02d}:{:02d}".format(t[3], t[4])
        today_date = "{:02d}-{:02d}".format(t[1], t[2])
        forecast_start = 0
        current_rain_prob = -1
        if weather_forecast and weather_forecast[0][0] == today_date:
            forecast_start = 1
            current_rain_prob = weather_forecast[0][3]
            
        draw_scaled_text(canvas, date_str, 3, 10, 3, 0)
        draw_scaled_text(canvas, time_str, 3, 40, 3, 0)
        
        if current_weather and current_weather[1] != "Unknown":
            weather_icon_path = "/image/weather_icons/{}.bin".format(current_weather[1])
            draw_image(canvas, weather_icon_path, 32, 32, 130, 0)
        # Display DHT22 local sensor data (replacing original current weather position)
        if dht22_temp is not None:
            draw_scaled_text(canvas, "{:02d}".format(int(dht22_temp)), 130, 32, 2, 0)
            draw_scaled_text(canvas, "o", 157, 25, 1, 0)
            
        if dht22_humidity is not None:
            draw_scaled_text(canvas, "{}%".format(int(dht22_humidity)), 133, 53, 1, 0)
            
        # Display forecast area: first slot = current OpenWeather, next 3 = future forecast
        if weather_forecast:
            offset = 0
            
            # First slot: OpenWeather current weather
            if current_weather and current_weather[1] != "Unknown":
                weather_icon_path = "/image/weather_icons/{}.bin".format(current_weather[1])
                draw_image(canvas, weather_icon_path, 32, 32, 8 + offset, 80)
                draw_scaled_text(canvas, "{:02d}".format(int(current_weather[0])), 15 + offset, 72, 1, 0)
                draw_scaled_text(canvas, "o", 30 + offset, 67, 1, 0)
                # Show current rain probability if available
                if current_rain_prob >= 0:
                    draw_scaled_text(canvas, "{}%".format(int(current_rain_prob)), 15 + offset, 115, 1, 0)
                offset += 40
            
            # Next 3 slots: Future 3-day forecast (skip first day, show next 3)
            for i in range(forecast_start, min(len(weather_forecast), forecast_start + 3)):
                weather = weather_forecast[i]
                icon_path = "/image/weather_icons/{}.bin".format(weather[2])
                draw_image(canvas, icon_path, 32, 32, 8 + offset, 80)
                draw_scaled_text(canvas, "{:02d}".format(int(weather[1])), 15 + offset, 72, 1, 0)
                draw_scaled_text(canvas, "o", 30 + offset, 67, 1, 0)
                draw_scaled_text(canvas, "{}%".format(int(weather[3])), 15 + offset, 115, 1, 0)
                offset += 40
                
        draw_image(canvas, display_image_path, 128, 128, 168, 0)
        
    display_rotated_screen(draw, angle=90, partial_update=partial_update)

def update_page_time_image(display_image_path, partial_update, t):
    """Updates the display to show time and a custom image."""
    def draw(canvas):
        date_str = "{:02d}/{:02d}".format(t[1], t[2])
        time_str = "{:02d}:{:02d}".format(t[3], t[4])
        draw_scaled_text(canvas, date_str, 3, 20, 4, 0)
        draw_scaled_text(canvas, time_str, 3, 70, 4, 0)
        draw_image(canvas, display_image_path, 128, 128, 168, 0)
    display_rotated_screen(draw, angle=90, partial_update=partial_update)

def update_page_birthday(partial_update, t):
    """Updates the display to show a birthday message and image."""
    def draw(canvas):
        date_str = "{:02d}/{:02d}".format(t[1], t[2])
        time_str = "{:02d}:{:02d}".format(t[3], t[4])
        draw_scaled_text(canvas, date_str, 3, 10, 4, 0)
        draw_scaled_text(canvas, time_str, 3, 44, 4, 0)
        draw_scaled_text(canvas, "Happy", 15, 80, 2, 0)
        draw_scaled_text(canvas, "Birthday!", 15, 100, 2, 0)

        image_dir = "/image/events/birthday"
        file_list = list_files(image_dir)
        image_path = get_image_path(image_dir, file_list, offset=0)
        if image_path:
            draw_image(canvas, image_path, 128, 128, 168, 0)
        else:
            draw_scaled_text(canvas, "No image", 20, 140, 2, 0)
            
    display_rotated_screen(draw, angle=90, partial_update=partial_update)

def update_page_loading(partial_update):
    """Updates the display to show a loading screen with a random image."""
    def draw(canvas):
        image_dir = "/image/login"
        file_list = list_files(image_dir)
        if file_list:
            image_name = random.choice(file_list)
            image_path = f"{image_dir}/{image_name}.bin"
            draw_image(canvas, image_path, 296, 128, 0, 0)
        else:
            draw_scaled_text(canvas, "No image", 20, 20, 2, 0)
    display_rotated_screen(draw, angle=90, partial_update=partial_update)

def update_display_Restart():
    """Updates the display to show a reboot message."""
    def draw(canvas):
        draw_scaled_text(canvas, "Reboot...", 3, 50, 4, 0)
    display_rotated_screen(draw, angle=90, partial_update=False)

def update_display_AP(ap_ssid, ap_password, IP):
    """Updates the e-Paper display to show AP mode details (SSID, Password, IP)."""
    def draw(canvas):
        draw_scaled_text(canvas, f"SSID: {ap_ssid}", 3, 20, 2, 0)
        draw_scaled_text(canvas, f"Password: {ap_password}", 3, 50, 2, 0)
        draw_scaled_text(canvas, f"IP: {IP}", 3, 80, 2, 0)
    display_rotated_screen(draw, angle=90, partial_update=False)
