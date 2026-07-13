# hardware_manager.py
import time
import gc
import dht
from machine import ADC, Pin
from epaper import ICNT86, ICNT_Development, get_touch_state

DHT_READ_INTERVAL_MS = 2500
DHT_FAILURE_RETRY_MS = 10000

class HardwareManager:
    """Manages hardware components like ADC, buttons, and touch panel."""
    def __init__(self):
        """Initializes hardware components."""
        self.adc = ADC(Pin(26))

        self.button_1 = Pin(2, Pin.IN, Pin.PULL_UP)
        self.button_2 = Pin(3, Pin.IN, Pin.PULL_UP)
        self.button_3 = Pin(15, Pin.IN, Pin.PULL_UP)

        self.tp = ICNT86()
        self.icnt_dev = ICNT_Development()
        self.icnt_old = ICNT_Development()
        self.tp.ICNT_Init()
        
        # DHT22 temperature/humidity sensor on GP19
        self.dht_pin = Pin(19, Pin.IN, Pin.PULL_UP)
        self.dht_sensor = dht.DHT22(self.dht_pin)
        # Allow the first read immediately; later reads leave a small margin
        # beyond DHT22's two-second minimum interval.
        self.dht_next_read_ms = time.ticks_ms()
        self.dht_last_read_ms = -1
        self.dht_last_temperature = None
        self.dht_last_humidity = None
        self.dht_cached_values = None
        
        # Button long press detection
        self.button_press_timestamps = {}
        self.long_press_threshold_ms = 3000

    def get_adc_value(self):
        """Reads the ADC value from the light sensor."""
        return self.adc.read_u16()

    def get_button_states(self):
        """Reads the raw button states and inverts them."""
        raw_state_1 = self.button_1.value()
        raw_state_2 = self.button_2.value()
        raw_state_3 = self.button_3.value()

        inverted_state_1 = 1 if raw_state_1 == 0 else 0
        inverted_state_2 = 1 if raw_state_2 == 0 else 0
        inverted_state_3 = 1 if raw_state_3 == 0 else 0
        
        return (inverted_state_1, inverted_state_2, inverted_state_3)

    def get_touch_state(self):
        """Gets the current touch state from the touch panel."""
        return get_touch_state(self.tp, self.icnt_dev, self.icnt_old)
    
    def handle_button_long_press(self, callback=None):
        """Handle button long press detection with callback support.
        
        Args:
            callback: Function to call when long press is detected. 
                     Receives button index (0-2) as parameter.
                     
        Returns:
            True if long press was detected, False otherwise.
        """
        button_states = self.get_button_states()
        current_time_ms = time.ticks_ms()
        
        for i, state in enumerate(button_states):
            if state == 1:  # Button is pressed
                if i not in self.button_press_timestamps:
                    # Record the start of button press
                    self.button_press_timestamps[i] = current_time_ms
                else:
                    # Check if long press threshold is reached
                    press_duration = time.ticks_diff(current_time_ms, self.button_press_timestamps[i])
                    
                    if press_duration >= self.long_press_threshold_ms:
                        print(f"Button {i+1} long pressed for {press_duration} ms")
                        
                        # Call the callback if provided
                        if callback:
                            callback(i)
                            
                        # Clear the timestamp to prevent repeated calls
                        del self.button_press_timestamps[i]
                        return True
            else:
                # Button is released, clear timestamp
                if i in self.button_press_timestamps:
                    del self.button_press_timestamps[i]
        
        return False
    
    def get_temperature_humidity(self):
        """Reads temperature and humidity from DHT22 sensor with built-in throttling.
        
        Returns:
            tuple: (temperature_celsius, humidity_percent) on success, None on failure.
                   Returns the last successful values while a read is throttled or
                   temporarily unavailable.
        """
        current_time_ms = time.ticks_ms()

        if time.ticks_diff(current_time_ms, self.dht_next_read_ms) < 0:
            return self.dht_cached_values

        # The DHT driver uses a software-timed protocol.  Reclaim fragmented
        # heap before starting it, while keeping the sensor read outside the
        # network/weather allocation path.
        gc.collect()
        try:
            if self.dht_pin.value() == 0:
                raise OSError("GPIO19 data line is low; check DHT22 power and pull-up")
            # Read sensor (measure() must be called before reading values)
            self.dht_sensor.measure()
            temperature = self.dht_sensor.temperature()
            humidity = self.dht_sensor.humidity()

            if (
                temperature is None or humidity is None or
                temperature != temperature or humidity != humidity or
                temperature < -40 or temperature > 80 or
                humidity < 0 or humidity > 100
            ):
                raise ValueError("invalid sensor values")

            self.dht_last_read_ms = current_time_ms
            self.dht_last_temperature = temperature
            self.dht_last_humidity = humidity
            self.dht_cached_values = (temperature, humidity)
            self.dht_next_read_ms = time.ticks_add(current_time_ms, DHT_READ_INTERVAL_MS)
            return self.dht_cached_values

        except MemoryError:
            print("DHT22: Read skipped because memory is low; keeping previous values")
        except (OSError, ValueError) as e:
            print(f"DHT22 sensor read error: {e}; keeping previous values")
        except Exception as e:
            print(f"DHT22 sensor unavailable: {e}; keeping previous values")

        # A failed transaction also counts as an attempted measurement.  Wait
        # longer before retrying so a disconnected/noisy sensor cannot flood
        # the serial log or repeatedly compete for heap during network work.
        self.dht_next_read_ms = time.ticks_add(current_time_ms, DHT_FAILURE_RETRY_MS)
        gc.collect()
        return self.dht_cached_values
