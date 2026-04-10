import pytest
from impedance_monitor.processing.thresholds import (
    GOOD_THRESHOLD_OHM,
    MARGINAL_THRESHOLD_OHM,
    OPEN_CIRCUIT_CEILING_OHM,
    OPEN_CIRCUIT_FLOOR_OHM,
    ImpedanceReading,
    Status,
    classify,
    classify_all,
)


class TestClassify:
    def test_short_at_zero(self):
        r = classify("GND", 0.0)
        assert r.status == Status.SHORT

    def test_short_just_below_floor(self):
        r = classify("GND", OPEN_CIRCUIT_FLOOR_OHM - 1)
        assert r.status == Status.SHORT

    def test_good_at_floor(self):
        # Exactly 100 Ω: not short (< 100 is short), so GOOD
        r = classify("Fp1", OPEN_CIRCUIT_FLOOR_OHM)
        assert r.status == Status.GOOD

    def test_good_midrange(self):
        r = classify("Cz", 2500.0)
        assert r.status == Status.GOOD

    def test_good_just_below_threshold(self):
        r = classify("Cz", GOOD_THRESHOLD_OHM - 1)
        assert r.status == Status.GOOD

    def test_marginal_at_good_threshold(self):
        # Exactly 10000 Ω → MARGINAL (boundary inclusive of higher band)
        r = classify("Cz", GOOD_THRESHOLD_OHM)
        assert r.status == Status.MARGINAL

    def test_marginal_midrange(self):
        r = classify("Cz", 100_000.0)
        assert r.status == Status.MARGINAL

    def test_marginal_just_below_threshold(self):
        r = classify("Cz", MARGINAL_THRESHOLD_OHM - 1)
        assert r.status == Status.MARGINAL

    def test_bad_at_marginal_threshold(self):
        # Exactly 20000 Ω → BAD (boundary inclusive of higher band)
        r = classify("Cz", MARGINAL_THRESHOLD_OHM)
        assert r.status == Status.BAD

    def test_bad_large_value(self):
        r = classify("Cz", 250_000.0)
        assert r.status == Status.BAD

    def test_bad_just_below_ceiling(self):
        r = classify("Cz", OPEN_CIRCUIT_CEILING_OHM - 1)
        assert r.status == Status.BAD

    def test_dry_at_ceiling(self):
        # ≥ 1 MΩ but not the known sentinel → DRY (cap on, electrode ungelled)
        r = classify("Cz", OPEN_CIRCUIT_CEILING_OHM)
        assert r.status == Status.DRY

    def test_dry_large_non_sentinel(self):
        r = classify("Cz", 2_000_000.0)
        assert r.status == Status.DRY

    def test_open_sdk_sentinel(self):
        # 0xFFFFFFFF — SDK no-contact sentinel for ungelled / not-placed electrodes
        r = classify("FP1", 4_294_967_295.0)
        assert r.status == Status.OPEN

    def test_label_preserved(self):
        r = classify("Fp1", 3000.0)
        assert r.label == "Fp1"

    def test_kohm_computed(self):
        r = classify("Cz", 3200.0)
        assert r.kohm == pytest.approx(3.2)

    def test_ohm_preserved(self):
        r = classify("Cz", 3200.0)
        assert r.ohm == 3200.0

    def test_returns_impedance_reading(self):
        r = classify("O1", 500.0)
        assert isinstance(r, ImpedanceReading)


class TestClassifyAll:
    def test_classifies_all_channels(self):
        readings = {
            "Fp1": 1000.0,
            "GND": 50.0,
            "Cz": 100_000.0,
            "O1": 250_000.0,
            "Fz": 4_294_967_295.0,
        }
        result = classify_all(readings)
        assert result["Fp1"].status == Status.GOOD
        assert result["GND"].status == Status.SHORT
        assert result["Cz"].status == Status.MARGINAL
        assert result["O1"].status == Status.BAD
        assert result["Fz"].status == Status.OPEN

    def test_empty_dict(self):
        assert classify_all({}) == {}
