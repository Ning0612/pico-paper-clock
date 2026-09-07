# weather.py
import urequests
import network
import gc
import time

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_REQUEST_TIMEOUT_SEC = 5

# Keep the existing icon names used by display_manager.py. Open-Meteo returns
# WMO weather interpretation codes instead of provider-specific condition strings.
WMO_CONDITION_MAP = {
    0: "Clear",
    1: "Clouds",
    2: "Clouds",
    3: "Clouds",
    45: "Fog",
    48: "Fog",
    51: "Drizzle",
    53: "Drizzle",
    55: "Drizzle",
    56: "Drizzle",
    57: "Drizzle",
    61: "Rain",
    63: "Rain",
    65: "Rain",
    66: "Rain",
    67: "Rain",
    71: "Snow",
    73: "Snow",
    75: "Snow",
    77: "Snow",
    80: "Rain",
    81: "Rain",
    82: "Rain",
    85: "Snow",
    86: "Snow",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def _log_heap(label):
    mem_free = getattr(gc, "mem_free", None)
    if not callable(mem_free):
        return
    try:
        free_bytes = mem_free()
        mem_alloc = getattr(gc, "mem_alloc", None)
        if callable(mem_alloc):
            print("Memory {}: free={} bytes, allocated={} bytes.".format(
                label, free_bytes, mem_alloc()
            ))
        else:
            print("Memory {}: free={} bytes.".format(label, free_bytes))
    except Exception:
        pass

def _make_request_with_retry(url, max_retries=2, delay=2):
    """Makes an HTTP request with retry mechanism and error handling."""
    for attempt in range(max_retries):
        response = None
        try:
            gc.collect()
            _log_heap("before weather request")
            response = urequests.get(url, timeout=WEATHER_REQUEST_TIMEOUT_SEC)
            if response.status_code == 200:
                _log_heap("after weather request")
                result = response
                response = None
                return result
            else:
                print("Error: API request failed on attempt {}/{}. Status code: {}".format(
                    attempt + 1, max_retries, response.status_code
                ))
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
    
    print("Error: API request failed after {} attempts for URL: {}".format(
        max_retries, url
    ))
    return None

def _condition_from_code(code):
    try:
        return WMO_CONDITION_MAP.get(int(code), "Clouds")
    except (TypeError, ValueError):
        return "Clouds"


def _timezone_name_from_offset(timezone_offset):
    """Convert the device's fixed UTC offset to an IANA fixed-offset zone."""
    try:
        offset = int(timezone_offset)
    except (TypeError, ValueError):
        offset = 0
    if offset < -12 or offset > 14:
        offset = 0
    if offset == 0:
        return "UTC"
    # Etc/GMT uses the opposite sign by convention: Etc/GMT-8 is UTC+8.
    sign = "-" if offset > 0 else "+"
    return "Etc/GMT{}{}".format(sign, abs(offset))


def _forecast_url(latitude, longitude, variables, timezone_offset=8):
    timezone_name = _timezone_name_from_offset(timezone_offset)
    return "{}?latitude={}&longitude={}&{}&timezone={}".format(
        OPEN_METEO_BASE_URL, latitude, longitude, variables, timezone_name
    )


def _parse_forecast_data(data, days_limit):
    """Converts Open-Meteo daily data to display_manager tuple format."""
    daily = data["daily"]
    dates = daily["time"]
    codes = daily["weather_code"]
    means = daily.get("temperature_2m_mean")
    maximums = daily.get("temperature_2m_max")
    minimums = daily.get("temperature_2m_min")
    rain_probabilities = daily.get("precipitation_probability_max") or []

    count = min(days_limit, len(dates), len(codes))
    if len(rain_probabilities) < count:
        raise ValueError("Open-Meteo precipitation probability is missing")
    result = []
    for index in range(count):
        average = None
        if means and index < len(means):
            average = means[index]
        elif maximums and minimums and index < len(maximums) and index < len(minimums):
            average = (maximums[index] + minimums[index]) / 2
        if average is None:
            raise ValueError("Open-Meteo daily temperature is missing")

        date_value = dates[index]
        if not isinstance(date_value, str) or len(date_value) < 10:
            raise ValueError("Open-Meteo daily date is invalid")
        rain_probability = rain_probabilities[index] if index < len(rain_probabilities) else 0
        result.append((
            date_value[5:10],
            average,
            _condition_from_code(codes[index]),
            rain_probability if rain_probability is not None else 0,
        ))
    return result


def _parse_current_data(data):
    current = data["current"]
    return (
        current["temperature_2m"],
        _condition_from_code(current.get("weather_code")),
    )


def _validated_days_limit(days_limit):
    try:
        days_limit = int(days_limit)
    except (TypeError, ValueError):
        print("Error: Forecast day count is invalid.")
        return None
    if days_limit < 1 or days_limit > 16:
        print("Error: Forecast day count must be between 1 and 16.")
        return None
    return days_limit


def fetch_weather_bundle(latitude, longitude, days_limit=5, timezone_offset=8):
    """Fetch current weather and daily forecast in one atomic request.

    The caller receives both values only when the complete response is valid;
    a failed or partial response returns None so the caller can retain its
    last-known-good weather snapshot.
    """
    if not network.WLAN(network.STA_IF).isconnected():
        print("Info: No internet connection. Skipping combined weather request.")
        return None

    days_limit = _validated_days_limit(days_limit)
    if days_limit is None:
        return None

    print("Info: Fetching current weather and forecast for ({}, {}).".format(
        latitude, longitude
    ))
    url = _forecast_url(
        latitude,
        longitude,
        "current=temperature_2m,weather_code&daily=weather_code,temperature_2m_mean,precipitation_probability_max&forecast_days={}".format(
            days_limit
        ),
        timezone_offset,
    )
    response = _make_request_with_retry(url)
    if not response:
        return None

    try:
        data = response.json()
        current = _parse_current_data(data)
        forecast = _parse_forecast_data(data, days_limit)
        if len(forecast) < days_limit:
            print("Warning: Combined weather response returned only {} of {} requested days.".format(
                len(forecast), days_limit
            ))
            return None
        del data
        gc.collect()
        _log_heap("after combined weather parse")
        return current, forecast
    except (ValueError, AttributeError, KeyError) as e:
        print("Error: Failed to parse combined weather data. Details: {}".format(e))
        return None
    except MemoryError:
        print("Error: Memory allocation failed during combined weather processing.")
        gc.collect()
        return None
    except Exception as e:
        print("Error: Unexpected combined weather exception. Details: {}".format(e))
        return None
    finally:
        try:
            response.close()
        except Exception:
            pass
        response = None
        gc.collect()


def fetch_current_weather(latitude, longitude, timezone_offset=8):
    """Fetches current weather information for a coordinate pair."""
    if not network.WLAN(network.STA_IF).isconnected():
        print("Info: No internet connection. Skipping current weather request.")
        return None

    print("Info: Fetching current weather for ({}, {}).".format(latitude, longitude))
    url = _forecast_url(
        latitude,
        longitude,
        # Request only fields consumed by the display; this keeps the response
        # small during the TLS-sensitive startup and refresh paths.
        "current=temperature_2m,weather_code",
        timezone_offset,
    )
    response = _make_request_with_retry(url)
    if not response:
        return None

    try:
        data = response.json()
        result = _parse_current_data(data)
        del data
        gc.collect()
        _log_heap("after current weather parse")
        return result
    except (ValueError, AttributeError, KeyError) as e:
        print("Error: Failed to parse current weather data. Details: {}".format(e))
        return None
    except MemoryError:
        print("Error: Memory allocation failed during current weather processing.")
        gc.collect()
        return None
    except Exception as e:
        print("Error: Unexpected current weather exception. Details: {}".format(e))
        return None
    finally:
        try:
            response.close()
        except Exception:
            pass
        response = None
        gc.collect()


def fetch_weather_forecast(latitude, longitude, days_limit=5, timezone_offset=8):
    """Fetches daily Open-Meteo forecast in display tuple format."""
    if not network.WLAN(network.STA_IF).isconnected():
        print("Info: No internet connection. Skipping weather forecast request.")
        return []

    days_limit = _validated_days_limit(days_limit)
    if days_limit is None:
        return []

    print("Info: Fetching weather forecast for ({}, {}).".format(latitude, longitude))
    url = _forecast_url(
        latitude,
        longitude,
        # The display uses mean temperature, WMO code and rain probability.
        "daily=weather_code,temperature_2m_mean,precipitation_probability_max&forecast_days={}".format(days_limit),
        timezone_offset,
    )
    response = _make_request_with_retry(url)
    if not response:
        return []

    try:
        data = response.json()
        result = _parse_forecast_data(data, days_limit)
        if len(result) < days_limit:
            print("Warning: Forecast returned only {} of {} requested days.".format(
                len(result), days_limit
            ))
            return []
        del data
        gc.collect()
        _log_heap("after forecast parse")
        return result
    except (ValueError, AttributeError, KeyError) as e:
        print("Error: Failed to parse weather forecast data. Details: {}".format(e))
        return []
    except MemoryError:
        print("Error: Memory allocation failed during forecast processing.")
        gc.collect()
        return []
    except Exception as e:
        print("Error: Unexpected weather forecast exception. Details: {}".format(e))
        return []
    finally:
        try:
            response.close()
        except Exception:
            pass
        response = None
        gc.collect()
