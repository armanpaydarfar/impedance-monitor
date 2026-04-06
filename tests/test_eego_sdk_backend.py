"""Mock-based tests for EegoSDKBackend logic.

These tests patch ctypes.CDLL so that EegoSDKBackend.start() and read() run
against a fake SDK that returns realistic channel lists. No hardware, no .so
file, and no live amplifier are required.

Why these tests exist:
  eego_sdk.py contains non-trivial logic: channel type filtering, label mapping,
  buffer unpacking, and error handling. The bugs encountered during initial
  hardware testing were all in this logic layer, not in the hardware itself.
  A mock-based suite catches regressions in that logic without needing the
  physical device to be connected.

Fake SDK behaviour modelled on:
  - wrapper.h: function signatures and channel type enum
  - wrapper.cc: _sdk_amplifier::getChannelList (lines 387-392),
                _sdk_stream::getChannelList (lines 341-347),
                observed hardware output: 32 REF + 24 BIP amplifier channels,
                32 REF + 1 IMPEDANCE_REF + 1 IMPEDANCE_GND stream channels
"""

import ctypes
from unittest.mock import MagicMock, patch

import pytest

from impedance_monitor.acquisition.eego_sdk import (
    CHAN_BIPOLAR,
    CHAN_IMPEDANCE_GND,
    CHAN_IMPEDANCE_REF,
    CHAN_REFERENCE,
    EegoSDKBackend,
    _AmpInfo,
    _ChannelInfo,
)
from impedance_monitor.cap_layouts import get_layout

# ---------------------------------------------------------------------------
# Helpers: build realistic fake SDK side-effects
# ---------------------------------------------------------------------------

N_REF = 32   # reference (EEG) channels — matches CA-209 + hardware REF
N_BIP = 24   # bipolar channels on EE-225


def _make_fake_sdk(
    n_ref: int = N_REF,
    n_bip: int = N_BIP,
    amp_id: int = 0,
    stream_id: int = 0,
    impedance_values: list[float] | None = None,
) -> MagicMock:
    """Return a MagicMock that behaves like the ctypes SDK handle.

    The fake SDK returns:
      - Amplifier channel list: n_ref REFERENCE + n_bip BIPOLAR channels
      - Stream channel list:    n_ref REFERENCE + 1 IMPEDANCE_REF + 1 IMPEDANCE_GND
      - getData buffer:         impedance_values (defaults to 1000 * position)

    This mirrors the actual hardware output observed during testing.
    """
    n_stream = n_ref + 2  # +1 IMPEDANCE_REF, +1 IMPEDANCE_GND

    if impedance_values is None:
        impedance_values = [float(i * 1000) for i in range(n_stream)]

    def fake_get_amplifiers_info(arr, size):
        arr[0].id = amp_id
        arr[0].serial = b"EE223-TEST-MOCK"
        return 1

    def fake_get_amplifier_channel_list(aid, arr, size):
        for i in range(n_ref):
            arr[i].index = i
            arr[i].type = CHAN_REFERENCE
        for i in range(n_bip):
            arr[n_ref + i].index = n_ref + i
            arr[n_ref + i].type = CHAN_BIPOLAR
        return n_ref + n_bip

    def fake_open_impedance_stream(aid, channels, count):
        return stream_id

    def fake_get_stream_channel_list(sid, arr, size):
        # Per-electrode channels echo back as REFERENCE type (observed hardware behaviour)
        for i in range(n_ref):
            arr[i].index = i
            arr[i].type = CHAN_REFERENCE
        # Hardware REF and GND electrodes appended at the end
        arr[n_ref].index = n_ref
        arr[n_ref].type = CHAN_IMPEDANCE_REF
        arr[n_ref + 1].index = n_ref + 1
        arr[n_ref + 1].type = CHAN_IMPEDANCE_GND
        return n_stream

    def fake_prefetch(sid):
        return n_stream * 8  # bytes for n_stream doubles

    def fake_get_data(sid, buf, size):
        for i, v in enumerate(impedance_values[:n_stream]):
            buf[i] = v
        return n_stream * 8

    sdk = MagicMock()
    sdk.eemagine_sdk_get_amplifiers_info.side_effect = fake_get_amplifiers_info
    sdk.eemagine_sdk_open_amplifier.return_value = 0
    sdk.eemagine_sdk_get_amplifier_channel_list.side_effect = fake_get_amplifier_channel_list
    sdk.eemagine_sdk_open_impedance_stream.side_effect = fake_open_impedance_stream
    sdk.eemagine_sdk_get_stream_channel_list.side_effect = fake_get_stream_channel_list
    sdk.eemagine_sdk_prefetch.side_effect = fake_prefetch
    sdk.eemagine_sdk_get_data.side_effect = fake_get_data
    sdk.eemagine_sdk_close_stream.return_value = 0
    sdk.eemagine_sdk_close_amplifier.return_value = 0
    return sdk


def _make_backend(cap="ca209", sdk=None, sdk_path="/fake/libeego-SDK.so"):
    layout = get_layout(cap)
    if sdk is None:
        sdk = _make_fake_sdk()
    with patch("ctypes.CDLL", return_value=sdk):
        backend = EegoSDKBackend(layout, sdk_path)
        backend.start()
    return backend, sdk


# ---------------------------------------------------------------------------
# start(): channel label mapping
# ---------------------------------------------------------------------------

class TestStartChannelMapping:
    def test_scalp_electrodes_mapped_in_cap_order(self):
        """The 32 REFERENCE-type stream channels map positionally to cap electrodes."""
        backend, _ = _make_backend()
        layout = get_layout("ca209")
        scalp = [e.label for e in layout.electrodes if not e.is_ground and not e.is_ref]
        assert backend._channel_labels[:32] == scalp

    def test_impedance_gnd_maps_to_gnd_label(self):
        """The IMPEDANCE_GROUND channel maps to the layout's GND electrode."""
        backend, _ = _make_backend()
        assert "GND" in backend._channel_labels

    def test_impedance_ref_electrode_labelled_ref(self):
        """The hardware REF electrode (IMPEDANCE_REF type) is labelled 'REF'."""
        backend, _ = _make_backend()
        assert "REF" in backend._channel_labels

    def test_total_channel_count(self):
        """Label list length equals stream channel count (32 + 1 REF + 1 GND = 34)."""
        backend, _ = _make_backend()
        assert len(backend._channel_labels) == 34

    def test_no_raw_labels_in_normal_stream(self):
        """No RAWn labels should appear when the stream has the expected channel types."""
        backend, _ = _make_backend()
        assert not any(l.startswith("RAW") for l in backend._channel_labels)

    def test_ca200_mapping_uses_64_scalp_electrodes(self):
        """CA-200 maps all 64 scalp electrodes correctly."""
        layout = get_layout("ca200")
        sdk = _make_fake_sdk(n_ref=64)
        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            backend.start()
        scalp = [e.label for e in layout.electrodes if not e.is_ground and not e.is_ref]
        assert backend._channel_labels[:64] == scalp


# ---------------------------------------------------------------------------
# start(): SDK call sequence
# ---------------------------------------------------------------------------

class TestStartCallSequence:
    def test_passes_only_reference_channels_to_open_impedance_stream(self):
        """open_impedance_stream must be called with REFERENCE-type channels only.

        This is the fix for the original "No impedance channels found" bug.
        The amplifier channel list contains REFERENCE and BIPOLAR channels;
        filtering for IMPEDANCE_REF/GND types returns nothing.
        """
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()

        captured_channels = []

        def capture_open_stream(aid, channels, count):
            for i in range(count):
                captured_channels.append(channels[i].type)
            return 0

        sdk.eemagine_sdk_open_impedance_stream.side_effect = capture_open_stream

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            backend.start()

        assert all(t == CHAN_REFERENCE for t in captured_channels), (
            f"open_impedance_stream received non-REFERENCE channel types: "
            f"{set(captured_channels) - {CHAN_REFERENCE}}"
        )
        assert len(captured_channels) == N_REF

    def test_first_read_is_discarded(self):
        """prefetch/get_data must be called once in start() and discarded (issue 3162)."""
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            backend.start()

        # start() calls _poll_once() once to discard the first result.
        # prefetch is called once during start, then once per read() call.
        assert sdk.eemagine_sdk_prefetch.call_count >= 1

    def test_sdk_init_called_before_get_amplifiers_info(self):
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        call_order = []
        sdk.eemagine_sdk_init.side_effect = lambda: call_order.append("init")
        original = sdk.eemagine_sdk_get_amplifiers_info.side_effect

        def tracking_get_amps(arr, size):
            call_order.append("get_amplifiers_info")
            return original(arr, size)

        sdk.eemagine_sdk_get_amplifiers_info.side_effect = tracking_get_amps

        with patch("ctypes.CDLL", return_value=sdk):
            EegoSDKBackend(layout, "/fake/libeego-SDK.so").start()

        assert call_order.index("init") < call_order.index("get_amplifiers_info")


# ---------------------------------------------------------------------------
# start(): error handling
# ---------------------------------------------------------------------------

class TestStartErrors:
    def test_no_amplifier_found_raises(self):
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        sdk.eemagine_sdk_get_amplifiers_info.side_effect = lambda arr, size: 0

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            with pytest.raises(RuntimeError, match="Amplifier not found"):
                backend.start()

    def test_already_exists_on_open_amplifier_raises(self):
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        sdk.eemagine_sdk_open_amplifier.return_value = -2

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            with pytest.raises(RuntimeError, match="Another eego stream"):
                backend.start()

    def test_already_exists_on_open_stream_raises(self):
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        sdk.eemagine_sdk_open_impedance_stream.side_effect = lambda *a: -2

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            with pytest.raises(RuntimeError, match="Another eego stream"):
                backend.start()

    def test_sdk_exit_called_when_amplifier_not_found(self):
        """SDK must be cleaned up even when start() fails."""
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        sdk.eemagine_sdk_get_amplifiers_info.side_effect = lambda arr, size: 0

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            with pytest.raises(RuntimeError):
                backend.start()

        sdk.eemagine_sdk_exit.assert_called_once()


# ---------------------------------------------------------------------------
# read(): buffer unpacking
# ---------------------------------------------------------------------------

class TestRead:
    def test_read_returns_correct_ohm_values(self):
        """Values from the getData buffer map to the correct electrode labels."""
        values = [float(i * 500) for i in range(34)]
        layout = get_layout("ca209")
        sdk = _make_fake_sdk(impedance_values=values)

        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
            backend.start()
            result = backend.read()

        # Channel 0 in the stream → FP1 (first scalp electrode in CA-209)
        assert result["FP1"] == pytest.approx(values[0])
        # Channel 31 → O2 (last scalp electrode)
        assert result["O2"] == pytest.approx(values[31])
        # GND is at position 33 (last channel)
        assert result["GND"] == pytest.approx(values[33])

    def test_read_includes_all_labels(self):
        """read() returns a value for every channel in _channel_labels."""
        backend, _ = _make_backend()
        result = backend.read()
        assert set(result.keys()) == set(backend._channel_labels)

    def test_read_returns_empty_before_start(self):
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
        # start() not called — _stream_id is None, prefetch returns 0 bytes
        sdk.eemagine_sdk_prefetch.side_effect = lambda sid: 0
        # Does not crash; _poll_once returns {}
        assert backend.read() == {}


# ---------------------------------------------------------------------------
# stop(): shutdown sequence
# ---------------------------------------------------------------------------

class TestStop:
    def test_stop_calls_close_stream_then_close_amplifier_then_exit(self):
        """SDK teardown must happen in this exact order (SDK constraint)."""
        backend, sdk = _make_backend()
        call_order = []
        sdk.eemagine_sdk_close_stream.side_effect   = lambda sid: call_order.append("close_stream") or 0
        sdk.eemagine_sdk_close_amplifier.side_effect = lambda aid: call_order.append("close_amplifier") or 0
        sdk.eemagine_sdk_exit.side_effect            = lambda: call_order.append("exit")

        backend.stop()

        assert call_order == ["close_stream", "close_amplifier", "exit"], (
            f"SDK teardown order wrong: {call_order}"
        )

    def test_stop_is_idempotent(self):
        """Calling stop() twice must not raise."""
        backend, _ = _make_backend()
        backend.stop()
        backend.stop()  # second call must be a no-op


# ---------------------------------------------------------------------------
# battery(): power state reporting
# ---------------------------------------------------------------------------

class TestBattery:
    def test_battery_returns_battery_state_on_success(self):
        """battery() returns a populated BatteryState when the SDK call succeeds."""
        from impedance_monitor.acquisition.base import BatteryState

        backend, sdk = _make_backend()

        def fake_power_state(amp_id, p_powered, p_charging, p_level):
            # byref() objects require ctypes.cast to write through them in a mock
            ctypes.cast(p_powered,  ctypes.POINTER(ctypes.c_int))[0] = 1
            ctypes.cast(p_charging, ctypes.POINTER(ctypes.c_int))[0] = 0
            ctypes.cast(p_level,    ctypes.POINTER(ctypes.c_int))[0] = 75
            return 0

        sdk.eemagine_sdk_get_amplifier_power_state.side_effect = fake_power_state
        result = backend.battery()

        assert isinstance(result, BatteryState)
        assert result.is_powered  is True
        assert result.is_charging is False
        assert result.level       == 75

    def test_battery_returns_none_on_sdk_error(self):
        """battery() returns None when get_amplifier_power_state returns a negative code.

        Battery state is informational — a failure must not raise or interrupt the session.
        """
        backend, sdk = _make_backend()
        sdk.eemagine_sdk_get_amplifier_power_state.return_value = -1
        assert backend.battery() is None

    def test_battery_returns_none_before_start(self):
        """battery() returns None when called before start() (no amp_id yet)."""
        layout = get_layout("ca209")
        sdk = _make_fake_sdk()
        with patch("ctypes.CDLL", return_value=sdk):
            backend = EegoSDKBackend(layout, "/fake/libeego-SDK.so")
        # start() not called — _amp_id is None
        assert backend.battery() is None
        sdk.eemagine_sdk_get_amplifier_power_state.assert_not_called()
