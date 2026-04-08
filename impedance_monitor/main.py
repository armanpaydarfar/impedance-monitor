"""Entry point for impedance-monitor.

Usage:
    impedance-monitor [--mode {live,mock}] [--cap {ca209,ca001,ca200}]
                      [--sdk-path PATH] [--poll-ms INT]
                      [--subject SUBJECT_ID] [--data-dir PATH]
                      [--check]
"""

import argparse
import logging
import sys
from pathlib import Path


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="impedance-monitor",
        description="ANT Neuro electrode impedance monitor",
    )
    parser.add_argument(
        "--mode",
        choices=["live", "mock"],
        default="live",
        help="Acquisition mode (default: live)",
    )
    parser.add_argument(
        "--cap",
        choices=["ca209", "ca001", "ca200"],
        default="ca209",
        help="Cap layout (default: ca209)",
    )
    parser.add_argument(
        "--sdk-path",
        default=None,
        metavar="PATH",
        help="Explicit path to the SDK library (libeego-SDK.so on Linux, eego-SDK.dll on Windows)",
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=500,
        metavar="INT",
        help="Polling interval in ms (default: 500)",
    )
    parser.add_argument(
        "--subject",
        default=None,
        metavar="SUBJECT_ID",
        help="Subject ID for log directory (e.g. PILOT007)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Root data directory (e.g. /home/alice/eeg_data)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run setup verification and exit (no hardware connection opened)",
    )
    return parser.parse_args(argv)


def _resolve_log_dir(subject: str | None, data_dir: str | None) -> Path:
    """Determine the default log directory.

    Priority:
      1. Harmony config.py importable from sys.path → use its DATA_DIR / TRAINING_SUBJECT
      2. --data-dir and --subject both provided → {data_dir}/sub-{subject}/impedance_logs/
      3. Neither → ~/impedance_logs/
    """
    try:
        import config  # type: ignore[import]
        base = Path(config.DATA_DIR) / f"sub-{config.TRAINING_SUBJECT}" / "impedance_logs"
        return base
    except (ImportError, AttributeError):
        pass

    if data_dir and subject:
        return Path(data_dir) / f"sub-{subject}" / "impedance_logs"

    return Path.home() / "impedance_logs"


def _run_check(sdk_path_arg: str | None) -> int:
    """Run setup verification. Returns exit code (0 = all pass, 1 = any fail)."""
    import ctypes

    all_ok = True

    def _ok(label: str, detail: str) -> None:
        print(f"[OK]   {label:<16} {detail}")

    def _fail(label: str, detail: str) -> None:
        nonlocal all_ok
        all_ok = False
        print(f"[FAIL] {label:<16} {detail}")

    # SDK resolvable
    try:
        from .acquisition.eego_sdk import resolve_sdk_path
        sdk_path = resolve_sdk_path(sdk_path_arg)
        _ok("SDK found:", sdk_path)
    except FileNotFoundError as exc:
        _fail("SDK found:", str(exc))
        sdk_path = None

    # SDK loadable
    if sdk_path:
        try:
            ctypes.CDLL(sdk_path)
            _ok("SDK loadable:", sdk_path)
        except OSError as exc:
            _fail("SDK loadable:", str(exc))

    # udev rule (Linux only — not applicable on Windows)
    if sys.platform != "win32":
        udev_path = Path("/etc/udev/rules.d/90-eego.rules")
        if udev_path.exists():
            _ok("udev rule:", str(udev_path))
        else:
            _fail("udev rule:", f"{udev_path} not found — run install.py or copy 90-eego.rules manually")

    # PySide6
    try:
        import PySide6
        _ok("PySide6:", PySide6.__version__)
    except ImportError:
        _fail("PySide6:", "not importable — run: pip install PySide6")

    if all_ok:
        print("\nAll checks passed. Run: impedance-monitor --mode live")
    else:
        print("\nSome checks failed. Resolve the issues above before running live mode.")

    return 0 if all_ok else 1


def main(argv=None) -> None:
    args = _parse_args(argv)

    if args.check:
        sys.exit(_run_check(args.sdk_path))

    # Validate --subject / --data-dir pairing
    if bool(args.subject) != bool(args.data_dir):
        print(
            "error: --subject and --data-dir must be provided together or not at all.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Configure stdout logging early so terminal output is available immediately.
    # The SessionLog will add a file handler when the user clicks Start.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

    default_log_dir = _resolve_log_dir(args.subject, args.data_dir)

    from PySide6.QtWidgets import QApplication
    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)

    # Backend and cap layout are created inside MainWindow on Start click,
    # based on the GUI selections. CLI args pre-populate the GUI fields only.
    window = MainWindow(default_log_dir, args)
    window.show()

    sys.exit(app.exec())
