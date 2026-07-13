# weather.py
import time
import urequests
import network
import gc
import ujson

OPENWEATHER_BASE_URL = "http://api.openweathermap.org/data/2.5"
FORECAST_COUNTS = (24, 20, 16, 12, 8)
FORECAST_READ_BUFFER_SIZE = 256
MAX_FORECAST_ENTRY_BYTES = 2048

def _make_request_with_retry(url, max_retries=2, delay=2):
    """Makes an HTTP request with retry mechanism and error handling."""
    for attempt in range(max_retries):
        response = None
        try:
            gc.collect()
            response = urequests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"Memory available after request: {gc.mem_free()} bytes.")
                result = response
                response = None
                return result
            else:
                print(f"Error: API request failed on attempt {attempt + 1}/{max_retries}. Status code: {response.status_code}")
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
        finally:
            if response:
                try:
                    response.close()
                except Exception:
                    pass
            response = None
            gc.collect()
        
        if attempt < max_retries - 1:
            time.sleep(delay)
    
    print(f"Error: API request failed after {max_retries} attempts for URL: {url}")
    return None

def _finalize_forecast_day(result, current_date, temps_sum, temps_count, weather_counts, rain_sum, rain_count):
    if temps_count <= 0:
        return
    avg_temp = temps_sum / temps_count
    most_common_weather = max(weather_counts, key=weather_counts.get)
    avg_rain_prob = (rain_sum / rain_count) * 100 if rain_count > 0 else 0
    result.append((current_date, avg_temp, most_common_weather, avg_rain_prob))

def _iter_raw_bytes(raw):
    """Yields response bytes while reusing a fixed buffer when supported."""
    buffer = bytearray(FORECAST_READ_BUFFER_SIZE)
    readinto = getattr(raw, "readinto", None)
    if readinto is not None:
        try:
            while True:
                count = readinto(buffer)
                if count is None:
                    raise OSError("forecast stream has no data")
                if count < 0:
                    raise OSError("forecast stream read failed: {}".format(count))
                if count == 0:
                    return
                for index in range(count):
                    yield buffer[index]
        except TypeError:
            # A few host test doubles and older stream wrappers only support
            # read(size); fall through without losing data.
            pass

    while True:
        chunk = raw.read(FORECAST_READ_BUFFER_SIZE)
        if not chunk:
            return
        for value in chunk:
            yield value


def _iter_forecast_entries(response):
    raw = getattr(response, "raw", None)
    if raw is None:
        raise AttributeError("Response raw stream is not available")

    list_key = b'"list"'
    key_pos = 0
    waiting_for_list = False
    in_list = False
    in_string = False
    escape = False
    depth = 0
    entry = None

    for b in _iter_raw_bytes(raw):
        if not in_list:
            if waiting_for_list:
                if b == ord('['):
                    in_list = True
                    waiting_for_list = False
                continue

            if b == list_key[key_pos]:
                key_pos += 1
                if key_pos == len(list_key):
                    waiting_for_list = True
                    key_pos = 0
            else:
                key_pos = 1 if b == list_key[0] else 0
            continue

        if entry is None:
            if b == ord('{'):
                entry = bytearray()
                entry.append(b)
                depth = 1
                in_string = False
                escape = False
            elif b == ord(']'):
                return
            continue

        entry.append(b)
        if len(entry) > MAX_FORECAST_ENTRY_BYTES:
            raise ValueError("forecast entry is too large")
        if in_string:
            if escape:
                escape = False
            elif b == 92:
                escape = True
            elif b == 34:
                in_string = False
        else:
            if b == 34:
                in_string = True
            elif b == ord('{'):
                depth += 1
            elif b == ord('}'):
                depth -= 1
                if depth == 0:
                    yield entry
                    entry = None
                    gc.collect()

def _aggregate_forecast_stream(response, days_limit, timezone_offset):
    result = []
    processed_days = 0
    current_date = None
    temps_sum = 0
    temps_count = 0
    weather_counts = {}
    rain_sum = 0
    rain_count = 0

    for entry_bytes in _iter_forecast_entries(response):
        if processed_days >= days_limit:
            break

        entry = ujson.loads(entry_bytes.decode())
        dt = entry["dt"]
        local_time = time.localtime(dt + timezone_offset * 3600)
        month_day = "{:02d}-{:02d}".format(local_time[1], local_time[2])

        if current_date is None:
            current_date = month_day

        if month_day != current_date:
            _finalize_forecast_day(result, current_date, temps_sum, temps_count, weather_counts, rain_sum, rain_count)
            processed_days += 1

            current_date = month_day
            temps_sum = 0
            temps_count = 0
            weather_counts.clear()
            rain_sum = 0
            rain_count = 0

        temp = entry["main"]["temp"]
        weather = entry["weather"][0]["main"]
        rain_prob = entry.get("pop", 0)

        temps_sum += temp
        temps_count += 1
        weather_counts[weather] = weather_counts.get(weather, 0) + 1
        rain_sum += rain_prob
        rain_count += 1

        entry = None
        entry_bytes = None
        gc.collect()

    if temps_count > 0 and processed_days < days_limit:
        _finalize_forecast_day(result, current_date, temps_sum, temps_count, weather_counts, rain_sum, rain_count)

    return result

def fetch_current_weather(api_key, location):
    """Fetches current weather information."""
    if not network.WLAN(network.STA_IF).isconnected():
        print("Info: No internet connection. Skipping current weather request.")
        return None
    print(f"Info: Fetching current weather for {location}.")
    url = "{}/weather?q={},TW&appid={}&units=metric".format(OPENWEATHER_BASE_URL, location, api_key)
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
            gc.collect()
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
    max_count = min(24, max(8, days_limit * 6))

    for forecast_count in FORECAST_COUNTS:
        if forecast_count > max_count:
            continue
        response = None
        try:
            gc.collect()
            url = "{0}/forecast?q={1},TW&appid={2}&units=metric&cnt={3}".format(OPENWEATHER_BASE_URL, location, api_key, forecast_count)
            response = _make_request_with_retry(url)

            if not response:
                continue

            if response.status_code != 200:
                print(f"Error: Weather forecast query failed with status code: {response.status_code}")
                continue

            result = _aggregate_forecast_stream(response, days_limit, timezone_offset)
            gc.collect()
            return result

        except (ValueError, AttributeError) as e:
            print(f"Error: Failed to parse weather forecast data. Invalid JSON or attribute error. Details: {e}")
            return []
        except MemoryError:
            print("Warning: Memory allocation failed with forecast cnt={}. Retrying smaller request.".format(forecast_count))
            gc.collect()
        except Exception as e:
            print(f"Error: An unexpected error occurred while fetching weather forecast. Details: {e}")
            return []
        finally:
            if response:
                try:
                    response.close()
                except Exception as e_close:
                    print(f"Error: Failed to close response for weather forecast request. Details: {e_close}")
            response = None
            gc.collect()

    print("Error: Weather forecast failed after all memory fallback attempts.")
    return []
