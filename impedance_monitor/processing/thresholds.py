from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    GOOD = "good"        # 100 ≤ value < 10 kΩ
    MARGINAL = "marginal"  # 10–20 kΩ (exclusive lower bound)
    BAD = "bad"          # 20 kΩ – 1 MΩ
    OPEN = "open"        # < 100 Ω (issue 3165) or ≥ 1 MΩ (SDK sentinel for no contact)


GOOD_THRESHOLD_OHM = 10_000
MARGINAL_THRESHOLD_OHM = 20_000
OPEN_CIRCUIT_FLOOR_OHM = 100
# SDK returns 0xFFFFFFFF (~4.3 GΩ) for electrodes with no contact (ungelled/lifted).
# Any value at or above this ceiling is open circuit, not a meaningful impedance.
OPEN_CIRCUIT_CEILING_OHM = 1_000_000


@dataclass(frozen=True)
class ImpedanceReading:
    label: str
    ohm: float
    kohm: float    # ohm / 1000, for display
    status: Status


def classify(label: str, ohm: float) -> ImpedanceReading:
    """Classify a single channel impedance value.

    Two distinct OPEN conditions:
      - < 100 Ω: near-zero (SDK issue 3165 — shorted/clipped signal)
      - ≥ 1 MΩ: SDK sentinel 0xFFFFFFFF returned for ungelled / no-contact electrodes

    Boundary values are inclusive of the higher band:
        exactly 10000 Ω → MARGINAL (not GOOD)
        exactly 20000 Ω → BAD (not MARGINAL)
    """
    if ohm < OPEN_CIRCUIT_FLOOR_OHM or ohm >= OPEN_CIRCUIT_CEILING_OHM:
        status = Status.OPEN
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
