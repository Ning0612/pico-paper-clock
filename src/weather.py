# weather.py
import time
import urequests
import network
import gc

def _make_request_with_retry(url, max_retries=3, delay=5):
    """Makes an HTTP request with retry mechanism and error handling."""
    for attempt in range(max_retries):
        try:
            response = urequests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"Memory available after request: {gc.mem_free()} bytes.")
                return response
            else:
                print(f"Error: API request failed on attempt {attempt + 1}/{max_retries}. Status code: {response.status_code}")
                response.close()
        except OSError as e:
            if e.errno == 103:
                print(f"Warning: Connection aborted on attempt {attempt + 1}/{max_retries}.")
            else:
                print(f"Error: Network issue on attempt {attempt + 1}/{max_retries}. Details: {e}")
        except MemoryError:
            print(f"Error: Memory allocation failed on attempt {attempt + 1}/{max_retries}. Forcing garbage collection.")
            gc.collect()
        except Exception as e:
            print(f"Error: API request exception on attempt {attempt + 1}/{max_retries}. Details: {e}")
        
        if attempt < max_retries - 1:
            time.sleep(delay)
    
    print(f"Error: API request failed after {max_retries} attempts for URL: {url}")
    return None

def fetch_current_weather(api_key, location):
    """Fetches current weather information."""
    if not network.WLAN(network.STA_IF).isconnected():
        print("Info: No internet connection. Skipping current weather request.")
        return None
    print(f"Info: Fetching current weather for {location}.")
    url = "https://api.openweathermap.org/data/2.5/weather?q={},TW&appid={}&units=metric".format(location, api_key)
    response = _make_request_with_retry(url)
    
    if response:
        try:
            data = response.json()
            temp = data["main"]["temp"]
            condition = data["weather"][0]["main"]
            del data
            gc.collect()

            return temp, condition
        except (ValueError, AttributeError) as e:
            print(f"Error: Failed to parse current weather data. Invalid JSON or attribute error. Details: {e}")
            return None
        except MemoryError:
            print("Error: Memory allocation failed during current weather data processing.")
            return None
        except Exception as e:
            print(f"Error: An unexpected error occurred while fetching current weather. Details: {e}")
            return None
        finally:
            try:
                response.close()
            except Exception as e_close:
                print(f"Error: Failed to close response for current weather request. Details: {e_close}")

    return None

def fetch_weather_forecast(api_key, location, days_limit=4, timezone_offset=8):
    """Fetches weather forecast information. """
    if not network.WLAN(network.STA_IF).isconnected():
        print("Info: No internet connection. Skipping weather forecast request.")
        return []

    print(f"Info: Fetching weather forecast for {location}.")
    gc.collect()
    forecast_count = min(24, max(8, days_limit * 6))
    url = "https://api.openweathermap.org/data/2.5/forecast?q={0},TW&appid={1}&units=metric&cnt={2}".format(location, api_key, forecast_count)
    response = _make_request_with_retry(url)

    if not response:
        return []

    try:
        gc.collect()
        if response.status_code != 200:
            print(f"Error: Weather forecast query failed with status code: {response.status_code}")
            return []
        data = response.json()
        forecast_list = data.get("list", [])
        del data
        gc.collect()

        result = []
        processed_days = 0
        current_date = None
        temps_sum = 0
        temps_count = 0
        weather_counts = {}
        rain_sum = 0
        rain_count = 0

        for i in range(len(forecast_list)):
            if processed_days >= days_limit:
                break

            entry = forecast_list[i]
            dt = entry["dt"]
            local_time = time.localtime(dt + timezone_offset * 3600)
            month_day = "{:02d}-{:02d}".format(local_time[1], local_time[2])

            if current_date is None:
                current_date = month_day

            if month_day != current_date:
                # Store previous day's aggregated data
                if temps_count > 0:
                    avg_temp = temps_sum / temps_count
                    most_common_weather = max(weather_counts, key=weather_counts.get)
                    avg_rain_prob = (rain_sum / rain_count) * 100 if rain_count > 0 else 0
                    result.append((current_date, avg_temp, most_common_weather, avg_rain_prob))
                    processed_days += 1

                # Reset for new day
                current_date = month_day
                temps_sum = temps_count = rain_sum = rain_count = 0
                weather_counts = {}
                gc.collect()

            # Accumulate data for the current day
            temp = entry["main"]["temp"]
            weather = entry["weather"][0]["main"]
            rain_prob = entry.get("pop", 0)

            temps_sum += temp
            temps_count += 1
            weather_counts[weather] = weather_counts.get(weather, 0) + 1
            rain_sum += rain_prob
            rain_count += 1

            # Explicitly release processed entry
            forecast_list[i] = None

        # Process data for the last day
        if temps_count > 0 and processed_days <= days_limit:
            avg_temp = temps_sum / temps_count
            most_common_weather = max(weather_counts, key=weather_counts.get)
            avg_rain_prob = (rain_sum / rain_count) * 100 if rain_count > 0 else 0
            result.append((current_date, avg_temp, most_common_weather, avg_rain_prob))

        # Release main list
        del forecast_list
        gc.collect()
        return result

    except (ValueError, AttributeError) as e:
        print(f"Error: Failed to parse weather forecast data. Invalid JSON or attribute error. Details: {e}")
        return []
    except MemoryError:
        print("Error: Memory allocation failed during weather forecast processing.")
        gc.collect()
        return []
    except Exception as e:
        print(f"Error: An unexpected error occurred while fetching weather forecast. Details: {e}")
        return []
    finally:
        try:
            response.close()
        except Exception as e_close:
            print(f"Error: Failed to close response for weather forecast request. Details: {e_close}")
