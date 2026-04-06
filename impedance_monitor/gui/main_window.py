import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..cap_layouts import get_layout
from ..logging_session.session_log import SessionLog
from ..processing.thresholds import classify_all
from .head_widget import HeadWidget

logger = logging.getLogger(__name__)

_CAP_OPTIONS = [
    ("CA-209", "ca209"),
    ("CA-001", "ca001"),
    ("CA-200", "ca200"),
]
_MODE_OPTIONS = [("Live", "live"), ("Mock", "mock")]


class MainWindow(QMainWindow):
    """Main application window.

    Layout (top → bottom):
      - Config panel: mode, cap, poll interval (row 1); subject, log dir, Start (row 2)
      - HeadWidget (electrode topomap, central)
      - Status bar: connection status, battery, poll rate, last-updated timestamp,
        Save Snapshot, Quit

    All acquisition options are selectable in the GUI. CLI args pre-populate the
    fields but are not required — running with no args opens a fully usable window.
    """

    def __init__(self, default_log_dir: Path, args) -> None:
        super().__init__()
        self._args = args
        self._default_log_dir = default_log_dir
        self._backend = None
        self._session: SessionLog | None = None

        # Resolve initial selections from args (fall back to defaults)
        initial_mode = getattr(args, "mode", "live") or "live"
        initial_cap  = getattr(args, "cap",  "ca209") or "ca209"
        initial_poll = getattr(args, "poll_ms", 500) or 500

        self._cap_layout = get_layout(initial_cap)

        self.setMinimumSize(680, 760)
        self._update_title()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Config panel ────────────────────────────────────────────────
        config_frame = QFrame()
        config_frame.setFrameShape(QFrame.Shape.StyledPanel)
        config_layout = QVBoxLayout(config_frame)
        config_layout.setContentsMargins(8, 6, 8, 6)
        config_layout.setSpacing(4)

        # Row 1: mode, cap, poll interval
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("Mode:"))
        self._mode_combo = QComboBox()
        for label, key in _MODE_OPTIONS:
            self._mode_combo.addItem(label, userData=key)
        self._mode_combo.setCurrentIndex(
            next((i for i, (_, k) in enumerate(_MODE_OPTIONS) if k == initial_mode), 0)
        )
        row1.addWidget(self._mode_combo)

        row1.addSpacing(12)
        row1.addWidget(QLabel("Cap:"))
        self._cap_combo = QComboBox()
        for label, key in _CAP_OPTIONS:
            self._cap_combo.addItem(label, userData=key)
        self._cap_combo.setCurrentIndex(
            next((i for i, (_, k) in enumerate(_CAP_OPTIONS) if k == initial_cap), 0)
        )
        self._cap_combo.currentIndexChanged.connect(self._on_cap_changed)
        row1.addWidget(self._cap_combo)

        row1.addSpacing(12)
        row1.addWidget(QLabel("Poll interval (ms):"))
        self._poll_edit = QLineEdit(str(initial_poll))
        self._poll_edit.setMaximumWidth(60)
        self._poll_edit.setToolTip("Polling interval in milliseconds (default: 500)")
        row1.addWidget(self._poll_edit)
        row1.addStretch()
        config_layout.addLayout(row1)

        # Row 2: subject, log dir, Start button
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Subject:"))
        self._subject_field = QLineEdit(getattr(args, "subject", "") or "")
        self._subject_field.setPlaceholderText("(optional, e.g. PILOT007)")
        self._subject_field.setMinimumWidth(120)
        row2.addWidget(self._subject_field)

        row2.addWidget(QLabel("Log dir:"))
        self._logdir_field = QLineEdit(str(default_log_dir))
        self._logdir_field.setMinimumWidth(260)
        self._logdir_field.setToolTip(str(default_log_dir))
        row2.addWidget(self._logdir_field)

        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setMinimumWidth(90)
        self._start_btn.clicked.connect(self._start_session)
        row2.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setMinimumWidth(90)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_session)
        row2.addWidget(self._stop_btn)

        config_layout.addLayout(row2)
        root.addWidget(config_frame)

        # ── Head widget ──────────────────────────────────────────────────
        self._head_widget = HeadWidget(self._cap_layout)
        root.addWidget(self._head_widget, stretch=1)

        # ── Status bar ───────────────────────────────────────────────────
        status_bar = QHBoxLayout()
        status_bar.setSpacing(12)

        self._conn_label    = QLabel("Status: Not started")
        self._battery_label = QLabel("Battery: —")
        self._poll_label    = QLabel(f"Poll: {initial_poll} ms")
        self._updated_label = QLabel("Updated: —")

        for lbl in (self._conn_label, self._battery_label,
                    self._poll_label, self._updated_label):
            status_bar.addWidget(lbl)

        status_bar.addStretch()

        self._snapshot_btn = QPushButton("Save Snapshot")
        self._snapshot_btn.setEnabled(False)
        self._snapshot_btn.clicked.connect(self._save_snapshot)
        status_bar.addWidget(self._snapshot_btn)

        self._quit_btn = QPushButton("Quit")
        self._quit_btn.clicked.connect(self.close)
        status_bar.addWidget(self._quit_btn)

        root.addLayout(status_bar)

        # ── Poll timer (not started until _start_session) ────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    # Config callbacks (pre-start only)
    # ------------------------------------------------------------------

    def _on_cap_changed(self, index: int) -> None:
        cap_key = self._cap_combo.itemData(index)
        self._cap_layout = get_layout(cap_key)
        self._head_widget.set_layout(self._cap_layout)
        self._update_title()

    def _update_title(self) -> None:
        mode = self._mode_combo.currentText() if hasattr(self, "_mode_combo") else "Live"
        cap  = self._cap_layout.name
        self.setWindowTitle(f"Impedance Monitor — {cap} — {mode.upper()}")

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _start_session(self) -> None:
        """Validate config, create backend, create session, begin polling."""
        try:
            poll_ms = int(self._poll_edit.text())
            if poll_ms < 50:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Poll interval must be an integer ≥ 50 ms.")
            return

        mode    = self._mode_combo.currentData()
        cap_key = self._cap_combo.currentData()
        log_dir = Path(self._logdir_field.text().strip() or str(self._default_log_dir))

        # Create the backend for the selected mode
        if mode == "live":
            from ..acquisition.eego_sdk import EegoSDKBackend, resolve_sdk_path
            try:
                sdk_path = resolve_sdk_path(getattr(self._args, "sdk_path", None))
            except FileNotFoundError as exc:
                QMessageBox.critical(self, "SDK Not Found", str(exc))
                return
            self._backend = EegoSDKBackend(self._cap_layout, sdk_path)
        else:
            from ..acquisition.mock import MockBackend
            self._backend = MockBackend(self._cap_layout)

        # Create the session (adds file handler to root logger)
        self._session = SessionLog(log_dir)

        self._conn_label.setText("Status: Connecting…")
        try:
            self._backend.start()
        except RuntimeError as exc:
            self._conn_label.setText("Status: Error")
            self._session.close()
            self._session = None
            self._backend = None
            QMessageBox.critical(self, "Startup Error", str(exc))
            return

        # Lock all config fields while running
        self._mode_combo.setEnabled(False)
        self._cap_combo.setEnabled(False)
        self._subject_field.setReadOnly(True)
        self._logdir_field.setReadOnly(True)
        self._poll_edit.setReadOnly(True)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._snapshot_btn.setEnabled(True)

        self._conn_label.setText("Status: Connected")
        self._poll_label.setText(f"Poll: {poll_ms} ms")
        logger.info(
            "Acquisition started. Mode=%s Cap=%s Poll=%dms Log=%s",
            mode.upper(), self._cap_layout.name, poll_ms, log_dir,
        )

        self._timer.setInterval(poll_ms)
        self._timer.start()

    def _stop_session(self) -> None:
        """Stop acquisition and restore the config panel for a new session."""
        self._timer.stop()
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
        if self._session is not None:
            self._session.close()
            self._session = None

        # Restore config fields
        self._mode_combo.setEnabled(True)
        self._cap_combo.setEnabled(True)
        self._subject_field.setReadOnly(False)
        self._logdir_field.setReadOnly(False)
        self._poll_edit.setReadOnly(False)
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._snapshot_btn.setEnabled(False)

        self._conn_label.setText("Status: Stopped")
        self._battery_label.setText("Battery: —")
        self._updated_label.setText("Updated: —")
        self._head_widget.set_layout(self._cap_layout)  # clears stale readings
        logger.info("Acquisition stopped by user.")

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Read backend, classify, update display, log readings."""
        try:
            raw = self._backend.read()
        except Exception as exc:
            self._timer.stop()
            self._conn_label.setText("Status: Error")
            logger.exception("Amplifier error during poll")
            QMessageBox.critical(
                self,
                "Amplifier Connection Lost",
                f"Amplifier connection lost:\n{exc}\n\nClose and restart the tool.",
            )
            return

        if not raw:
            return

        classified = classify_all(raw)
        self._head_widget.update_readings(classified)

        if self._session:
            self._session.log_readings(classified)

        self._update_battery()
        self._updated_label.setText(
            "Updated: " + datetime.now().strftime("%H:%M:%S")
        )

    def _update_battery(self) -> None:
        state = self._backend.battery()
        if state is None:
            self._battery_label.setText("Battery: N/A")
        elif not state.is_powered:
            self._battery_label.setText("Battery: off")
        elif state.is_charging:
            self._battery_label.setText(f"Battery: {state.level}% (charging)")
        else:
            self._battery_label.setText(f"Battery: {state.level}%")

    def _save_snapshot(self) -> None:
        if self._session:
            self._session.save_snapshot(self._head_widget)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Shutdown in the correct order before accepting the close event."""
        self._timer.stop()
        if self._backend is not None:
            self._backend.stop()
        if self._session:
            self._session.close()
        event.accept()
