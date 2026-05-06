import gc
import os
import time

from config_manager import config_manager


EVENT_FILE = "presence_events.log"
DAILY_FILE = "presence_daily.log"
PENDING_FILE = "presence_pending.log"
RETENTION_DAYS = 30

_presence_manager = None


def set_presence_manager(manager):
    global _presence_manager
    _presence_manager = manager


def get_presence_manager():
    return _presence_manager


def _date_key(t):
    return "{:04d}{:02d}{:02d}".format(t[0], t[1], t[2])


def _time_key(t):
    return "{:02d}{:02d}{:02d}".format(t[3], t[4], t[5])


def _seconds_of_day(t):
    return t[3] * 3600 + t[4] * 60 + t[5]


def _epoch(t):
    return time.mktime(t)


def _read_lines(path):
    try:
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []

def iter_lines(path):
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield line
    except OSError:
        return


def _write_lines(path, lines):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        for line in lines:
            f.write(line)
            f.write("\n")
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp_path, path)


def _append_line(path, line):
    with open(path, "a") as f:
        f.write(line)
        f.write("\n")


def _trim_by_date(path, min_date):
    tmp_path = path + ".tmp"
    changed = False
    try:
        with open(tmp_path, "w") as out:
            for line in iter_lines(path):
                parts = line.split(",", 1)
                if parts and parts[0] >= min_date:
                    out.write(line)
                    out.write("\n")
                else:
                    changed = True
        if changed:
            try:
                os.remove(path)
            except OSError:
                pass
            os.rename(tmp_path, path)
        else:
            os.remove(tmp_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


class PresenceManager:
    def __init__(self, discord_sender=None):
        self.discord_sender = discord_sender
        self.current_date = None
        self.current_state = None
        self.last_change_epoch = None
        self.last_change_date = ""
        self.last_change_time = ""
        self.last_adc = None
        self.last_threshold = None
        self.last_update_epoch = None
        self.today_seconds = 0
        self.today_transitions = 0
        self.pending_summary = self._load_pending_summary()
        self.last_retry_ms = time.ticks_add(time.ticks_ms(), -600001)

    def update(self, adc_value, threshold, local_time):
        date = _date_key(local_time)
        now_epoch = _epoch(local_time)
        at_desk = adc_value <= threshold

        self.last_adc = adc_value
        self.last_threshold = threshold
        self.last_update_epoch = now_epoch

        if self.current_date is None:
            self._restore_day(date, local_time, now_epoch, at_desk, adc_value)
            return

        if date != self.current_date:
            self._rollover_day(date, local_time, now_epoch)

        if at_desk != self.current_state:
            if self.current_state:
                self.today_seconds += max(0, int(now_epoch - self.last_change_epoch))
            self.current_state = at_desk
            self.last_change_epoch = now_epoch
            self.today_transitions += 1
            self._record_transition(local_time, at_desk, adc_value)

        self._retry_pending_summary()

    def get_status(self):
        session_seconds = 0
        segment_seconds = 0
        now_epoch = self.last_update_epoch if self.last_update_epoch is not None else self.last_change_epoch
        if self.last_change_epoch is not None and now_epoch is not None:
            try:
                segment_seconds = max(0, int(now_epoch - self.last_change_epoch))
            except Exception:
                segment_seconds = 0
        if self.current_state and self.last_change_epoch is not None:
            try:
                session_seconds = segment_seconds
            except Exception:
                session_seconds = 0
        today_total = self.today_seconds + session_seconds
        return {
            "state": 1 if self.current_state else 0,
            "adc": self.last_adc if self.last_adc is not None else -1,
            "threshold": self.last_threshold if self.last_threshold is not None else config_manager.get("user.light_threshold", 56000),
            "session_seconds": session_seconds,
            "segment_seconds": segment_seconds,
            "today_seconds": today_total,
            "last_change_date": self.last_change_date,
            "last_change_time": self.last_change_time,
            "transitions": self.today_transitions,
            "now_epoch": int(now_epoch) if now_epoch is not None else 0
        }

    def get_events(self):
        return _read_lines(EVENT_FILE)

    def get_daily(self):
        return _read_lines(DAILY_FILE)

    def _start_day(self, date, local_time, now_epoch, at_desk):
        self.current_date = date
        self.current_state = at_desk
        self.last_change_epoch = now_epoch
        self.last_change_date = date
        self.last_change_time = _time_key(local_time)
        self.today_seconds = 0
        self.today_transitions = 0

    def _restore_day(self, date, local_time, now_epoch, at_desk, adc_value):
        self._start_day(date, local_time, now_epoch, at_desk)
        total = 0
        transitions = 0
        last_state = None
        last_epoch = None
        last_time = ""

        for line in iter_lines(EVENT_FILE):
            parts = line.split(",")
            if len(parts) < 4 or parts[0] != date:
                continue
            event_time = parts[1]
            event_state = parts[2] == "1"
            event_epoch = self._event_epoch(date, event_time)
            if event_epoch is None:
                continue
            if last_state:
                total += max(0, int(event_epoch - last_epoch))
            last_state = event_state
            last_epoch = event_epoch
            last_time = event_time
            transitions += 1

        if last_state is not None:
            self.today_seconds = total
            self.today_transitions = transitions
            self.current_state = last_state
            self.last_change_epoch = last_epoch
            self.last_change_date = date
            self.last_change_time = last_time

        if at_desk != self.current_state:
            if self.current_state:
                self.today_seconds += max(0, int(now_epoch - self.last_change_epoch))
            self.current_state = at_desk
            self.last_change_epoch = now_epoch
            self.today_transitions += 1
            self._record_transition(local_time, at_desk, adc_value)
        elif last_state is None:
            self._record_transition(local_time, at_desk, adc_value)

    def _event_epoch(self, date, time_value):
        try:
            return time.mktime((
                int(date[0:4]),
                int(date[4:6]),
                int(date[6:8]),
                int(time_value[0:2]),
                int(time_value[2:4]),
                int(time_value[4:6]),
                0, 0
            ))
        except Exception:
            return None

    def _rollover_day(self, new_date, local_time, now_epoch):
        seconds_at_midnight = _seconds_of_day(local_time)
        midnight_epoch = now_epoch - seconds_at_midnight
        if self.current_state and self.last_change_epoch is not None:
            self.today_seconds += max(0, int(midnight_epoch - self.last_change_epoch))

        summary = "{},{},{}".format(self.current_date, int(self.today_seconds), self.today_transitions)
        _append_line(DAILY_FILE, summary)
        self._send_or_queue_summary(summary)
        self._trim_retention(new_date)

        self.current_date = new_date
        self.today_seconds = 0
        self.today_transitions = 0
        self.last_change_epoch = midnight_epoch if self.current_state else now_epoch
        gc.collect()

    def _record_transition(self, local_time, at_desk, adc_value):
        self.last_change_date = _date_key(local_time)
        self.last_change_time = _time_key(local_time)
        state = "1" if at_desk else "0"
        line = "{},{},{},{}".format(self.last_change_date, self.last_change_time, state, adc_value)
        try:
            _append_line(EVENT_FILE, line)
        except Exception as e:
            print("Presence: failed to write event. {}".format(e))

    def _send_or_queue_summary(self, summary):
        if self.discord_sender:
            try:
                if self.discord_sender(summary):
                    self._clear_pending_summary()
                    return
            except Exception as e:
                print("Presence: Discord summary failed. {}".format(e))
        self.pending_summary = summary
        self._save_pending_summary(summary)

    def _retry_pending_summary(self):
        if not self.pending_summary or not self.discord_sender:
            return
        if time.ticks_diff(time.ticks_ms(), self.last_retry_ms) < 10 * 60 * 1000:
            return
        self.last_retry_ms = time.ticks_ms()
        try:
            if self.discord_sender(self.pending_summary):
                self._clear_pending_summary()
        except Exception as e:
            print("Presence: pending Discord retry failed. {}".format(e))

    def _load_pending_summary(self):
        lines = _read_lines(PENDING_FILE)
        return lines[-1] if lines else None

    def _save_pending_summary(self, summary):
        try:
            _write_lines(PENDING_FILE, [summary])
        except Exception as e:
            print("Presence: failed to save pending summary. {}".format(e))

    def _clear_pending_summary(self):
        self.pending_summary = None
        try:
            os.remove(PENDING_FILE)
        except OSError:
            pass

    def _trim_retention(self, current_date):
        try:
            current_tuple = (
                int(current_date[0:4]),
                int(current_date[4:6]),
                int(current_date[6:8]),
                0, 0, 0, 0, 0
            )
            min_epoch = time.mktime(current_tuple) - (RETENTION_DAYS - 1) * 86400
            min_date_tuple = time.localtime(min_epoch)
            min_date = _date_key(min_date_tuple)
            _trim_by_date(EVENT_FILE, min_date)
            _trim_by_date(DAILY_FILE, min_date)
        except Exception as e:
            print("Presence: retention trim failed. {}".format(e))
