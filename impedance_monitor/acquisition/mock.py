import random
from .base import AcquisitionBackend, BatteryState


class MockBackend(AcquisitionBackend):
    """Generates random-walk impedance values for all channels in a given cap layout.

    Values drift slowly to simulate gel drying / cap settling. The initial
    distribution covers SHORT, GOOD, MARGINAL, and BAD bands. OPEN (SDK sentinel)
    and ERROR are not exercised — those require specific raw values the random walk
    will not naturally produce.
    """

    def __init__(self, cap_layout, seed: int | None = None):
        self._labels = [e.label for e in cap_layout.electrodes]
        self._rng = random.Random(seed)
        self._values: dict[str, float] = {}
        self._battery_level: float = 85.0

    def start(self) -> None:
        # Seed each channel with a starting value drawn from across the full range.
        # The distribution intentionally spans SHORT, GOOD, MARGINAL, and BAD bands.
        band_starts = [
            (0, 80),            # SHORT: < 100 Ω
            (200, 9_800),       # GOOD: 100–10000 Ω
            (10_000, 19_800),   # MARGINAL: 10000–20000 Ω
            (20_000, 40_000),   # BAD: ≥ 20000 Ω
        ]
        for i, label in enumerate(self._labels):
            lo, hi = band_starts[i % len(band_starts)]
            self._values[label] = self._rng.uniform(lo, hi)

    def read(self) -> dict[str, float]:
        """Return current values with a small random walk applied."""
        if not self._values:
            return {}
        for label in self._labels:
            # Step size is ±5% of current value, clamped to [0, 50 kΩ]
            step = self._rng.uniform(-0.05, 0.05) * self._values[label]
            self._values[label] = max(0.0, min(50_000.0, self._values[label] + step))
        return dict(self._values)

    def battery(self) -> BatteryState:
        """Return a slowly draining simulated battery."""
        self._battery_level = max(0.0, self._battery_level - 0.05)
        return BatteryState(
            is_powered=True,
            is_charging=False,
            level=int(self._battery_level),
        )

    def stop(self) -> None:
        self._values.clear()
