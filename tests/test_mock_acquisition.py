from impedance_monitor.acquisition.mock import MockBackend
from impedance_monitor.cap_layouts import get_layout


class TestMockBackend:
    def _backend(self, cap="ca209", seed=42) -> MockBackend:
        layout = get_layout(cap)
        return MockBackend(layout, seed=seed)

    def test_read_returns_all_channels(self):
        b = self._backend()
        b.start()
        result = b.read()
        layout = get_layout("ca209")
        expected_labels = {e.label for e in layout.electrodes}
        assert set(result.keys()) == expected_labels
        b.stop()

    def test_values_are_floats(self):
        b = self._backend()
        b.start()
        result = b.read()
        for v in result.values():
            assert isinstance(v, float)
        b.stop()

    def test_values_non_negative(self):
        b = self._backend()
        b.start()
        result = b.read()
        for v in result.values():
            assert v >= 0.0
        b.stop()

    def test_values_within_range(self):
        b = self._backend()
        b.start()
        result = b.read()
        for v in result.values():
            assert v <= 50_000.0
        b.stop()

    def test_read_before_start_returns_empty(self):
        b = self._backend()
        # Before start(), _values is empty — read() returns empty dict
        result = b.read()
        assert result == {}

    def test_stop_clears_values(self):
        b = self._backend()
        b.start()
        b.read()
        b.stop()
        assert b.read() == {}

    def test_seeded_reproducibility(self):
        b1 = self._backend(seed=0)
        b2 = self._backend(seed=0)
        b1.start()
        b2.start()
        r1 = b1.read()
        r2 = b2.read()
        assert r1 == r2

    def test_ca200_has_64_plus_gnd_channels(self):
        layout = get_layout("ca200")
        b = MockBackend(layout, seed=1)
        b.start()
        result = b.read()
        assert len(result) == len(layout.electrodes)
        b.stop()
