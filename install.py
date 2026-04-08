#!/usr/bin/env python3
"""impedance-monitor installer — Linux and Windows.

Activate a Python 3.10+ environment, then run from the repo root:

    python install.py

On Linux this also installs the udev rule for unprivileged USB access (requires sudo).
On Windows the ANT Neuro USB driver must be installed separately.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.resolve()
SDK_LIB  = "eego-SDK.dll" if sys.platform == "win32" else "libeego-SDK.so"

ERRORS = 0


def _ok(label: str, detail: str = "") -> None:
    print(f"[OK]   {label:<16} {detail}".rstrip())


def _warn(label: str, detail: str = "") -> None:
    print(f"[WARN] {label:<16} {detail}".rstrip())


def _fail(label: str, detail: str = "") -> None:
    global ERRORS
    ERRORS += 1
    print(f"[FAIL] {label:<16} {detail}".rstrip(), file=sys.stderr)


def _info(msg: str) -> None:
    print(f"       {msg}")


# --------------------------------------------------------------------------
# 1. Python version
# --------------------------------------------------------------------------
def check_python() -> None:
    print("--- Checking Python environment ---")
    major, minor = sys.version_info.major, sys.version_info.minor
    if major < 3 or (major == 3 and minor < 10):
        _fail("Python:", f"{major}.{minor} found — 3.10+ required")
        _info("Create a suitable environment and re-run:")
        _info("  conda create -n <env> python=3.12")
        _info("  conda activate <env>")
        _info("  python install.py")
        sys.exit(1)
    env_name = os.environ.get("CONDA_DEFAULT_ENV", "")
    detail = f"{major}.{minor}  (conda: {env_name})" if env_name else f"{major}.{minor}"
    _ok("Python:", detail)
    print()


# --------------------------------------------------------------------------
# 2. Locate SDK
# --------------------------------------------------------------------------
def _sdk_candidates() -> list[str]:
    candidates: list[str] = []

    env_path = os.environ.get("EEGO_SDK_PATH", "")
    if env_path:
        candidates.append(env_path)

    if sys.platform == "win32":
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(str(Path(user_profile) / "opt" / "lsl-eego" / SDK_LIB))
    else:
        user = os.environ.get("USER", "")
        if user:
            candidates.append(f"/home/{user}/opt/lsl-eego/{SDK_LIB}")
        candidates.append(f"/opt/lsl-eego/{SDK_LIB}")

    return candidates


def check_sdk() -> None:
    print("--- Locating ANT Neuro SDK ---")
    candidates = _sdk_candidates()

    for p in candidates:
        if Path(p).is_file():
            _ok("SDK found:", p)
            print()
            return

    _fail("SDK:", f"{SDK_LIB} not found")
    _info("Paths checked:")
    for p in candidates:
        _info(f"  {p}")
    _info("")
    _info(f"Obtain {SDK_LIB} from ANT Neuro, then either:")
    _info(f"  - Place it at one of the paths above, or")
    _info(f"  - Set EEGO_SDK_PATH=/path/to/{SDK_LIB} and re-run")
    sys.exit(1)


# --------------------------------------------------------------------------
# 3. udev rule (Linux only)
# --------------------------------------------------------------------------
def install_udev_rule() -> None:
    print("--- Installing udev rule ---")
    rule_src  = REPO_DIR / "90-eego.rules"
    rule_dest = Path("/etc/udev/rules.d/90-eego.rules")

    if not rule_src.exists():
        _fail("udev rule:", f"90-eego.rules not found in repo at {rule_src}")
        print()
        return

    import filecmp
    if rule_dest.exists() and filecmp.cmp(str(rule_src), str(rule_dest), shallow=False):
        _ok("udev rule:", f"already current at {rule_dest}")
        print()
        return

    print("       Installing udev rule (requires sudo)...")
    r1 = subprocess.run(["sudo", "cp", str(rule_src), str(rule_dest)])
    if r1.returncode != 0:
        _fail("udev rule:", "sudo cp failed")
        _info(f"To install manually:")
        _info(f"  sudo cp {rule_src} {rule_dest}")
        _info(f"  sudo udevadm control --reload-rules")
        _info(f"  sudo udevadm trigger --subsystem-match=usb")
        print()
        return

    subprocess.run(["sudo", "udevadm", "control", "--reload-rules"])
    subprocess.run(["sudo", "udevadm", "trigger", "--subsystem-match=usb"])
    _ok("udev rule:", str(rule_dest))
    print()


# --------------------------------------------------------------------------
# 4. pip install
# --------------------------------------------------------------------------
def pip_install() -> None:
    print("--- Installing Python package and dependencies ---")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(REPO_DIR)],
    )
    if result.returncode != 0:
        _fail("pip install:", "failed — see output above")
        _info("Common causes:")
        _info("  - Wrong Python active — check that your environment is activated")
        _info("  - No internet access (required to download PySide6 if not cached)")
        sys.exit(1)
    _ok("Package:", "installed")
    print()


# --------------------------------------------------------------------------
# 5. Verify entry point
# --------------------------------------------------------------------------
def check_entry_point() -> None:
    print("--- Verifying entry point ---")
    import shutil
    if shutil.which("impedance-monitor"):
        _ok("Entry point:", "impedance-monitor")
    else:
        _warn("Entry point:", "impedance-monitor not on PATH yet")
        _info("Try opening a new terminal, or run directly with:")
        _info(f"  {sys.executable} -m impedance_monitor.main")
    print()


# --------------------------------------------------------------------------
# 6. --check verification
# --------------------------------------------------------------------------
def run_check() -> None:
    print("--- Running setup verification ---")
    result = subprocess.run(
        [sys.executable, "-m", "impedance_monitor.main", "--check"],
        cwd=REPO_DIR,
    )
    if result.returncode != 0:
        _fail("--check:", "reported failures (see above)")
    print()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    print("=== impedance-monitor installer ===")
    print()

    check_python()
    check_sdk()

    if sys.platform != "win32":
        install_udev_rule()

    pip_install()
    check_entry_point()
    run_check()

    if ERRORS == 0:
        print("=== Installation complete ===")
        print()
        print("Run the tool with:")
        print("  impedance-monitor --mode mock --cap ca209   # hardware-free test")
        print("  impedance-monitor --mode live --cap ca209   # live acquisition")
    else:
        print(f"=== Installation finished with {ERRORS} error(s) — see [FAIL] lines above ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
