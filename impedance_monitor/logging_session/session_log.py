import logging
import time
from datetime import datetime
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# Minimum seconds between per-reading log entries regardless of poll rate
_READINGS_LOG_INTERVAL_S = 1.0


class SessionLog:
    """Manages the text event log for one session.

    A single .log file is written per session, mirroring everything that appears
    on the terminal (timestamps, INFO/WARNING/ERROR level, message text). Impedance
    readings are logged at most once per second regardless of the polling rate, so
    the file is usable as a time-stamped record of how impedances evolved during
    cap setup.

    The file handler is added to the root logger on construction and removed on
    close(), so all logging calls throughout the application automatically write
    to the session file while a session is active.
    """

    def __init__(self, log_dir: Path) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir = log_dir
        self._last_readings_log: float = 0.0  # monotonic time of last readings entry

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = log_dir / f"impedance_monitor_{timestamp}.log"

        self._file_handler = logging.FileHandler(str(log_filename), mode="w")
        self._file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logging.getLogger().addHandler(self._file_handler)

        logging.info("Session started. Log: %s", log_filename)

    def log_readings(self, readings: dict) -> None:
        """Log a one-line impedance summary at most once per second.

        Format:
            Readings: FP1=4.2K FPz=3.1K ... GND=open REF=2.1K  [28G 2M 0B 2O]

        The throttle ensures the log file stays readable even at high poll rates.
        """
        now = time.monotonic()
        if now - self._last_readings_log < _READINGS_LOG_INTERVAL_S:
            return
        self._last_readings_log = now

        from ..processing.thresholds import Status

        counts = {s: 0 for s in Status}
        parts = []
        for label, reading in readings.items():
            counts[reading.status] += 1
            if reading.status == Status.OPEN:
                parts.append(f"{label}=open")
            else:
                val = f"{reading.kohm:.1f}K"
                parts.append(f"{label}={val}")

        summary = (
            f"[{counts[Status.GOOD]}G "
            f"{counts[Status.MARGINAL]}M "
            f"{counts[Status.BAD]}B "
            f"{counts[Status.OPEN]}O "
            f"{counts[Status.DRY]}D]"
        )
        logging.info("Readings: %s  %s", " ".join(parts), summary)

    def save_snapshot(self, widget) -> Path:
        """Capture widget as PNG, write to log_dir, log the path. Return path."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self._log_dir / f"impedance_snapshot_{timestamp}.png"
        widget.grab().save(str(path))
        logging.info("Snapshot saved: %s", path)
        return path

    def close(self) -> None:
        """Remove the file handler and log session end."""
        logging.info("Session ended.")
        logging.getLogger().removeHandler(self._file_handler)
        self._file_handler.flush()
        self._file_handler.close()
