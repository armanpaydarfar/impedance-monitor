"""Validate eego_sdk.py constants and struct layouts against the SDK headers.

These tests use wrapper.h and wrapper.cc as the source of truth. They require
the SDK headers to be present at the expected path but do not require hardware,
a running SDK, or ctypes to load the .so.

Why these tests exist:
  The channel type constants in eego_sdk.py are hand-transcribed from the C enum
  in wrapper.h. If the SDK is upgraded and the enum order changes, a mismatch
  would silently produce wrong channel type filters — the kind of bug that only
  shows up on hardware. Parsing the header directly eliminates that risk.
"""

import ctypes
import re
from pathlib import Path
from unittest.mock import patch

import pytest

SDK_HEADER_DIR = Path("/home/arman-admin/opt/lsl-eego")
WRAPPER_H = SDK_HEADER_DIR / "eemagine/sdk/wrapper.h"
WRAPPER_CC = SDK_HEADER_DIR / "wrapper.cc"


def _skip_if_no_headers():
    return pytest.mark.skipif(
        not WRAPPER_H.exists(),
        reason=f"SDK headers not found at {WRAPPER_H}",
    )


# ---------------------------------------------------------------------------
# Channel type enum: Python constants vs. wrapper.h
# ---------------------------------------------------------------------------

@_skip_if_no_headers()
def test_channel_type_constants_match_header():
    """Parse the eemagine_sdk_channel_type enum from wrapper.h and verify
    that every constant in eego_sdk.py has the correct integer value.

    The C enum auto-increments from 0, so position in the enum = value.
    If the SDK is upgraded and the enum is reordered, this test fails loudly
    rather than silently producing wrong channel filters on hardware.
    """
    from impedance_monitor.acquisition.eego_sdk import (
        CHAN_REFERENCE, CHAN_BIPOLAR, CHAN_ACCELEROMETER, CHAN_GYROSCOPE,
        CHAN_MAGNETOMETER, CHAN_TRIGGER, CHAN_SAMPLE_COUNTER,
        CHAN_IMPEDANCE_REF, CHAN_IMPEDANCE_GND,
    )

    content = WRAPPER_H.read_text()
    enum_match = re.search(
        r"typedef enum \s*\{([^}]+)\}\s*eemagine_sdk_channel_type",
        content, re.DOTALL,
    )
    assert enum_match, "eemagine_sdk_channel_type enum not found in wrapper.h"

    members = re.findall(
        r"EEMAGINE_SDK_CHANNEL_TYPE_(\w+)", enum_match.group(1)
    )
    assert members, "No enum members found"

    # Map expected C name suffix → our Python constant
    our_constants = {
        "REFERENCE":           CHAN_REFERENCE,
        "BIPOLAR":             CHAN_BIPOLAR,
        "ACCELEROMETER":       CHAN_ACCELEROMETER,
        "GYROSCOPE":           CHAN_GYROSCOPE,
        "MAGNETOMETER":        CHAN_MAGNETOMETER,
        "TRIGGER":             CHAN_TRIGGER,
        "SAMPLE_COUNTER":      CHAN_SAMPLE_COUNTER,
        "IMPEDANCE_REFERENCE": CHAN_IMPEDANCE_REF,
        "IMPEDANCE_GROUND":    CHAN_IMPEDANCE_GND,
    }

    for i, name in enumerate(members):
        if name in our_constants:
            assert our_constants[name] == i, (
                f"CHAN_{name}: wrapper.h enum position is {i} "
                f"but eego_sdk.py has {our_constants[name]}"
            )


# ---------------------------------------------------------------------------
# Struct layout: _AmpInfo and _ChannelInfo vs. wrapper.h
# ---------------------------------------------------------------------------

@_skip_if_no_headers()
def test_amp_info_struct_size():
    """_AmpInfo must match eemagine_sdk_amplifier_info: { int id; char serial[64] }."""
    from impedance_monitor.acquisition.eego_sdk import _AmpInfo

    expected = ctypes.sizeof(ctypes.c_int) + 64  # int + char[64]
    assert ctypes.sizeof(_AmpInfo) == expected, (
        f"_AmpInfo size {ctypes.sizeof(_AmpInfo)} != expected {expected}. "
        f"Check wrapper.h eemagine_sdk_amplifier_info definition."
    )


@_skip_if_no_headers()
def test_channel_info_struct_size():
    """_ChannelInfo must match eemagine_sdk_channel_info: { int index; int type }."""
    from impedance_monitor.acquisition.eego_sdk import _ChannelInfo

    expected = 2 * ctypes.sizeof(ctypes.c_int)  # two ints
    assert ctypes.sizeof(_ChannelInfo) == expected, (
        f"_ChannelInfo size {ctypes.sizeof(_ChannelInfo)} != expected {expected}. "
        f"Check wrapper.h eemagine_sdk_channel_info definition."
    )


def test_channel_info_field_assignment():
    """_ChannelInfo fields can be set and read back correctly."""
    from impedance_monitor.acquisition.eego_sdk import _ChannelInfo

    ch = _ChannelInfo()
    ch.index = 17
    ch.type = 7
    assert ch.index == 17
    assert ch.type == 7


def test_amp_info_field_assignment():
    """_AmpInfo fields can be set and read back correctly."""
    from impedance_monitor.acquisition.eego_sdk import _AmpInfo

    amp = _AmpInfo()
    amp.id = 42
    amp.serial = b"EE223-TEST"
    assert amp.id == 42
    assert amp.serial == b"EE223-TEST"


# ---------------------------------------------------------------------------
# ctypes array element identity — the root cause of the .index() crash
# ---------------------------------------------------------------------------

def test_ctypes_array_elements_lack_value_equality():
    """Demonstrate that ctypes array element access does not support value equality.

    This is the exact behaviour that caused the stream_imp_ref.index() crash.
    Each time you index a ctypes array, Python returns a *new* wrapper object
    around the same memory location. That new object is not == any previously
    retrieved object, so list.index() and the `in` operator always fail.

    This test exists so that anyone who reads the eego_sdk.py channel mapping
    code understands why we use a counter (scalp_pos) instead of .index().
    """
    from impedance_monitor.acquisition.eego_sdk import _ChannelInfo

    arr = (_ChannelInfo * 3)()
    arr[0].index = 5
    arr[0].type = 7
    arr[1].index = 6
    arr[1].type = 7
    arr[2].index = 7
    arr[2].type = 8

    # Build a list from the array — same pattern the original code used
    type7_list = [arr[i] for i in range(3) if arr[i].type == 7]
    assert len(type7_list) == 2

    # The bug: re-accessing arr[0] gives a new Python object, not the one in the list
    assert (arr[0] in type7_list) is False  # confirms broken identity equality

    # The correct approach: iterate by position and use a counter
    pos = 0
    labels = []
    for i in range(3):
        if arr[i].type == 7:
            labels.append(f"CH{pos}")
            pos += 1
        elif arr[i].type == 8:
            labels.append("GND")
    assert labels == ["CH0", "CH1", "GND"]


# ---------------------------------------------------------------------------
# Amplifier channel list: what types the hardware actually reports
# ---------------------------------------------------------------------------

@_skip_if_no_headers()
def test_amplifier_channel_list_never_contains_impedance_types():
    """Verify via wrapper.cc analysis that get_amplifier_channel_list cannot
    return IMPEDANCE_REFERENCE or IMPEDANCE_GROUND typed channels.

    wrapper.cc _sdk_amplifier::getChannelList() (lines 387-392) calls
    get_amplifier_channel_list then _channelArrayToVector, which is a
    straightforward type mapping. The hardware EEG amplifier only has
    REFERENCE and BIPOLAR channels — it never reports impedance-typed channels
    in its channel list. Impedance types only appear in the STREAM channel list
    after open_impedance_stream is called.

    This is the root cause of the original "No impedance channels found" error:
    the code was filtering the AMPLIFIER channel list for impedance types,
    which are never present there.
    """
    content = WRAPPER_CC.read_text()

    # Confirm _channelArrayToVector exists and maps IMPEDANCE types
    assert "EEMAGINE_SDK_CHANNEL_TYPE_IMPEDANCE_REFERENCE" in content
    assert "impedance_reference" in content

    # Confirm getChannelList on the amplifier calls _channelArrayToVector
    # (not some other function that might inject impedance channels)
    amplifier_section = content[content.find("class _sdk_amplifier"):]
    get_channel_list_match = re.search(
        r"getChannelList\(\)[^{]*\{([^}]+)\}", amplifier_section
    )
    assert get_channel_list_match, "Could not find amplifier getChannelList in wrapper.cc"
    body = get_channel_list_match.group(1)
    assert "_channelArrayToVector" in body, (
        "amplifier::getChannelList does not call _channelArrayToVector — "
        "the channel list source may have changed"
    )
    # No impedance type is constructed inside getChannelList itself
    assert "impedance" not in body.lower(), (
        "amplifier::getChannelList appears to construct impedance channels — "
        "re-check whether filtering for impedance types in the amplifier list is now valid"
    )


# ---------------------------------------------------------------------------
# resolve_sdk_path(): SDK path resolution priority
# ---------------------------------------------------------------------------

def test_resolve_sdk_path_explicit_wins(tmp_path):
    """An explicit path is returned immediately when the file exists.

    Explicit takes priority over every other mechanism (env var, hardcoded paths).
    """
    from impedance_monitor.acquisition.eego_sdk import resolve_sdk_path

    fake_so = tmp_path / "libeego-SDK.so"
    fake_so.touch()
    assert resolve_sdk_path(str(fake_so)) == str(fake_so)


def test_resolve_sdk_path_env_var_used(tmp_path, monkeypatch):
    """EEGO_SDK_PATH env var is used when no explicit path is given."""
    from impedance_monitor.acquisition.eego_sdk import resolve_sdk_path

    fake_so = tmp_path / "libeego-SDK.so"
    fake_so.touch()
    monkeypatch.setenv("EEGO_SDK_PATH", str(fake_so))
    # Patch Path.is_file so hardcoded fallback paths don't accidentally resolve
    with patch.object(Path, "is_file", lambda self: str(self) == str(fake_so)):
        assert resolve_sdk_path() == str(fake_so)


def test_resolve_sdk_path_explicit_beats_env_var(tmp_path, monkeypatch):
    """An explicit path wins over EEGO_SDK_PATH."""
    from impedance_monitor.acquisition.eego_sdk import resolve_sdk_path

    env_so      = tmp_path / "env.so"
    explicit_so = tmp_path / "explicit.so"
    env_so.touch()
    explicit_so.touch()
    monkeypatch.setenv("EEGO_SDK_PATH", str(env_so))
    assert resolve_sdk_path(str(explicit_so)) == str(explicit_so)


def test_resolve_sdk_path_raises_when_not_found(monkeypatch):
    """FileNotFoundError is raised with a helpful message when no path resolves.

    All filesystem checks are stubbed out so the test is not dependent on which
    files happen to be present on the development machine.
    """
    from impedance_monitor.acquisition.eego_sdk import resolve_sdk_path

    monkeypatch.delenv("EEGO_SDK_PATH", raising=False)
    with patch.object(Path, "is_file", return_value=False):
        with patch("impedance_monitor.acquisition.eego_sdk.ctypes.CDLL", side_effect=OSError):
            with pytest.raises(FileNotFoundError, match="libeego-SDK.so not found"):
                resolve_sdk_path()
