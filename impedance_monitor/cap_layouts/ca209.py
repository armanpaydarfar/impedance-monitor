from dataclasses import dataclass


@dataclass(frozen=True)
class Electrode:
    label: str
    x: float    # normalised head X position in [-1, 1], positive = right
    y: float    # normalised head Y position in [-1, 1], positive = anterior (nose-up)
    is_ground: bool = False
    is_ref: bool = False    # True for the hardware reference electrode (SDK IMPEDANCE_REF channel)


@dataclass(frozen=True)
class CapLayout:
    name: str
    electrodes: tuple


# Standard 10-20 polar-projected positions (nose-up, vertex at centre).
# Derived from the 10-20 international system; x positive = right, y positive = anterior.
# GND is placed below the head outline at bottom-centre (y = -1.25).
CA209_LAYOUT = CapLayout(
    name="CA-209",
    electrodes=(
        # Names from mainwindow.cpp electrodeMap_209 (lines 25-30).
        # Positions in the same order as the SDK channel list (ascending index).
        Electrode("FP1",  -0.18,  0.95),
        Electrode("FPz",   0.00,  0.95),
        Electrode("FP2",   0.18,  0.95),
        Electrode("F7",   -0.72,  0.55),
        Electrode("F3",   -0.32,  0.64),
        Electrode("Fz",    0.00,  0.65),
        Electrode("F4",    0.32,  0.64),
        Electrode("F8",    0.72,  0.55),
        Electrode("FC5",  -0.63,  0.32),
        Electrode("FC1",  -0.12,  0.35),
        Electrode("FC2",   0.12,  0.35),
        Electrode("FC6",   0.63,  0.32),
        Electrode("M1",   -0.95,  0.00),
        Electrode("T7",   -0.87,  0.00),
        Electrode("C3",   -0.45,  0.00),
        Electrode("Cz",    0.00,  0.00),
        Electrode("C4",    0.45,  0.00),
        Electrode("T8",    0.87,  0.00),
        Electrode("M2",    0.95,  0.00),
        Electrode("CP5",  -0.63, -0.32),
        Electrode("CP1",  -0.12, -0.35),
        Electrode("CP2",   0.12, -0.35),
        Electrode("CP6",   0.63, -0.32),
        Electrode("P7",   -0.72, -0.55),
        Electrode("P3",   -0.32, -0.64),
        Electrode("Pz",    0.00, -0.65),
        Electrode("P4",    0.32, -0.64),
        Electrode("P8",    0.72, -0.55),
        Electrode("POz",   0.00, -0.82),
        Electrode("O1",   -0.18, -0.95),
        Electrode("Oz",    0.00, -0.95),
        Electrode("O2",    0.18, -0.95),
        Electrode("GND",   0.00, -1.25, is_ground=True),
        # REF is the hardware reference electrode (SDK IMPEDANCE_REF channel).
        # Placed left of the head outline, mirroring GND below.
        Electrode("REF",  -1.35,  0.00, is_ref=True),
    ),
)
