"""ctypes binding to libeego-SDK.so for live impedance acquisition.

This is the only file that may import ctypes or load libeego-SDK.so.
No other module touches the SDK. This module must never be imported in mock mode —
the acquisition backend is injected at runtime.

SDK constraints enforced here:
  - Only one stream may be active at a time.
  - stop() calls close_stream, close_amplifier, and eemagine_sdk_exit() in that order.
  - The first getData() result after stream open is discarded (issue 3162).
  - Values below 100 Ω are classified as OPEN circuit, not GOOD (issue 3165 —
    handled in processing/thresholds.py, but documented here for traceability).
"""

import ctypes
import logging
from pathlib import Path

from .base import AcquisitionBackend

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# SDK path resolution order (first found wins)
# --------------------------------------------------------------------------
_SDK_SEARCH_PATHS = [
    # Resolved at call time so EEGO_SDK_PATH is read from the live environment
    None,  # placeholder for EEGO_SDK_PATH — resolved in resolve_sdk_path()
    "/home/arman-admin/opt/lsl-eego/libeego-SDK.so",
    "/opt/lsl-eego/libeego-SDK.so",
    "libeego-SDK.so",  # relies on LD_LIBRARY_PATH or system library path
]


def resolve_sdk_path(explicit: str | None = None) -> str:
    """Return the path to libeego-SDK.so, searching in priority order.

    Priority:
      1. explicit argument (from --sdk-path CLI arg)
      2. EEGO_SDK_PATH environment variable
      3. /home/arman-admin/opt/lsl-eego/libeego-SDK.so
      4. /opt/lsl-eego/libeego-SDK.so
      5. libeego-SDK.so  (via LD_LIBRARY_PATH / system)

    Raises FileNotFoundError if none resolves.
    """
    import os

    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)

    env_path = os.environ.get("EEGO_SDK_PATH", "")
    if env_path:
        candidates.append(env_path)

    candidates.extend([
        "/home/arman-admin/opt/lsl-eego/libeego-SDK.so",
        "/opt/lsl-eego/libeego-SDK.so",
        "libeego-SDK.so",
    ])

    for p in candidates:
        if p == "libeego-SDK.so":
            # System-path resolution — try loading and catch OSError
            try:
                ctypes.CDLL(p)
                return p
            except OSError:
                continue
        if Path(p).is_file():
            return p

    checked = "\n  ".join(candidates)
    raise FileNotFoundError(
        f"libeego-SDK.so not found. Paths checked:\n  {checked}\n"
        "Set EEGO_SDK_PATH or use --sdk-path to specify the location."
    )


# --------------------------------------------------------------------------
# ctypes struct and constant definitions
# --------------------------------------------------------------------------

class _AmpInfo(ctypes.Structure):
    _fields_ = [
        ("id",     ctypes.c_int),
        ("serial", ctypes.c_char * 64),
    ]


class _ChannelInfo(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_int),
        ("type",  ctypes.c_int),
    ]


# Channel type constants from wrapper.h eemagine_sdk_channel_type enum.
CHAN_REFERENCE          = 0
CHAN_BIPOLAR            = 1
CHAN_ACCELEROMETER      = 2
CHAN_GYROSCOPE          = 3
CHAN_MAGNETOMETER       = 4
CHAN_TRIGGER            = 5
CHAN_SAMPLE_COUNTER     = 6
CHAN_IMPEDANCE_REF      = 7   # impedance_reference — per EEG electrode
CHAN_IMPEDANCE_GND      = 8   # impedance_ground

# SDK error codes from wrapper.h
_SDK_ERROR_STRINGS = {
    -1: "NOT_CONNECTED",
    -2: "ALREADY_EXISTS",
    -3: "NOT_FOUND",
    -4: "INCORRECT_VALUE",
    -5: "INTERNAL_ERROR",
    -6: "UNKNOWN",
}


def _check(ret: int, sdk: ctypes.CDLL, context: str) -> int:
    """Raise RuntimeError if ret is a negative SDK error code."""
    if ret < 0:
        err_buf = ctypes.create_string_buffer(256)
        sdk.eemagine_sdk_get_error_string(err_buf, 256)
        err_str = err_buf.value.decode(errors="replace")
        code_name = _SDK_ERROR_STRINGS.get(ret, f"code {ret}")
        raise RuntimeError(
            f"SDK error in {context}: {code_name} — {err_str}"
        )
    return ret


# --------------------------------------------------------------------------
# EegoSDKBackend
# --------------------------------------------------------------------------

class EegoSDKBackend(AcquisitionBackend):
    """Live impedance acquisition via ctypes binding to libeego-SDK.so.

    Parameters
    ----------
    cap_layout:
        CapLayout instance whose electrode list determines the channel→label mapping.
    sdk_path:
        Resolved path to libeego-SDK.so (use resolve_sdk_path() before constructing).
    """

    def __init__(self, cap_layout, sdk_path: str) -> None:
        self._layout = cap_layout
        self._sdk_path = sdk_path
        self._sdk: ctypes.CDLL | None = None
        self._amp_id: int | None = None
        self._stream_id: int | None = None
        # Ordered list of (label, is_ground) built during start(), used to unpack buf
        self._channel_labels: list[str] = []

    def start(self) -> None:
        """Open the SDK, connect to the first amplifier, and open the impedance stream."""
        self._sdk = ctypes.CDLL(self._sdk_path)
        sdk = self._sdk

        sdk.eemagine_sdk_init()
        logger.info("SDK initialised: %s", self._sdk_path)

        # Discover amplifiers
        amp_info_array = (_AmpInfo * 8)()
        count = sdk.eemagine_sdk_get_amplifiers_info(amp_info_array, 8)
        if count <= 0:
            sdk.eemagine_sdk_exit()
            raise RuntimeError(
                "Amplifier not found — check USB connection and udev rules (90-eego.rules)."
            )

        self._amp_id = amp_info_array[0].id
        serial = amp_info_array[0].serial.decode(errors="replace")
        logger.info("Amplifier found: id=%d serial=%s", self._amp_id, serial)

        ret = sdk.eemagine_sdk_open_amplifier(self._amp_id)
        if ret < 0:
            sdk.eemagine_sdk_exit()
            if ret == -2:
                raise RuntimeError(
                    "Another eego stream is active. Close eegoSports or any other "
                    "acquisition tool before running the impedance monitor."
                )
            _check(ret, sdk, "open_amplifier")

        # Get the full channel list from the amplifier.
        # The amplifier list contains reference, bipolar, trigger, etc. channels.
        # Impedance-typed channels (CHAN_IMPEDANCE_REF / CHAN_IMPEDANCE_GND) do NOT
        # appear here — they only appear in the stream channel list after the stream
        # is opened. To request impedance measurement, we pass the REFERENCE channels
        # to open_impedance_stream; the SDK maps them to impedance internally.
        ch_array = (_ChannelInfo * 256)()
        n = _check(
            sdk.eemagine_sdk_get_amplifier_channel_list(self._amp_id, ch_array, 256),
            sdk, "get_amplifier_channel_list",
        )

        # Log the type distribution for diagnostics
        from collections import Counter
        type_counts = Counter(ch_array[i].type for i in range(n))
        logger.info(
            "Amplifier channel list: %d channels — types: %s",
            n,
            dict(type_counts),
        )

        # Select reference channels (type 0) to request impedance for each EEG electrode
        ref_channels = sorted(
            [ch_array[i] for i in range(n) if ch_array[i].type == CHAN_REFERENCE],
            key=lambda c: c.index,
        )
        if not ref_channels:
            sdk.eemagine_sdk_close_amplifier(self._amp_id)
            sdk.eemagine_sdk_exit()
            raise RuntimeError(
                f"No reference channels found in the amplifier channel list "
                f"(got {n} channels with types {dict(type_counts)}). "
                f"Cannot open impedance stream."
            )

        n_ref = len(ref_channels)
        ch_arr = (_ChannelInfo * n_ref)(*ref_channels)

        stream_id = sdk.eemagine_sdk_open_impedance_stream(self._amp_id, ch_arr, n_ref)
        if stream_id < 0:
            sdk.eemagine_sdk_close_amplifier(self._amp_id)
            sdk.eemagine_sdk_exit()
            if stream_id == -2:
                raise RuntimeError(
                    "Another eego stream is active. Close eegoSports or any other "
                    "acquisition tool before running the impedance monitor."
                )
            _check(stream_id, sdk, "open_impedance_stream")
        self._stream_id = stream_id

        # Query the stream's own channel list to determine the buffer layout.
        # The SDK echoes back the input channel types in the stream channel list —
        # the 32 REFERENCE-type channels we passed in appear as REFERENCE (type 0)
        # in the stream, not as IMPEDANCE_REFERENCE (type 7). Their buffer values
        # are nonetheless impedance readings in Ohm. The SDK appends the hardware
        # REF electrode as IMPEDANCE_REF (type 7) and the GND electrode as
        # IMPEDANCE_GND (type 8) at the end.
        stream_ch_array = (_ChannelInfo * 256)()
        n_stream = _check(
            sdk.eemagine_sdk_get_stream_channel_list(self._stream_id, stream_ch_array, 256),
            sdk, "get_stream_channel_list",
        )

        from collections import Counter as _Counter
        stream_type_counts = _Counter(stream_ch_array[i].type for i in range(n_stream))
        logger.info(
            "Impedance stream opened (id=%d): %d total channels — types: %s",
            self._stream_id, n_stream, dict(stream_type_counts),
        )

        # Build the label list by iterating the stream channel list in order.
        # REFERENCE (0): per-electrode impedance values — map positionally to
        #                scalp electrodes in the cap layout.
        # IMPEDANCE_REF (7): hardware reference electrode — labelled "REF".
        #                    Not in the cap layout; logged to CSV only.
        # IMPEDANCE_GND (8): GND electrode — mapped to the layout's GND electrode.
        scalp_electrodes = [e for e in self._layout.electrodes if not e.is_ground and not e.is_ref]
        gnd_electrodes   = [e for e in self._layout.electrodes if e.is_ground]
        ref_electrodes   = [e for e in self._layout.electrodes if e.is_ref]

        scalp_pos = 0  # increments for each REFERENCE-type channel seen
        self._channel_labels = []
        for i in range(n_stream):
            ch_type = stream_ch_array[i].type
            if ch_type == CHAN_REFERENCE:
                label = (scalp_electrodes[scalp_pos].label
                         if scalp_pos < len(scalp_electrodes) else f"CH{scalp_pos}")
                self._channel_labels.append(label)
                scalp_pos += 1
            elif ch_type == CHAN_IMPEDANCE_GND:
                label = gnd_electrodes[0].label if gnd_electrodes else "GND"
                self._channel_labels.append(label)
            elif ch_type == CHAN_IMPEDANCE_REF:
                # Hardware reference electrode — mapped to the layout's REF electrode
                label = ref_electrodes[0].label if ref_electrodes else "REF"
                self._channel_labels.append(label)
            else:
                logger.warning(
                    "Unexpected channel type %d at stream position %d — labelled as RAW%d",
                    ch_type, i, i,
                )
                self._channel_labels.append(f"RAW{i}")

        logger.info("Channel label map: %s", self._channel_labels)

        # Discard first getData() result — SDK issue 3162: first cycle delivers wrong values.
        self._poll_once()
        logger.info("First read discarded (SDK issue 3162)")

    def _poll_once(self) -> dict[str, float]:
        """Execute one prefetch/get_data cycle and return raw values in Ohm."""
        if self._sdk is None or self._stream_id is None:
            return {}
        sdk = self._sdk
        bytes_needed = _check(
            sdk.eemagine_sdk_prefetch(self._stream_id),
            sdk, "prefetch",
        )
        if bytes_needed == 0:
            return {}

        n_doubles = bytes_needed // 8
        buf = (ctypes.c_double * n_doubles)()
        _check(
            sdk.eemagine_sdk_get_data(self._stream_id, buf, bytes_needed),
            sdk, "get_data",
        )

        # Buffer layout: data[channel + sample * channel_count].
        # An impedance stream returns one sample per channel, so sample index is 0.
        # buf[channel] gives the value for that channel.
        result: dict[str, float] = {}
        for i, label in enumerate(self._channel_labels):
            if i < n_doubles:
                result[label] = buf[i]
        return result

    def read(self) -> dict[str, float]:
        """Return the latest impedance state in Ohm, keyed by electrode label."""
        return self._poll_once()

    def battery(self):
        """Return the amplifier battery state, or None if the call fails."""
        if self._sdk is None or self._amp_id is None:
            return None
        from .base import BatteryState
        is_powered  = ctypes.c_int(0)
        is_charging = ctypes.c_int(0)
        level       = ctypes.c_int(0)
        ret = self._sdk.eemagine_sdk_get_amplifier_power_state(
            self._amp_id,
            ctypes.byref(is_powered),
            ctypes.byref(is_charging),
            ctypes.byref(level),
        )
        if ret < 0:
            # Non-fatal — battery state is informational only
            logger.warning("get_amplifier_power_state returned %d", ret)
            return None
        return BatteryState(
            is_powered=bool(is_powered.value),
            is_charging=bool(is_charging.value),
            level=int(level.value),
        )

    def stop(self) -> None:
        """Close the stream, amplifier, and SDK in the required order."""
        sdk = self._sdk
        if sdk is None:
            return

        if self._stream_id is not None:
            try:
                sdk.eemagine_sdk_close_stream(self._stream_id)
                logger.info("Stream closed")
            except Exception:
                logger.exception("Error closing stream")
            self._stream_id = None

        if self._amp_id is not None:
            try:
                sdk.eemagine_sdk_close_amplifier(self._amp_id)
                logger.info("Amplifier closed")
            except Exception:
                logger.exception("Error closing amplifier")
            self._amp_id = None

        try:
            sdk.eemagine_sdk_exit()
            logger.info("SDK exit called")
        except Exception:
            logger.exception("Error calling eemagine_sdk_exit")

        self._sdk = None
