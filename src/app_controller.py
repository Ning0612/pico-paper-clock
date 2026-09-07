# app_controller.py
import time
import gc
from config_manager import config_manager
from netutils import sync_time, get_local_time
from weather import fetch_weather_bundle
from display_manager import update_page_weather, update_page_time_image, update_page_birthday, update_page_image_preview
from display_utils import clear_display_and_sleep, release_display_workspace
from image_manager import image_catalog, image_store
from wifi_manager import reset_wifi_and_reboot
from chime import Chime
from presence_manager import PresenceManager, set_presence_manager
from env_manager import EnvManager, set_env_manager

STARTUP_DISCORD_DELAY_MS = 45 * 1000
STARTUP_DISCORD_RETRY_MS = 30 * 1000
# Heap fragmentation can push the TLS handshake permanently out of reach; only a
# reboot restores a contiguous heap.  Reboot as a last resort, with a cooldown so
# a genuinely unreachable webhook cannot turn into a boot loop.
#
# Measured on device 2026-07-26 (MicroPython 1.24.1, .mpy deployment): once the
# app reaches steady state the largest contiguous block is only ~10 KiB against a
# 20 KiB threshold, and release_display_workspace() does not move it at all.  So
# waiting does not help -- the reboot's low-memory startup window is the only one
# ever observed to succeed.  Retrying 30 times first only delayed every
# notification by half an hour without changing the outcome.  (Single device,
# single firmware, .mpy deployment: re-measure before assuming it elsewhere.)
#
# Since waiting buys nothing, the threshold is set by what a reboot *costs* right
# now rather than by how long the stall has lasted.  presence_manager queues the
# session summary on the leave transition, so nearly every pending notification is
# born while the user is away: the panel has already been cleared and put to sleep,
# nobody is there to see the boot screen, and two failed attempts (~2 min) are
# enough to stop waiting.  While the user is present the same reboot means staring
# at the loading page through a Wi-Fi reconnect and an NTP sync, so presence keeps
# the slower threshold.
#
# The present threshold is deliberately not "never".  It is the only remaining
# path out of fragmentation if the light sensor ever reads a lit but empty room as
# occupied -- an away-only trigger would never fire there, leaving notifications
# stuck for longer than before this change.  Ten attempts also leaves transient
# pressure (an image upload, an active Web UI session) room to clear on its own.
DISCORD_STALL_AWAY_FAILURES = 2
DISCORD_STALL_PRESENT_FAILURES = 10
# Long enough that the startup low-memory window (STARTUP_DISCORD_DELAY_MS) has
# had its turn and the display, server and sensor objects have settled.  It no
# longer has to stay clear of any multiple of the failure count: the check below
# re-evaluates on every *new* failure instead of on exact multiples, so a check
# this gate rejects costs one retry interval rather than another whole threshold.
DISCORD_STALL_MIN_UPTIME_MS = 5 * 60 * 1000
AUTO_RESET_STATE_FILE = "discord_autoreset.log"
# Left at two hours: shortening it bought little (observed gaps between backlogs
# are many hours) while weakening the only guard between a permanently wedged
# send and an hourly reboot cycle.  Note this is a per-reboot cooldown, not a
# per-backlog one -- a backlog deeper than flush_startup_discord()'s 8-message
# limit still needs one reboot per 8 notifications.
MIN_SECONDS_BETWEEN_AUTO_RESETS = 2 * 60 * 60
# Backoff between attempts to clear and sleep a panel that is refusing to do so.
DISPLAY_SLEEP_RETRY_MS = 60 * 1000
CURRENT_WEATHER_REFRESH_MS = 3 * 60 * 1000
CURRENT_WEATHER_RETRY_MS = 10 * 60 * 1000
FORECAST_REFRESH_MS = 30 * 60 * 1000
FORECAST_RETRY_MS = 10 * 60 * 1000


def _discord_configured():
    try:
        return bool(config_manager.get_global("discord_webhook_url", ""))
    except Exception:
        return False


def _send_lan_ip(ip_address):
    if not _discord_configured():
        return False
    from discord_notifier import send_lan_ip
    return send_lan_ip(ip_address)


def _send_presence_session(start_date, start_time, end_date, end_time, duration_seconds):
    if not _discord_configured():
        return False
    from discord_notifier import send_presence_session
    return send_presence_session(start_date, start_time, end_date, end_time, duration_seconds)


def _send_presence_summary(summary_line):
    if not _discord_configured():
        return False
    from discord_notifier import send_presence_summary
    return send_presence_summary(summary_line)

class AppController:
    """Manages the application's main logic, including hardware interaction, display updates, and data fetching."""
    __slots__ = (
        "state", "hw", "lan_server", "lan_ip", "startup_discord_sent",
        "startup_discord_disabled", "startup_discord_attempted", "startup_discord_ready_ms",
        "startup_discord_last_attempt_ms", "chime", "weather_latitude", "weather_longitude",
        "time_zone_offset", "presence", "env", "boot_ms", "min_uptime_reached",
        "auto_reset_blocked", "stall_checked_failures", "stall_checked_threshold",
        "display_sleep_retry_ms",
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
        self.weather_latitude = config_manager.get("weather.latitude")
        self.weather_longitude = config_manager.get("weather.longitude")
        self.time_zone_offset = config_manager.get("user.timezone_offset", 8)
        self.presence = PresenceManager(
            discord_sender=_send_presence_summary,
            session_sender=_send_presence_session
        )
        # Let the display, sensor, and server objects settle before the first
        # pending Discord retry; the startup webhook already used the safe
        # low-memory window.
        self.presence.last_retry_ms = time.ticks_ms()
        set_presence_manager(self.presence)
        self.env = EnvManager(
            sample_interval_min=config_manager.get_global("env_log.interval_min", 15)
        )
        set_env_manager(self.env)
        self.boot_ms = time.ticks_ms()
        # Latched once reached: ticks_diff() is only valid over ~6.2 days, and the
        # fragmentation this guards against shows up after ~12 days of uptime.
        self.min_uptime_reached = False
        self.auto_reset_blocked = False
        # Failure count and threshold whose reboot decision has already been made;
        # -1 means none.
        self.stall_checked_failures = -1
        self.stall_checked_threshold = -1
        # Deadline before the next clear-and-sleep attempt; None means try now.
        self.display_sleep_retry_ms = None


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

        # Consumed here but rendered further down: a preview may replace this
        # pass's page render, never the housekeeping below it.  Returning early
        # instead -- as this used to -- let a client uploading with preview=true
        # once per loop starve presence updates (so the leave debounce never
        # advances), env sampling, button handling and the Discord stall check
        # for as long as it kept posting.
        preview = image_store.consume_preview()

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

        # Sample independently of presence/display state so room temperature
        # keeps being logged while the user is away from the desk.
        if config_manager.get_global("env_log.enabled", True):
            self.env.update(t, self.hw)

        # Drive the display from the debounced presence state so both transitions
        # honor their configured timeout instead of reacting to raw ADC changes.
        if self.presence.current_state is True:
            self.state.display_asleep = False
            # Dropped on return, not carried: a deadline left over from an earlier
            # away period could sit further in the past than ticks_diff() can
            # resolve (~6.2 days), which would read as "not due yet" and leave the
            # panel awake through the next away period.
            self.display_sleep_retry_ms = None
            # A preview takes this pass's render slot, leaving last_minute and
            # partial_update untouched so the normal page returns on the next
            # trigger.  Dropped while away: the panel is asleep in an unlit room,
            # where the preview is unreadable and would only wake it.
            # Handled on preview passes too: get_touch_state() above has already
            # taken the event from the driver, so leaving it to the render branch
            # would silently swallow an image advance whenever a preview lands on
            # the same pass.  A None touch_state is a no-op, which is what the
            # render branch relied on anyway.
            self.handle_touch(touch_state)
            if preview:
                update_page_image_preview(preview[0], preview[1], preview[2])
            else:
                # If date has changed
                self._handle_date_change(t[2])

                # If minute has changed, or touch occurred, or first run
                if t[4] != self.state.last_minute or touch_state is not None or self.state.is_first_run:
                    self._perform_chime(t)
                    self._update_sensor_data()
                    weather_used_network = self._update_weather()
                    self._update_display(t)

                    self.state.is_first_run = False
                    self.state.partial_update = not self.state.partial_update
                    self.state.last_minute = t[4]
        else:
            # Away is a *state*, not just a transition.  Reacting only to the
            # present->away edge left the panel awake and holding whatever it
            # last drew whenever the app *entered* the loop already away --
            # most visibly the loading page after a reboot in an unlit room,
            # which the Discord auto-reset turned from rare into routine.
            # Converging on the same end state from every route also covers a
            # preview arriving while away: it was consumed above and is dropped
            # here rather than drawn, so the panel stays asleep.
            if not self.state.display_asleep and self._display_sleep_retry_due():
                # Guarded because main.py drives this loop bare (`while True:
                # run_main_loop()`): an exception here would end the program and
                # take _check_discord_stall() below down with it -- exactly when
                # the heap is most starved, and on the one path every dark-room
                # reboot is guaranteed to take.
                try:
                    clear_display_and_sleep()
                    self.state.display_asleep = True
                    self.display_sleep_retry_ms = None
                except Exception as e:
                    # Backed off rather than retried every pass: a full clear plus
                    # panel init is expensive, and repeating it once a second on a
                    # persistently failing panel would delay LAN polling, presence
                    # and the stall check while flooding the UART log.
                    self.display_sleep_retry_ms = time.ticks_add(
                        time.ticks_ms(), DISPLAY_SLEEP_RETRY_MS
                    )
                    print("Error: could not put the display to sleep. {}".format(e))
            # Reset flags when screen is off to ensure full update on wake-up
            self.state.is_first_run = True
            self.state.partial_update = False

        if not weather_used_network and not discord_used_network:
            if not self._send_startup_discord_if_ready():
                if not self._startup_discord_pending():
                    self.presence.flush_discord()
        self._check_discord_stall()
        gc.collect()

    def _auto_reset_allowed(self):
        """Blocks a second auto-reset until the cooldown has elapsed."""
        try:
            with open(AUTO_RESET_STATE_FILE) as f:
                raw = f.read().strip()
        except OSError as e:
            # A missing file is the one benign case: nothing has been recorded yet,
            # and the very first auto-reset must not be blocked.  Every other I/O
            # error leaves the cooldown *unknown*, and unknown must not read as
            # "allowed" -- a flash read that fails intermittently would otherwise
            # wave through a reboot every time it failed.
            # errno lives on .errno in CPython and MicroPython alike; args[0] is the
            # fallback for ports that only populate the tuple.  2 is ENOENT, spelled
            # out rather than imported so this path costs no module.
            code = getattr(e, "errno", None)
            if code is None and e.args:
                code = e.args[0]
            if code == 2:
                return True
            print("Error: could not read the auto-reset cooldown. {}".format(e))
            return False
        except Exception as e:
            print("Error: could not read the auto-reset cooldown. {}".format(e))
            return False
        last = None
        try:
            last = int(raw)
        except Exception:
            pass
        if last is None or last <= 0:
            # The file exists but holds nothing usable -- a truncated write, a
            # corrupted block, a zero from a partially formatted flash.  Reading
            # that as "never rebooted" would throw away the only boot-loop guard
            # there is, and at the away threshold (~2 min) that means a reboot
            # every time the uptime gate opens.  Restart the cooldown from now
            # instead: one lost recovery, not an endless loop.
            return self._restart_cooldown("auto-reset timestamp is unreadable")
        try:
            elapsed = time.time() - last
        except Exception as e:
            # Fail closed for the same reason as above: no usable clock means no
            # way to tell whether the cooldown has elapsed.
            print("Error: could not evaluate the auto-reset cooldown. {}".format(e))
            return False
        if elapsed < 0:
            # The clock ran backwards, which on this board means the time base
            # changed rather than the timestamp being wrong: the Pico W has no
            # battery-backed RTC, so a reboot whose NTP sync failed restarts
            # time.time() from the port epoch while the stored value came from a
            # synced boot.  The difference is then meaningless and permanently
            # negative -- read as "not elapsed" it would block every future
            # auto-reset until NTP succeeds again.  Re-stamp onto the current base
            # and wait out one cooldown on it; treating it as elapsed instead would
            # allow a reboot on every pass, and each reboot would reset the base
            # again.
            return self._restart_cooldown("auto-reset timestamp predates the current clock")
        return elapsed >= MIN_SECONDS_BETWEEN_AUTO_RESETS

    def _restart_cooldown(self, reason):
        """Re-stamps an unusable cooldown and denies this round; always False."""
        print("Error: {}; restarting the cooldown.".format(reason))
        if not self._record_auto_reset():
            # Same fail-safe as the caller's own write failure: without a durable
            # timestamp there is nothing left to stop a boot loop.
            self.auto_reset_blocked = True
        return False

    def _record_auto_reset(self):
        """Persists the reset timestamp; False means the cooldown cannot be trusted."""
        try:
            with open(AUTO_RESET_STATE_FILE, "w") as f:
                f.write(str(int(time.time())))
            return True
        except Exception as e:
            print("Error: Could not persist the auto-reset timestamp. {}".format(e))
            return False

    def _display_sleep_retry_due(self):
        """False while backing off from a panel that failed to clear and sleep."""
        if self.display_sleep_retry_ms is None:
            return True
        return time.ticks_diff(time.ticks_ms(), self.display_sleep_retry_ms) >= 0

    def _stall_reset_threshold(self):
        """How many memory failures to tolerate before rebooting, by presence state.

        Away is the cheap moment to reboot -- the panel is already cleared and
        asleep and nobody is watching -- and it is also where nearly every pending
        notification comes from, since presence_manager queues the session summary
        on the leave transition.  current_state is None until the first presence
        update; that counts as present, the conservative side, and the uptime gate
        has not opened that early anyway.
        """
        if self.presence.current_state is False:
            return DISCORD_STALL_AWAY_FAILURES
        return DISCORD_STALL_PRESENT_FAILURES

    def _check_discord_stall(self):
        """Reboots when Discord is wedged by heap fragmentation and nothing else."""
        if not _discord_configured():
            return
        # Latch on every loop, never only when a stall is already detected: after
        # ~6.2 days ticks_diff() stops being meaningful, and the fragmentation this
        # guards against typically appears later than that.
        if not self.min_uptime_reached:
            if time.ticks_diff(time.ticks_ms(), self.boot_ms) >= DISCORD_STALL_MIN_UPTIME_MS:
                self.min_uptime_reached = True

        if self.auto_reset_blocked or not self.min_uptime_reached:
            return
        # Only memory starvation is fixable by rebooting; a dead webhook is not.
        threshold = self._stall_reset_threshold()
        failures = self.presence.discord_mem_failures
        if failures < threshold:
            # Cleared here so a counter that restarts from zero after a successful
            # send cannot climb back onto the latched value below and lose a check.
            self.stall_checked_failures = -1
            return
        if not (self.presence.pending_summary or self.presence.pending_session):
            return
        if self.presence.pending_persist_failed:
            # A reboot would discard a notification that never reached flash.
            return
        if (failures == self.stall_checked_failures
                and threshold == self.stall_checked_threshold):
            # Keeps the cooldown file out of the common path: it is read once per
            # failed attempt (~60 s), not once per loop pass.  Latching on the count
            # rather than on multiples of the threshold means a check rejected by
            # the cooldown is retried at the next failure instead of at the next
            # multiple.  The threshold is part of the latch because it can drop
            # mid-stall: the user leaving the desk must be re-evaluated straight
            # away, not held back until the count happens to move again.
            return
        self.stall_checked_failures = failures
        self.stall_checked_threshold = threshold
        # Evaluated here rather than at boot so the cooldown can expire while running.
        if not self._auto_reset_allowed():
            return
        if not self._record_auto_reset():
            # Without a durable timestamp a reboot could turn into a boot loop.
            self.auto_reset_blocked = True
            return

        # The presence state goes into both records: it is what picked the
        # threshold, so without it the attempt count in discord_diag.log cannot be
        # read back against the constants above.
        where = "away" if self.presence.current_state is False else "present"
        print("Error: Discord stalled for {} attempts while {}; rebooting to defragment the heap.".format(
            self.presence.discord_mem_failures, where
        ))
        try:
            from discord_notifier import diag_record, record_autoreset_ip
            diag_record("autoreset", "failures={},{}".format(
                self.presence.discord_mem_failures, where
            ))
            if self.startup_discord_sent and self.lan_ip:
                # The online notice costs the one TLS window a reboot buys, and
                # after an auto-reset it usually carries an address the user was
                # already told.  Note it so the next boot can spend that window on
                # the backlog instead.  Only an address that actually went out is
                # worth suppressing -- one that never made it still owes its notice.
                record_autoreset_ip(self.lan_ip)
        except Exception:
            pass
        # Pending notifications are already on flash, so nothing is lost.
        import machine
        machine.reset()

    def _handle_date_change(self, current_day):
        """Refresh daily weather while retaining the last-known-good payload."""
        if current_day == self.state.last_day:
            return False

        self.state.last_day = current_day
        # Keep the existing payload visible if the first request of the new day
        # fails.  Reset timestamps to force an immediate bundle refresh without
        # turning a transient network/TLS failure into an empty weather page.
        self.state.weather_forecast_last_updated = -1
        self.state.weather_forecast_last_attempted = -1
        self.state.current_weather_last_updated = -1
        self.state.current_weather_last_attempted = -1
        sync_time()
        return True

    def _send_startup_discord_if_ready(self):
        if self.startup_discord_sent or self.startup_discord_disabled or not self.lan_ip:
            return False
        if not _discord_configured():
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
        result = _send_lan_ip(self.lan_ip)
        if result is None:
            print("Warning: Discord LAN IP notification hit ENOMEM; will retry later.")
        else:
            self.startup_discord_sent = result
            if result:
                self.presence.discord_disabled = False
                self.presence.clear_discord_failures()
        return True

    def _startup_discord_pending(self):
        return (
            bool(self.lan_ip) and
            not self.startup_discord_attempted and
            not self.startup_discord_sent and
            not self.startup_discord_disabled and
            _discord_configured()
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
        used_network = False
        try:
            now_ms = time.ticks_ms()

            current_attempt_allowed = (
                self.state.current_weather_last_attempted < 0 or
                time.ticks_diff(now_ms, self.state.current_weather_last_attempted) > CURRENT_WEATHER_RETRY_MS
            )
            current_due = current_attempt_allowed and (
                not self.state.current_weather or
                self.state.current_weather_last_updated < 0 or
                time.ticks_diff(now_ms, self.state.current_weather_last_updated) > CURRENT_WEATHER_REFRESH_MS
            )
            if self.state.is_first_run and self.state.current_weather_last_attempted < 0:
                current_due = True

            forecast_attempt_allowed = (
                self.state.weather_forecast_last_attempted < 0 or
                time.ticks_diff(now_ms, self.state.weather_forecast_last_attempted) > FORECAST_RETRY_MS
            )
            forecast_due = forecast_attempt_allowed and (
                not self.state.weather_forecast or
                self.state.weather_forecast_last_updated < 0 or
                time.ticks_diff(now_ms, self.state.weather_forecast_last_updated) > FORECAST_REFRESH_MS
            )
            if self.state.is_first_run and self.state.weather_forecast_last_attempted < 0:
                forecast_due = True

            # Always request current conditions and the forecast together.  The
            # current refresh cadence therefore controls the bundle cadence;
            # one TLS handshake is preferable to two independently allocated
            # response paths on this device.
            if current_due or forecast_due:
                used_network = True
                self.state.current_weather_last_attempted = now_ms
                self.state.weather_forecast_last_attempted = now_ms
                release_display_workspace()
                gc.collect()
                weather_bundle = fetch_weather_bundle(
                    self.weather_latitude,
                    self.weather_longitude,
                    days_limit=5,
                    timezone_offset=self.time_zone_offset,
                )
                if weather_bundle:
                    current_weather, weather_forecast = weather_bundle
                    updated_ms = time.ticks_ms()
                    self.state.current_weather = current_weather
                    self.state.weather_forecast = weather_forecast
                    self.state.current_weather_last_updated = updated_ms
                    self.state.weather_forecast_last_updated = updated_ms

            return used_network
        except Exception as e:
            print("Error: Weather update failed; retaining last-known-good data. {}".format(e))
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
