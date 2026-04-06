from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BatteryState:
    is_powered: bool   # True if the amplifier is receiving power
    is_charging: bool  # True if the battery is currently charging
    level: int         # Charge level 0–100 (percent)


class AcquisitionBackend(ABC):
    @abstractmethod
    def start(self) -> None:
        """Open the hardware connection or initialise the data source."""

    @abstractmethod
    def read(self) -> dict[str, float]:
        """Return the latest impedance state.

        Keys are electrode labels (e.g. 'Fp1', 'Cz', 'GND').
        Values are impedance in Ohm.
        Returns an empty dict if no data is available yet.
        """

    @abstractmethod
    def stop(self) -> None:
        """Close the stream and release all resources."""

    def battery(self) -> BatteryState | None:
        """Return the current battery state, or None if not supported.

        Default implementation returns None. Override in backends that have
        access to power state information.
        """
        return None
