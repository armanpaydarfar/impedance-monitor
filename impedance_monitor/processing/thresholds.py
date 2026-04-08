from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    GOOD = "good"          # < 10 kΩ
    MARGINAL = "marginal"  # 10–20 kΩ (exclusive lower bound)
    BAD = "bad"            # 20 kΩ – 1 MΩ
    SHORT = "short"        # < 100 Ω (issue 3165) — likely shorted to adjacent electrode or reference
    OPEN = "open"          # SDK no-contact sentinel (0xFFFFFFFF) — cap not seated / electrode lifted
    DRY = "dry"            # ≥ 1 MΩ, non-sentinel — cap on but electrode not yet gelled


GOOD_THRESHOLD_OHM = 10_000
MARGINAL_THRESHOLD_OHM = 20_000
# SDK returns 0xFFFFFFFF (4 294 967 295 Ω) as the no-contact sentinel for
# ungelled / lifted electrodes. This specific value is classified as OPEN.
_SDK_OPEN_SENTINEL = 0xFFFFFFFF
# Values ≥ 1 MΩ that are not the sentinel are classified as DRY —
# the cap is seated but the electrode has not yet been gelled.
OPEN_CIRCUIT_CEILING_OHM = 1_000_000

# Near-zero values (< 100 Ω) are classified as OPEN per SDK issue 3165 (shorted /
# clipped signal, unresolved in SDK 1.3.19). Accuracy testing produced apparent
# flickering at ~1 kΩ channels, but < 100 Ω is physically implausible for real
# scalp contact — the likely cause was the raw value genuinely dipping near-zero
# transiently, not a false positive from this threshold.
OPEN_CIRCUIT_FLOOR_OHM = 100


@dataclass(frozen=True)
class ImpedanceReading:
    label: str
    ohm: float
    kohm: float    # ohm / 1000, for display
    status: Status


def classify(label: str, ohm: float) -> ImpedanceReading:
    """Classify a single channel impedance value.

    Three abnormal conditions, checked in priority order:
      - == 0xFFFFFFFF: SDK no-contact sentinel — OPEN (cap not seated / electrode lifted)
      - >= 1 MΩ (but not sentinel): dry electrode, cap on but ungelled — DRY
      - < 100 Ω: near-zero (SDK issue 3165) — SHORT (shorted to adjacent electrode or ref)

    Boundary values are inclusive of the higher band:
        exactly 10000 Ω → MARGINAL (not GOOD)
        exactly 20000 Ω → BAD (not MARGINAL)
    """
    if ohm == _SDK_OPEN_SENTINEL:
        status = Status.OPEN
    elif ohm >= OPEN_CIRCUIT_CEILING_OHM:
        status = Status.DRY
    elif ohm < OPEN_CIRCUIT_FLOOR_OHM:
        status = Status.SHORT
    elif ohm < GOOD_THRESHOLD_OHM:
        status = Status.GOOD
    elif ohm < MARGINAL_THRESHOLD_OHM:
        status = Status.MARGINAL
    else:
        status = Status.BAD
    return ImpedanceReading(label=label, ohm=ohm, kohm=ohm / 1000.0, status=status)


def classify_all(readings: dict[str, float]) -> dict[str, "ImpedanceReading"]:
    """Classify a full channel dict returned by AcquisitionBackend.read()."""
    return {label: classify(label, ohm) for label, ohm in readings.items()}
