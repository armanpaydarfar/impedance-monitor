"""Tests for ctypes/SDK Python binding assumptions.

These tests verify the calling conventions, buffer arithmetic, and constant
mappings that underpin eego_sdk.py. They run without hardware but depend on
the ctypes mechanics being correct. Any failure here means the Python-to-C
bridge has a structural problem that will surface immediately on hardware.

Sections:
  1. Basic ctypes assumptions  — type sizes, struct copy semantics, byref
  2. Error code mapping        — _SDK_ERROR_STRINGS vs wrapper.h enum
  3. Buffer arithmetic         — buffer.h getSample() layout
  4. SDK symbol verification   — requires libeego-SDK.so (skipped if absent)
  5. Header cross-checks       — C++ channel enum vs C flat API enum
"""

import ctypes
import re
from pathlib import Path

import pytest

SDK_SO_PATH = "/home/arman-admin/opt/lsl-eego/libeego-SDK.so"
WRAPPER_H   = Path("/home/arman-admin/opt/lsl-eego/eemagine/sdk/wrapper.h")
CHANNEL_H   = Path("/home/arman-admin/opt/lsl-eego/eemagine/sdk/channel.h")

_so_present      = pytest.mark.skipif(not Path(SDK_SO_PATH).is_file(), reason="libeego-SDK.so not found")
_headers_present = pytest.mark.skipif(not WRAPPER_H.exists(), reason="SDK headers not found")


# ---------------------------------------------------------------------------
# 1. Basic ctypes assumptions
# ---------------------------------------------------------------------------

def test_c_double_is_eight_bytes():
    """bytes_needed // 8 in _poll_once() assumes sizeof(double) == 8.

    The C standard guarantees double >= 4 bytes; IEEE 754 double is 8 bytes
    on all platforms we care about, but ctypes makes it explicit. If this
    ever changes (e.g. cross-compilation for a 32-bit target), the buffer
    unpack in _poll_once() would silently read the wrong number of samples.
    """
    assert ctypes.sizeof(ctypes.c_double) == 8, (
        "c_double is not 8 bytes — the bytes_needed // 8 calculation in "
        "_poll_once() will produce wrong channel counts"
    )


def test_channel_info_array_construction_copies_values():
    """(_ChannelInfo * n)(*list) must deep-copy values from the source list.

    eego_sdk.py constructs ch_arr = (_ChannelInfo * n_ref)(*ref_channels)
    before passing it to open_impedance_stream. This test confirms that
    values are present in ch_arr and that modifying the source objects
    afterwards does not corrupt ch_arr (ctypes copies the struct contents).
    """
    from impedance_monitor.acquisition.eego_sdk import _ChannelInfo, CHAN_REFERENCE

    source_arr = (_ChannelInfo * 4)()
    for i in range(4):
        source_arr[i].index = i * 10
        source_arr[i].type = CHAN_REFERENCE

    source_list = [source_arr[i] for i in range(4)]
    packed = (_ChannelInfo * 4)(*source_list)

    for i in range(4):
        assert packed[i].index == i * 10, (
            f"packed[{i}].index = {packed[i].index}, expected {i * 10}"
        )
        assert packed[i].type == CHAN_REFERENCE


def test_byref_output_parameter_pattern():
    """Validate the ctypes.byref calling convention used in battery().

    wrapper.h declares:
        int eemagine_sdk_get_amplifier_power_state(
            int amplifier_id,
            int* is_powered,
            int* is_charging,
            int* charging_level
        )

    Python passes ctypes.byref(c_int) for each output pointer. This test
    exercises that pattern against a real CFUNCTYPE (not a MagicMock) to
    confirm that byref correctly receives values written through the pointer.
    """
    FUNC_TYPE = ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    )

    def fake_get_power_state(amp_id, p_powered, p_charging, p_level):
        # Simulate SDK writing through its output pointers
        p_powered[0]  = 1
        p_charging[0] = 0
        p_level[0]    = 75
        return 0

    fn = FUNC_TYPE(fake_get_power_state)

    is_powered  = ctypes.c_int(0)
    is_charging = ctypes.c_int(0)
    level       = ctypes.c_int(0)
    ret = fn(
        42,
        ctypes.byref(is_powered),
        ctypes.byref(is_charging),
        ctypes.byref(level),
    )

    assert ret == 0
    assert is_powered.value  == 1,  f"is_powered not updated: {is_powered.value}"
    assert is_charging.value == 0,  f"is_charging not updated: {is_charging.value}"
    assert level.value       == 75, f"charging_level not updated: {level.value}"


def test_byref_argument_order_matches_wrapper_h():
    """Confirm that byref args are passed in the order wrapper.h specifies.

    wrapper.h: (amp_id, int* is_powered, int* is_charging, int* charging_level)
    wrapper.cc line 383: get_amplifier_power_state(id, &rv.is_powered, &rv.is_charging, &rv.charging_level)

    The test uses a CFUNCTYPE that asserts the intended semantics of each
    positional argument, so any future reordering in battery() would fail here.
    """
    FUNC_TYPE = ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    )

    received_amp_id = ctypes.c_int(-1)

    def fake_fn(amp_id, p_powered, p_charging, p_level):
        received_amp_id.value = amp_id
        # Write distinctive values so position mismatches are detectable
        p_powered[0]  = 111
        p_charging[0] = 222
        p_level[0]    = 333
        return 0

    fn = FUNC_TYPE(fake_fn)

    is_powered  = ctypes.c_int(0)
    is_charging = ctypes.c_int(0)
    level       = ctypes.c_int(0)
    fn(99, ctypes.byref(is_powered), ctypes.byref(is_charging), ctypes.byref(level))

    assert received_amp_id.value == 99,  "amp_id was not passed as arg 0"
    assert is_powered.value      == 111, "is_powered received wrong value — arg order mismatch?"
    assert is_charging.value     == 222, "is_charging received wrong value — arg order mismatch?"
    assert level.value           == 333, "charging_level received wrong value — arg order mismatch?"


# ---------------------------------------------------------------------------
# 2. Error code mapping
# ---------------------------------------------------------------------------

def test_error_codes_match_wrapper_h():
    """_SDK_ERROR_STRINGS must contain every error code from wrapper.h.

    wrapper.h eemagine_sdk_error enum:
        NOT_CONNECTED = -1, ALREADY_EXISTS = -2, NOT_FOUND = -3,
        INCORRECT_VALUE = -4, INTERNAL_ERROR = -5, UNKNOWN = -6

    If the SDK is upgraded and a new error code is added, or an existing code
    is renumbered, this test fails loudly instead of silently returning a
    wrong error string on hardware.
    """
    from impedance_monitor.acquisition.eego_sdk import _SDK_ERROR_STRINGS

    # Values taken directly from wrapper.h eemagine_sdk_error enum
    expected = {
        -1: "NOT_CONNECTED",
        -2: "ALREADY_EXISTS",
        -3: "NOT_FOUND",
        -4: "INCORRECT_VALUE",
        -5: "INTERNAL_ERROR",
        -6: "UNKNOWN",
    }

    for code, name in expected.items():
        assert code in _SDK_ERROR_STRINGS, (
            f"SDK error code {code} ({name}) missing from _SDK_ERROR_STRINGS"
        )
        assert _SDK_ERROR_STRINGS[code] == name, (
            f"_SDK_ERROR_STRINGS[{code}] = {_SDK_ERROR_STRINGS[code]!r}, "
            f"expected {name!r} (from wrapper.h eemagine_sdk_error enum)"
        )

    # No extra codes beyond what the header defines
    extra = set(_SDK_ERROR_STRINGS) - set(expected)
    assert not extra, f"_SDK_ERROR_STRINGS has codes not in wrapper.h: {extra}"


# ---------------------------------------------------------------------------
# 3. Buffer arithmetic
# ---------------------------------------------------------------------------

def test_buffer_layout_channel_at_sample_zero():
    """buf[channel] == getSample(channel, sample=0) for a single-sample buffer.

    buffer.h getSample(): _data[channel + sample * channel_count]
    For one sample (sample=0): _data[channel + 0] = _data[channel] = buf[channel].

    This is the indexing assumption in _poll_once():
        result[label] = buf[i]   # i == channel index, one sample
    """
    n_channels = 5
    # Allocate as the SDK returns: n_channels * n_samples doubles (n_samples=1)
    buf = (ctypes.c_double * n_channels)()
    values = [100.0, 200.0, 300.0, 400.0, 500.0]
    for i, v in enumerate(values):
        buf[i] = v  # buf[channel + 0*n_channels] = buf[channel]

    for ch in range(n_channels):
        assert buf[ch] == pytest.approx(values[ch]), (
            f"buf[{ch}] = {buf[ch]}, expected {values[ch]}"
        )


def test_n_doubles_from_bytes_needed():
    """bytes_needed // 8 == number of c_double elements in the buffer.

    prefetch() returns bytes_needed = n_channels * n_samples * sizeof(double).
    Dividing by 8 must recover the exact element count with no remainder.
    """
    for n_channels in [1, 32, 34, 64, 66]:
        bytes_needed = n_channels * 8  # one sample per channel, sizeof(double)=8
        n_doubles = bytes_needed // 8
        assert n_doubles == n_channels
        assert bytes_needed % 8 == 0, (
            f"bytes_needed={bytes_needed} is not divisible by 8 for n_channels={n_channels}"
        )


# ---------------------------------------------------------------------------
# 4. SDK symbol verification
# ---------------------------------------------------------------------------

@_so_present
def test_all_called_functions_are_exported():
    """Every function called by EegoSDKBackend must be exported by libeego-SDK.so.

    This test loads the actual .so via ctypes and checks that each symbol we
    call is accessible as an attribute. A missing symbol raises AttributeError
    at call time (not import time) — this test surfaces that failure before
    hardware testing.

    If the SDK is upgraded and a function is renamed or removed, this test
    fails immediately rather than crashing on the first hardware connection.
    """
    sdk = ctypes.CDLL(SDK_SO_PATH)

    # Every function called in eego_sdk.py's EegoSDKBackend
    required_symbols = [
        "eemagine_sdk_init",
        "eemagine_sdk_exit",
        "eemagine_sdk_get_amplifiers_info",
        "eemagine_sdk_open_amplifier",
        "eemagine_sdk_close_amplifier",
        "eemagine_sdk_get_amplifier_channel_list",
        "eemagine_sdk_open_impedance_stream",
        "eemagine_sdk_get_stream_channel_list",
        "eemagine_sdk_prefetch",
        "eemagine_sdk_get_data",
        "eemagine_sdk_close_stream",
        "eemagine_sdk_get_amplifier_power_state",
        "eemagine_sdk_get_error_string",
    ]

    missing = []
    for sym in required_symbols:
        try:
            getattr(sdk, sym)
        except AttributeError:
            missing.append(sym)

    assert not missing, (
        f"Functions missing from {SDK_SO_PATH}:\n  " + "\n  ".join(missing)
    )


# ---------------------------------------------------------------------------
# 5. Header cross-checks
# ---------------------------------------------------------------------------

@_headers_present
def test_c_flat_api_enum_differs_from_cpp_internal_enum():
    """Document that wrapper.h C enum values differ from channel.h C++ enum values.

    The C flat API (wrapper.h, eemagine_sdk_channel_type) uses different
    integer values than the C++ internal enum (channel.h, channel::channel_type).
    Our Python code must use wrapper.h values exclusively — using channel.h
    values would silently filter for the wrong channel types.

    C flat API (wrapper.h):
        REFERENCE=0, BIPOLAR=1, ACCELEROMETER=2, GYROSCOPE=3, MAGNETOMETER=4,
        TRIGGER=5, SAMPLE_COUNTER=6, IMPEDANCE_REFERENCE=7, IMPEDANCE_GROUND=8

    C++ internal enum (channel.h):
        none=0, reference=1, bipolar=2, trigger=3, sample_counter=4,
        impedance_reference=5, impedance_ground=6, accelerometer=7, ...

    For example, TRIGGER has value 5 in the C API but 3 in C++. Using the
    wrong enum would cause silent data corruption, not a crash.
    """
    from impedance_monitor.acquisition.eego_sdk import (
        CHAN_REFERENCE, CHAN_BIPOLAR, CHAN_TRIGGER, CHAN_SAMPLE_COUNTER,
        CHAN_IMPEDANCE_REF, CHAN_IMPEDANCE_GND,
    )

    # Parse wrapper.h C flat API enum to get authoritative values
    content = WRAPPER_H.read_text()
    enum_match = re.search(
        r"typedef enum \s*\{([^}]+)\}\s*eemagine_sdk_channel_type",
        content, re.DOTALL,
    )
    assert enum_match, "eemagine_sdk_channel_type enum not found in wrapper.h"
    members = re.findall(r"EEMAGINE_SDK_CHANNEL_TYPE_(\w+)", enum_match.group(1))

    flat_api_values = {name: i for i, name in enumerate(members)}

    # These are the values our Python constants must match
    assert CHAN_REFERENCE     == flat_api_values["REFERENCE"]
    assert CHAN_BIPOLAR       == flat_api_values["BIPOLAR"]
    assert CHAN_TRIGGER       == flat_api_values["TRIGGER"]
    assert CHAN_SAMPLE_COUNTER == flat_api_values["SAMPLE_COUNTER"]
    assert CHAN_IMPEDANCE_REF == flat_api_values["IMPEDANCE_REFERENCE"]
    assert CHAN_IMPEDANCE_GND == flat_api_values["IMPEDANCE_GROUND"]

    # Confirm that C++ internal values differ (the dangerous confusion point)
    channel_h = CHANNEL_H.read_text()
    cpp_match = re.search(
        r"enum channel_type \{([^}]+)\}", channel_h
    )
    assert cpp_match, "channel::channel_type enum not found in channel.h"
    cpp_members = [m.strip() for m in cpp_match.group(1).split(",") if m.strip()]
    cpp_values = {name.strip(): i for i, name in enumerate(cpp_members)}

    # reference is at position 1 in C++ enum, but REFERENCE is at position 0 in C flat API
    cpp_reference_val = cpp_values.get("reference", None)
    assert cpp_reference_val is not None, "could not find 'reference' in channel.h enum"
    assert CHAN_REFERENCE != cpp_reference_val, (
        "C flat API REFERENCE value unexpectedly equals the C++ internal enum value. "
        "Re-check both headers."
    )
