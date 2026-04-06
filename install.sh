#!/usr/bin/env bash
# impedance-monitor installer
# Run from the repo root with the target conda environment already active:
#   conda activate lsl
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
    _fail "python not found. Activate the conda environment first:"
    _info "  conda activate lsl"
    exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')"
PYTHON_MINOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')"

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]; }; then
    _fail "Python 3.12+ required, found $PYTHON_VERSION."
    _info "Activate the correct environment: conda activate lsl"
    exit 1
fi
_ok "Python $PYTHON_VERSION ($PYTHON_BIN)"

# Warn if not in the expected conda environment
CONDA_ENV="${CONDA_DEFAULT_ENV:-}"
if [ -z "$CONDA_ENV" ]; then
    _warn "No conda environment appears to be active. Expected: lsl"
    _info "Run: conda activate lsl"
elif [ "$CONDA_ENV" != "lsl" ]; then
    _warn "Active conda environment is '$CONDA_ENV', expected 'lsl'."
    _info "Run: conda activate lsl  (then re-run this script)"
    _info "Continuing anyway — if dependencies fail, activate the correct environment."
else
    _ok "conda environment: $CONDA_ENV"
fi
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
    _fail "libeego-SDK.so not found. Paths checked:"
    for p in "${SDK_PATHS[@]}"; do
        [ -n "$p" ] && _info "  $p"
    done
    _info ""
    _info "To fix: place libeego-SDK.so at one of the paths above, or set EEGO_SDK_PATH:"
    _info "  export EEGO_SDK_PATH=/path/to/libeego-SDK.so"
    _info "  ./install.sh"
    _info ""
    _info "The SDK is obtained from ANT Neuro or from a lab zip archive."
    _info "It is not distributed with this repository."
    exit 1
fi
_ok "SDK found: $SDK_FOUND"
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
# 4. Install Python package and all dependencies
#    pip install -e . resolves PySide6 and numpy from pyproject.toml
# --------------------------------------------------------------------------
echo "--- Installing Python package and dependencies ---"
if "$PYTHON_BIN" -m pip install -e "$SCRIPT_DIR"; then
    _ok "Python package installed"
else
    _fail "pip install failed. Check the output above."
    _info "Common causes:"
    _info "  - Wrong conda environment active (run: conda activate lsl)"
    _info "  - No internet access for downloading PySide6 / numpy"
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
    _info "The conda environment's bin directory may not be on PATH."
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
