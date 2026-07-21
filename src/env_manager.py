import gc
import os
import time

from presence_manager import (
    _append_line,
    _trim_by_date,
    iter_lines,
)


EVENT_FILE = "env_events.log"
DAILY_FILE = "env_daily.log"
SAMPLE_RETENTION_DAYS = 7
DAILY_RETENTION_DAYS = 366
DEFAULT_SAMPLE_INTERVAL_MIN = 15
MIN_VALID_YEAR = 2023
MAX_SAMPLE_LINES_IN_MEMORY = 700
MAX_DAILY_LINES_IN_MEMORY = 366
MAX_ENV_LINE_CHARS = 48

_env_manager = None


def set_env_manager(manager):
    global _env_manager
    _env_manager = manager


def get_env_manager():
    return _env_manager


def _date_key(t):
    return "{:04d}{:02d}{:02d}".format(t[0], t[1], t[2])


def _time_key(t):
    return "{:02d}{:02d}".format(t[3], t[4])


def _fmt1(value):
    return "{:.1f}".format(value)


def _read_env_lines(path):
    limit = MAX_DAILY_LINES_IN_MEMORY if path == DAILY_FILE else MAX_SAMPLE_LINES_IN_MEMORY
    lines = []
    try:
        with open(path, "r") as f:
            while True:
                line = f.readline(MAX_ENV_LINE_CHARS + 1)
                if not line:
                    break
                if len(line) > MAX_ENV_LINE_CHARS:
                    while line and not line.endswith("\n"):
                        line = f.readline(MAX_ENV_LINE_CHARS + 1)
                    continue
                line = line.strip()
                if not line:
                    continue
                lines.append(line)
                if len(lines) > limit:
                    del lines[0]
            return lines
    except OSError:
        return []


class EnvManager:
    __slots__ = (
        "sample_interval_sec", "current_date", "last_sample_epoch",
        "last_temp", "last_hum",
        "today_t_min", "today_t_max", "today_t_sum",
        "today_h_min", "today_h_max", "today_h_sum",
        "today_count",
    )

    def __init__(self, sample_interval_min=DEFAULT_SAMPLE_INTERVAL_MIN):
        self.sample_interval_sec = max(60, int(sample_interval_min) * 60)
        self.current_date = None
        self.last_sample_epoch = None
        self.last_temp = None
        self.last_hum = None
        self._reset_today()

    def _reset_today(self):
        self.today_t_min = None
        self.today_t_max = None
        self.today_t_sum = 0.0
        self.today_h_min = None
        self.today_h_max = None
        self.today_h_sum = 0.0
        self.today_count = 0

    def update(self, local_time, hw):
        if local_time[0] < MIN_VALID_YEAR:
            return
        date = _date_key(local_time)
        now_epoch = time.mktime(local_time)

        if self.current_date is None:
            self._restore_day(date)
        elif date != self.current_date:
            self._rollover_day(date)

        if self.last_sample_epoch is not None:
            if now_epoch - self.last_sample_epoch < self.sample_interval_sec:
                return

        reading = hw.get_temperature_humidity()
        if reading is None:
            return
        temp, hum = reading
        self.last_temp = temp
        self.last_hum = hum
        self.last_sample_epoch = now_epoch
        self._record_sample(temp, hum)
        _append_line(EVENT_FILE, "{},{},{},{}".format(
            date, _time_key(local_time), _fmt1(temp), _fmt1(hum)
        ))

    def _record_sample(self, temp, hum):
        self.today_t_min = temp if self.today_t_min is None else min(self.today_t_min, temp)
        self.today_t_max = temp if self.today_t_max is None else max(self.today_t_max, temp)
        self.today_t_sum += temp
        self.today_h_min = hum if self.today_h_min is None else min(self.today_h_min, hum)
        self.today_h_max = hum if self.today_h_max is None else max(self.today_h_max, hum)
        self.today_h_sum += hum
        self.today_count += 1

    def _restore_day(self, date):
        self.current_date = date
        self._reset_today()
        last_epoch = None
        for line in iter_lines(EVENT_FILE):
            parts = line.split(",")
            if len(parts) < 4 or parts[0] != date:
                continue
            try:
                temp = float(parts[2])
                hum = float(parts[3])
            except ValueError:
                continue
            self._record_sample(temp, hum)
            self.last_temp = temp
            self.last_hum = hum
            last_epoch = self._line_epoch(parts[0], parts[1])
        if last_epoch is not None:
            self.last_sample_epoch = last_epoch

    def _line_epoch(self, date, hhmm):
        try:
            return time.mktime((
                int(date[0:4]), int(date[4:6]), int(date[6:8]),
                int(hhmm[0:2]), int(hhmm[2:4]), 0, 0, 0
            ))
        except Exception:
            return None

    def _rollover_day(self, new_date):
        if self.today_count > 0:
            summary = "{},{},{},{},{},{},{},{}".format(
                self.current_date,
                _fmt1(self.today_t_min), _fmt1(self.today_t_max),
                _fmt1(self.today_t_sum / self.today_count),
                _fmt1(self.today_h_min), _fmt1(self.today_h_max),
                _fmt1(self.today_h_sum / self.today_count),
                self.today_count,
            )
            _append_line(DAILY_FILE, summary)
        self._trim_retention(new_date)
        self.current_date = new_date
        self._reset_today()
        gc.collect()

    def _trim_retention(self, current_date):
        try:
            current_tuple = (
                int(current_date[0:4]), int(current_date[4:6]), int(current_date[6:8]),
                0, 0, 0, 0, 0
            )
            current_epoch = time.mktime(current_tuple)
            sample_min_epoch = current_epoch - (SAMPLE_RETENTION_DAYS - 1) * 86400
            daily_min_epoch = current_epoch - (DAILY_RETENTION_DAYS - 1) * 86400
            _trim_by_date(EVENT_FILE, _date_key(time.localtime(sample_min_epoch)))
            _trim_by_date(DAILY_FILE, _date_key(time.localtime(daily_min_epoch)))
        except Exception as e:
            print("EnvManager: retention trim failed. {}".format(e))

    def get_status(self):
        avg_t = self.today_t_sum / self.today_count if self.today_count else None
        avg_h = self.today_h_sum / self.today_count if self.today_count else None
        return {
            "temp": self.last_temp,
            "hum": self.last_hum,
            "current_date": self.current_date or "",
            "t_min": self.today_t_min,
            "t_max": self.today_t_max,
            "t_avg": avg_t,
            "h_min": self.today_h_min,
            "h_max": self.today_h_max,
            "h_avg": avg_h,
            "count": self.today_count,
            "now_epoch": int(self.last_sample_epoch) if self.last_sample_epoch is not None else 0,
        }

    def get_samples(self):
        return _read_env_lines(EVENT_FILE)

    def get_daily(self):
        return _read_env_lines(DAILY_FILE)
