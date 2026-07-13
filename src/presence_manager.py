import gc
import os
import time

from config_manager import config_manager


EVENT_FILE = "presence_events.log"
DAILY_FILE = "presence_daily.log"
PENDING_FILE = "presence_pending.log"
PENDING_SESSION_FILE = "presence_session_pending.log"
RETENTION_DAYS = 30
DISCORD_FLUSH_INTERVAL_MS = 60 * 1000

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

def _read_first_line(path):
    _recover_replacement(path)
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    return line
    except OSError:
        pass
    return None

def iter_lines(path):
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield line
    except OSError:
        return


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _recover_replacement(path):
    backup_path = path + ".bak"
    tmp_path = path + ".tmp"
    if _exists(backup_path):
        if _exists(path):
            _remove_quiet(backup_path)
        else:
            os.rename(backup_path, path)
    if _exists(tmp_path):
        if _exists(path):
            _remove_quiet(tmp_path)
        else:
            os.rename(tmp_path, path)


def _commit_tmp(path, tmp_path):
    """Power-loss-safe replacement used by persistent presence queues."""
    backup_path = path + ".bak"
    if _exists(backup_path):
        if _exists(path):
            _remove_quiet(backup_path)
        else:
            os.rename(backup_path, path)

    moved_old = False
    try:
        if _exists(path):
            os.rename(path, backup_path)
            moved_old = True
        os.rename(tmp_path, path)
        sync = getattr(os, "sync", None)
        if sync:
            sync()
        _remove_quiet(backup_path)
    except Exception:
        if not _exists(path) and moved_old and _exists(backup_path):
            os.rename(backup_path, path)
        raise


def _write_lines(path, lines):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        for line in lines:
            f.write(line)
            f.write("\n")
    _commit_tmp(path, tmp_path)


def _append_line(path, line):
    with open(path, "a") as f:
        f.write(line)
        f.write("\n")

def _drop_first_line(path):
    tmp_path = path + ".tmp"
    skipped = False
    first_remaining = None
    try:
        with open(tmp_path, "w") as output:
            for line in iter_lines(path):
                if not skipped:
                    skipped = True
                    continue
                if first_remaining is None:
                    first_remaining = line
                output.write(line)
                output.write("\n")
        _commit_tmp(path, tmp_path)
        return first_remaining
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return _read_first_line(path)


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
            _commit_tmp(path, tmp_path)
        else:
            os.remove(tmp_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


class PresenceManager:
    __slots__ = (
        "discord_sender", "session_sender", "current_date", "current_state",
        "last_change_epoch", "last_change_date", "last_change_time",
        "session_start_epoch", "session_start_date", "session_start_time",
        "last_adc", "last_threshold", "last_update_epoch", "today_seconds",
        "today_transitions", "today_longest_session_seconds", "today_session_count",
        "pending_summary", "pending_session", "flush_summary_first", "last_retry_ms",
        "discord_disabled",
    )

    def __init__(self, discord_sender=None, session_sender=None):
        self.discord_sender = discord_sender
        self.session_sender = session_sender
        self.current_date = None
        self.current_state = None
        self.last_change_epoch = None
        self.last_change_date = ""
        self.last_change_time = ""
        self.session_start_epoch = None
        self.session_start_date = ""
        self.session_start_time = ""
        self.last_adc = None
        self.last_threshold = None
        self.last_update_epoch = None
        self.today_seconds = 0
        self.today_transitions = 0
        self.today_longest_session_seconds = 0
        self.today_session_count = 0
        self.pending_summary = self._load_pending_summary()
        self.pending_session = self._load_pending_session()
        self.flush_summary_first = False
        self.last_retry_ms = time.ticks_add(time.ticks_ms(), -600001)
        self.discord_disabled = False

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
            session_summary = None
            if self.current_state:
                segment_seconds = max(0, int(now_epoch - self.last_change_epoch))
                self.today_seconds += segment_seconds
                self._record_session_duration(segment_seconds)
                session_summary = (
                    self.session_start_date or self.last_change_date,
                    self.session_start_time or self.last_change_time,
                    date,
                    _time_key(local_time),
                    self._session_duration(now_epoch, segment_seconds)
                )
            elif at_desk:
                self.today_session_count += 1
                self._set_session_start(date, _time_key(local_time), now_epoch)
            self.current_state = at_desk
            self.last_change_epoch = now_epoch
            self.today_transitions += 1
            transition_saved = self._record_transition(local_time, at_desk, adc_value)
            if session_summary and transition_saved:
                self._queue_session(session_summary)
                self._clear_session_start()

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
            "longest_session_seconds": self._current_longest_session(now_epoch),
            "session_count": self.today_session_count,
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
        self.today_longest_session_seconds = 0
        self.today_session_count = 1 if at_desk else 0
        if at_desk:
            self._set_session_start(date, self.last_change_time, now_epoch)
        else:
            self._clear_session_start()

    def _restore_day(self, date, local_time, now_epoch, at_desk, adc_value):
        self._start_day(date, local_time, now_epoch, at_desk)
        total = 0
        transitions = 0
        longest_session = 0
        session_count = 0
        restored_open_session = False
        prior_state = None
        prior_epoch = None
        prior_date = ""
        prior_time = ""
        last_state = None
        last_epoch = None
        last_time = ""
        session_start_epoch = None
        session_start_date = ""
        session_start_time = ""

        for line in iter_lines(EVENT_FILE):
            parts = line.split(",")
            if len(parts) < 4 or parts[0] > date:
                continue
            event_date = parts[0]
            event_time = parts[1]
            event_state = parts[2] == "1"
            event_epoch = self._event_epoch(event_date, event_time)
            if event_epoch is None:
                continue

            prior_state = event_state
            prior_epoch = event_epoch
            prior_date = event_date
            prior_time = event_time

            if event_date != date:
                continue

            if last_state:
                segment_seconds = max(0, int(event_epoch - last_epoch))
                total += segment_seconds
                if segment_seconds > longest_session:
                    longest_session = segment_seconds
            if event_state:
                session_count += 1
                session_start_epoch = event_epoch
                session_start_date = event_date
                session_start_time = event_time
            last_state = event_state
            last_epoch = event_epoch
            last_time = event_time
            transitions += 1

        if last_state is not None:
            self.today_seconds = total
            self.today_transitions = transitions
            self.today_longest_session_seconds = longest_session
            self.today_session_count = session_count
            self.current_state = last_state
            self.last_change_epoch = last_epoch
            self.last_change_date = date
            self.last_change_time = last_time
            if last_state:
                self.session_start_epoch = session_start_epoch
                self.session_start_date = session_start_date or date
                self.session_start_time = session_start_time
            else:
                self._clear_session_start()
        elif prior_state:
            self.current_state = True
            self.last_change_epoch = self._event_epoch(date, "000000")
            self.last_change_date = date
            self.last_change_time = "000000"
            self.today_session_count = 1
            self.session_start_epoch = prior_epoch
            self.session_start_date = prior_date
            self.session_start_time = prior_time
            restored_open_session = True

        if at_desk != self.current_state:
            session_summary = None
            if self.current_state:
                segment_seconds = max(0, int(now_epoch - self.last_change_epoch))
                self.today_seconds += segment_seconds
                self._record_session_duration(segment_seconds)
                session_summary = (
                    self.session_start_date or self.last_change_date,
                    self.session_start_time or self.last_change_time,
                    date,
                    _time_key(local_time),
                    self._session_duration(now_epoch, segment_seconds)
                )
            elif at_desk:
                self.today_session_count += 1
                self._set_session_start(date, _time_key(local_time), now_epoch)
            self.current_state = at_desk
            self.last_change_epoch = now_epoch
            self.today_transitions += 1
            transition_saved = self._record_transition(local_time, at_desk, adc_value)
            if session_summary and transition_saved:
                self._queue_session(session_summary)
                self._clear_session_start()
        elif last_state is None and not restored_open_session:
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
            segment_seconds = max(0, int(midnight_epoch - self.last_change_epoch))
            self.today_seconds += segment_seconds
            self._record_session_duration(segment_seconds)

        summary = "{},{},{},{},{}".format(
            self.current_date,
            int(self.today_seconds),
            self.today_transitions,
            int(self.today_longest_session_seconds),
            self.today_session_count
        )
        _append_line(DAILY_FILE, summary)
        self._queue_summary(summary)
        self._trim_retention(new_date)

        self.current_date = new_date
        self.today_seconds = 0
        self.today_transitions = 0
        self.today_longest_session_seconds = 0
        self.today_session_count = 1 if self.current_state else 0
        self.last_change_epoch = midnight_epoch if self.current_state else now_epoch
        if self.current_state:
            self.last_change_date = new_date
            self.last_change_time = "000000"
        gc.collect()

    def _record_session_duration(self, segment_seconds):
        if segment_seconds > self.today_longest_session_seconds:
            self.today_longest_session_seconds = segment_seconds

    def _current_longest_session(self, now_epoch):
        longest = self.today_longest_session_seconds
        if self.current_state and self.last_change_epoch is not None and now_epoch is not None:
            try:
                segment_seconds = max(0, int(now_epoch - self.last_change_epoch))
                if segment_seconds > longest:
                    longest = segment_seconds
            except Exception:
                pass
        return longest

    def _set_session_start(self, date, time_value, epoch):
        self.session_start_date = date
        self.session_start_time = time_value
        self.session_start_epoch = epoch

    def _clear_session_start(self):
        self.session_start_date = ""
        self.session_start_time = ""
        self.session_start_epoch = None

    def _session_duration(self, now_epoch, fallback_seconds):
        if self.session_start_epoch is None:
            return fallback_seconds
        try:
            return max(0, int(now_epoch - self.session_start_epoch))
        except Exception:
            return fallback_seconds

    def _record_transition(self, local_time, at_desk, adc_value):
        self.last_change_date = _date_key(local_time)
        self.last_change_time = _time_key(local_time)
        state = "1" if at_desk else "0"
        line = "{},{},{},{}".format(self.last_change_date, self.last_change_time, state, adc_value)
        try:
            _append_line(EVENT_FILE, line)
            return True
        except Exception as e:
            print("Presence: failed to write event. {}".format(e))
        return False

    def _send_session_summary(self, session_summary):
        if not self.session_sender:
            return False
        try:
            result = self.session_sender(
                session_summary[0],
                session_summary[1],
                session_summary[2],
                session_summary[3],
                session_summary[4]
            )
            if result is None:
                self.discord_disabled = True
                print("Presence: disabling Discord notifications after ENOMEM.")
                return False
            return result
        except Exception as e:
            print("Presence: Discord session failed. {}".format(e))
        return False

    def flush_discord(self):
        if self.discord_disabled:
            if time.ticks_diff(time.ticks_ms(), self.last_retry_ms) >= DISCORD_FLUSH_INTERVAL_MS:
                self.discord_disabled = False
            else:
                return False
        if time.ticks_diff(time.ticks_ms(), self.last_retry_ms) < DISCORD_FLUSH_INTERVAL_MS:
            return False
        self.last_retry_ms = time.ticks_ms()
        sent = False
        if self.flush_summary_first:
            sent = self._retry_pending_summary(force=True)
            if not sent:
                sent = self._retry_pending_session(force=True)
        else:
            sent = self._retry_pending_session(force=True)
            if not sent:
                sent = self._retry_pending_summary(force=True)
        self.flush_summary_first = not self.flush_summary_first
        return sent

    def _queue_session(self, session_summary):
        session_line = self._session_line(session_summary)
        self._save_pending_session(session_line)
        if not self.pending_session:
            self.pending_session = session_line

    def _retry_pending_session(self, force=False):
        if self.discord_disabled or not self.pending_session or not self.session_sender:
            return False
        if not force and time.ticks_diff(time.ticks_ms(), self.last_retry_ms) < DISCORD_FLUSH_INTERVAL_MS:
            return False
        try:
            session_summary = self._parse_session_line(self.pending_session)
            if session_summary and self._send_session_summary(session_summary):
                self._clear_pending_session()
                return True
        except Exception as e:
            print("Presence: pending Discord session retry failed. {}".format(e))
        return False

    def _session_line(self, session_summary):
        return "{},{},{},{},{}".format(
            session_summary[0],
            session_summary[1],
            session_summary[2],
            session_summary[3],
            int(session_summary[4])
        )

    def _parse_session_line(self, line):
        parts = line.split(",")
        if len(parts) < 5:
            return None
        return (parts[0], parts[1], parts[2], parts[3], int(parts[4]))

    def _queue_summary(self, summary):
        self._save_pending_summary(summary)
        if not self.pending_summary:
            self.pending_summary = summary

    def _retry_pending_summary(self, force=False):
        if self.discord_disabled or not self.pending_summary or not self.discord_sender:
            return False
        if not force and time.ticks_diff(time.ticks_ms(), self.last_retry_ms) < DISCORD_FLUSH_INTERVAL_MS:
            return False
        try:
            result = self.discord_sender(self.pending_summary)
            if result is None:
                self.discord_disabled = True
                print("Presence: disabling Discord notifications after ENOMEM.")
            elif result:
                self._clear_pending_summary()
                return True
        except Exception as e:
            print("Presence: pending Discord retry failed. {}".format(e))
        return False

    def _load_pending_summary(self):
        return _read_first_line(PENDING_FILE)

    def _load_pending_session(self):
        return _read_first_line(PENDING_SESSION_FILE)

    def _save_pending_summary(self, summary):
        try:
            _append_line(PENDING_FILE, summary)
        except Exception as e:
            print("Presence: failed to save pending summary. {}".format(e))

    def _save_pending_session(self, session_line):
        try:
            _append_line(PENDING_SESSION_FILE, session_line)
        except Exception as e:
            print("Presence: failed to save pending session. {}".format(e))

    def _clear_pending_summary(self):
        try:
            self.pending_summary = _drop_first_line(PENDING_FILE)
        except Exception as e:
            print("Presence: failed to clear pending summary. {}".format(e))
            self.pending_summary = self._load_pending_summary()

    def _clear_pending_session(self):
        try:
            self.pending_session = _drop_first_line(PENDING_SESSION_FILE)
        except Exception as e:
            print("Presence: failed to clear pending session. {}".format(e))
            self.pending_session = self._load_pending_session()

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
