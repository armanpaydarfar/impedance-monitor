#!/usr/bin/env bash
# impedance-monitor installer
# Activate any Python 3.10+ environment, then run this script from the repo root:
#   conda activate <your-env>   (or: source .venv/bin/activate, etc.)
#   ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Coloured output helpers
_ok()   { echo "[OK]   $*"; }
_warn() { echo "[WARN] $*"; }
_fail() { echo "[FAIL] $*" >&2; }
_info() { echo "       $*"; }

echo "=== impedance-monitor installer ==="
echo ""

ERRORS=0

# --------------------------------------------------------------------------
# 1. Python version check
# --------------------------------------------------------------------------
echo "--- Checking Python environment ---"
PYTHON_BIN="$(command -v python 2>/dev/null || true)"
if [ -z "$PYTHON_BIN" ]; then
    _fail "No Python interpreter found on PATH."
    _info ""
    _info "Activate or create a Python 3.10+ environment, then re-run:"
    _info "  conda activate <your-env>"
    _info "  ./install.sh"
    _info ""
    _info "To create a new environment:"
    _info "  conda create -n <your-env> python=3.12"
    _info "  conda activate <your-env>"
    _info "  ./install.sh"
    _info ""
    _info "Don't have conda? Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')"
PYTHON_MINOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')"

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
    _fail "Python 3.10+ required, found $PYTHON_VERSION at $PYTHON_BIN."
    _info ""
    _info "Activate or create a Python 3.10+ environment, then re-run:"
    _info "  conda create -n <your-env> python=3.12"
    _info "  conda activate <your-env>"
    _info "  ./install.sh"
    exit 1
fi

_ok "Python $PYTHON_VERSION ($PYTHON_BIN)"
CONDA_ENV="${CONDA_DEFAULT_ENV:-}"
[ -n "$CONDA_ENV" ] && _info "conda environment: $CONDA_ENV"
echo ""

# --------------------------------------------------------------------------
# 2. Locate libeego-SDK.so
# --------------------------------------------------------------------------
echo "--- Locating ANT Neuro SDK ---"
SDK_PATHS=(
    "${EEGO_SDK_PATH:-}"
    "/home/$(whoami)/opt/lsl-eego/libeego-SDK.so"
    "/opt/lsl-eego/libeego-SDK.so"
    "libeego-SDK.so"
)
SDK_FOUND=""
for p in "${SDK_PATHS[@]}"; do
    if [ -n "$p" ] && [ -f "$p" ]; then
        SDK_FOUND="$p"
        break
    fi
done

if [ -z "$SDK_FOUND" ]; then
    _warn "libeego-SDK.so not found in default locations:"
    for p in "${SDK_PATHS[@]}"; do
        [ -n "$p" ] && _info "  $p"
    done
    echo ""
    if [ -t 0 ]; then
        # Running interactively — ask the user
        read -rp "       Enter full path to libeego-SDK.so (or press Enter to abort): " USER_SDK_PATH
        # Accept a directory — look for the library inside it
        if [ -n "$USER_SDK_PATH" ] && [ -d "$USER_SDK_PATH" ]; then
            USER_SDK_PATH="${USER_SDK_PATH%/}/libeego-SDK.so"
        fi
        if [ -n "$USER_SDK_PATH" ] && [ -f "$USER_SDK_PATH" ]; then
            SDK_FOUND="$USER_SDK_PATH"
        else
            [ -n "$USER_SDK_PATH" ] && _fail "File not found: $USER_SDK_PATH"
            _info "The SDK is obtained from ANT Neuro or from a lab zip archive."
            _info "It is not distributed with this repository."
            exit 1
        fi
    else
        # Non-interactive (piped/CI) — fail with instructions
        _fail "Cannot prompt for SDK path in non-interactive mode."
        _info "Set EEGO_SDK_PATH before running:"
        _info "  export EEGO_SDK_PATH=/path/to/libeego-SDK.so"
        _info "  ./install.sh"
        exit 1
    fi
fi
_ok "SDK found: $SDK_FOUND"

# Persist the resolved SDK path so impedance-monitor can find it on future runs
# without requiring EEGO_SDK_PATH to be set in the shell environment.
CONFIG_DIR="$HOME/.config/impedance-monitor"
mkdir -p "$CONFIG_DIR"
echo "$SDK_FOUND" > "$CONFIG_DIR/sdk_path"
_ok "SDK path saved: $CONFIG_DIR/sdk_path"
echo ""

# --------------------------------------------------------------------------
# 3. Install udev rule (required for unprivileged USB access to the amplifier)
# --------------------------------------------------------------------------
echo "--- Installing udev rule ---"
RULE_SRC="$SCRIPT_DIR/90-eego.rules"
RULE_DEST="/etc/udev/rules.d/90-eego.rules"

if [ ! -f "$RULE_SRC" ]; then
    _fail "90-eego.rules not found in repo at $RULE_SRC"
    _info "The file should be present in the repository root."
    ERRORS=$((ERRORS + 1))
else
    if cmp -s "$RULE_SRC" "$RULE_DEST" 2>/dev/null; then
        _ok "udev rule already current: $RULE_DEST"
    else
        echo "       Installing udev rule (requires sudo)..."
        if sudo cp "$RULE_SRC" "$RULE_DEST"; then
            sudo udevadm control --reload-rules
            # Trigger USB subsystem so the rule applies to already-plugged devices
            sudo udevadm trigger --subsystem-match=usb
            _ok "udev rule installed: $RULE_DEST"
        else
            _fail "Could not install udev rule (sudo failed)."
            _info "To install manually:"
            _info "  sudo cp $RULE_SRC $RULE_DEST"
            _info "  sudo udevadm control --reload-rules"
            _info "  sudo udevadm trigger --subsystem-match=usb"
            ERRORS=$((ERRORS + 1))
        fi
    fi
fi
echo ""

# --------------------------------------------------------------------------
# 4. Install Python package and dependencies
#    pip install -e . resolves PySide6 from pyproject.toml
# --------------------------------------------------------------------------
echo "--- Installing Python package and dependencies ---"
if "$PYTHON_BIN" -m pip install -e "$SCRIPT_DIR"; then
    _ok "Python package installed"
else
    _fail "pip install failed. Check the output above."
    _info "Common causes:"
    _info "  - Wrong Python active — check 'which python' and ensure your environment is activated"
    _info "  - No internet access (required to download PySide6 if not already installed)"
    _info "  - PySide6 version conflict — try: pip install --upgrade PySide6"
    exit 1
fi
echo ""

# --------------------------------------------------------------------------
# 5. Verify the entry point is reachable
# --------------------------------------------------------------------------
echo "--- Verifying entry point ---"
ENTRY_POINT="$(command -v impedance-monitor 2>/dev/null || true)"
if [ -z "$ENTRY_POINT" ]; then
    _fail "impedance-monitor command not found after install."
    _info "The environment's bin directory may not be on PATH yet."
    _info "Try: hash -r  or open a new terminal, then run: impedance-monitor --check"
    ERRORS=$((ERRORS + 1))
else
    _ok "Entry point: $ENTRY_POINT"
fi
echo ""

# --------------------------------------------------------------------------
# 6. Run full setup check
# --------------------------------------------------------------------------
echo "--- Running setup verification ---"
if "$PYTHON_BIN" -m impedance_monitor.main --check; then
    echo ""
else
    _fail "Setup check reported failures (see above)."
    ERRORS=$((ERRORS + 1))
fi

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
if [ "$ERRORS" -eq 0 ]; then
    echo "=== Installation complete ==="
    echo ""
    echo "Run the tool with:"
    echo "  impedance-monitor --mode mock --cap ca209   # hardware-free test"
    echo "  impedance-monitor --mode live --cap ca209   # live acquisition"
else
    echo "=== Installation finished with $ERRORS error(s) — see [FAIL] lines above ==="
    exit 1
fi
