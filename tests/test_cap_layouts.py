import pytest
from impedance_monitor.cap_layouts import (
    CA001_LAYOUT,
    CA200_LAYOUT,
    CA209_LAYOUT,
    get_layout,
)
from impedance_monitor.cap_layouts.ca209 import CapLayout, Electrode


class TestGetLayout:
    def test_ca209_by_name(self):
        assert get_layout("ca209") is CA209_LAYOUT

    def test_ca001_by_name(self):
        assert get_layout("ca001") is CA001_LAYOUT

    def test_ca200_by_name(self):
        assert get_layout("ca200") is CA200_LAYOUT

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown cap layout"):
            get_layout("ca999")


class TestCA209Layout:
    def test_name(self):
        assert CA209_LAYOUT.name == "CA-209"

    def test_electrode_count(self):
        # 32 EEG + 1 GND + 1 REF = 34
        assert len(CA209_LAYOUT.electrodes) == 34

    def test_has_gnd(self):
        gnd = [e for e in CA209_LAYOUT.electrodes if e.is_ground]
        assert len(gnd) == 1
        assert gnd[0].label == "GND"

    def test_exactly_one_gnd(self):
        grounds = [e for e in CA209_LAYOUT.electrodes if e.is_ground]
        assert len(grounds) == 1

    def test_electrode_names_match_mainwindow(self):
        # EEG electrodes from mainwindow.cpp electrodeMap_209 lines 25-30;
        # GND and REF are special hardware electrodes appended after.
        expected = [
            "FP1", "FPz", "FP2", "F7", "F3", "Fz", "F4", "F8",
            "FC5", "FC1", "FC2", "FC6", "M1", "T7", "C3", "Cz",
            "C4", "T8", "M2", "CP5", "CP1", "CP2", "CP6", "P7",
            "P3", "Pz", "P4", "P8", "POz", "O1", "Oz", "O2", "GND", "REF",
        ]
        labels = [e.label for e in CA209_LAYOUT.electrodes]
        assert labels == expected

    def test_positions_in_range(self):
        # Scalp electrodes within [-1, 1]; GND/REF are off-scalp special electrodes
        for e in CA209_LAYOUT.electrodes:
            if not e.is_ground and not e.is_ref:
                assert -1.3 <= e.x <= 1.3, f"{e.label} x={e.x} out of range"
                assert -1.1 <= e.y <= 1.1, f"{e.label} y={e.y} out of range"

    def test_cz_at_origin(self):
        cz = next(e for e in CA209_LAYOUT.electrodes if e.label == "Cz")
        assert cz.x == 0.0
        assert cz.y == 0.0


class TestCA001Layout:
    def test_name(self):
        assert CA001_LAYOUT.name == "CA-001"

    def test_electrode_count(self):
        # 32 EEG + 1 GND + 1 REF = 34
        assert len(CA001_LAYOUT.electrodes) == 34

    def test_has_gnd(self):
        gnd = [e for e in CA001_LAYOUT.electrodes if e.is_ground]
        assert len(gnd) == 1

    def test_electrode_names_match_mainwindow(self):
        expected = [
            "AF3", "AF4", "F3", "F1", "Fz", "F2", "F4", "FC3",
            "FC1", "FCz", "FC2", "FC4", "C3", "C1", "Cz", "C2",
            "C4", "CP3", "CP1", "CPz", "CP2", "CP4", "P3", "P1",
            "Pz", "P2", "P4", "PO3", "POz", "PO4", "O1", "O2", "GND", "REF",
        ]
        labels = [e.label for e in CA001_LAYOUT.electrodes]
        assert labels == expected


class TestCA200Layout:
    def test_name(self):
        assert CA200_LAYOUT.name == "CA-200"

    def test_electrode_count(self):
        # 64 EEG + 1 GND + 1 REF = 66
        assert len(CA200_LAYOUT.electrodes) == 66

    def test_has_gnd(self):
        gnd = [e for e in CA200_LAYOUT.electrodes if e.is_ground]
        assert len(gnd) == 1

    def test_has_eog(self):
        eog = [e for e in CA200_LAYOUT.electrodes if e.label == "EOG"]
        assert len(eog) == 1

    def test_eog_off_scalp(self):
        # EOG is placed off-scalp to the right (x > 1)
        eog = next(e for e in CA200_LAYOUT.electrodes if e.label == "EOG")
        assert eog.x > 1.0

    def test_electrode_names_match_mainwindow(self):
        expected = [
            "FP1", "FPz", "FP2", "F7", "F3", "Fz", "F4", "F8",
            "FC5", "FC1", "FC2", "FC6", "M1", "T7", "C3", "Cz",
            "C4", "T8", "M2", "CP5", "CP1", "CP2", "CP6", "P7",
            "P3", "Pz", "P4", "P8", "POz", "O1", "O2", "EOG",
            "AF7", "AF3", "AF4", "AF8", "F5", "F1", "F2", "F6",
            "FC3", "FCz", "FC4", "C5", "C1", "C2", "C6", "CP3",
            "CP4", "P5", "P1", "P2", "P6", "PO5", "PO3", "PO4",
            "PO6", "FT7", "FT8", "TP7", "TP8", "PO7", "PO8", "Oz", "GND", "REF",
        ]
        labels = [e.label for e in CA200_LAYOUT.electrodes]
        assert labels == expected
