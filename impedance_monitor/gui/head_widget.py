"""Custom QWidget that draws a per-electrode impedance topomap.

Coordinate system: electrode (x, y) normalised positions from CapLayout are
mapped to pixel coordinates as:
    pixel_x = centre_x + x * radius
    pixel_y = centre_y - y * radius   (Y flipped: screen Y increases downward)

where centre and radius are recomputed from widget dimensions on every paintEvent.

Each electrode is drawn as a colour-coded circle with the channel label centred
inside and the kΩ value drawn just below the circle. OPEN-circuit electrodes are
shown in white with no value text.
"""

import math

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QToolTip, QWidget

from ..processing.thresholds import ImpedanceReading, Status

# Colours per status
_STATUS_COLOURS: dict[Status | None, str] = {
    Status.GOOD:     "#2ecc71",   # green  — < 10 kΩ
    Status.MARGINAL: "#f39c12",   # orange — 10–20 kΩ
    Status.BAD:      "#e74c3c",   # red    — > 20 kΩ
    Status.OPEN:     "#ffffff",   # white  — < 100 Ω (open circuit)
    None:            "#aaaaaa",   # grey   — no data yet
}

# Text colour on each background for legibility
_TEXT_COLOURS: dict[Status | None, str] = {
    Status.GOOD:     "#ffffff",
    Status.MARGINAL: "#000000",
    Status.BAD:      "#ffffff",
    Status.OPEN:     "#888888",   # mid-grey label on white
    None:            "#000000",
}

_LEGEND_ENTRIES = [
    (Status.GOOD,     "Good",     "< 10 kΩ"),
    (Status.MARGINAL, "Marginal", "10–20 kΩ"),
    (Status.BAD,      "Bad",      "> 20 kΩ"),
    (Status.OPEN,     "Open",     "< 100 Ω"),
]


def _format_kohm(reading: ImpedanceReading | None) -> str:
    """Format a reading's value as e.g. '4.5K' or '30K'. Returns '' for open/no-data."""
    if reading is None or reading.status == Status.OPEN:
        return ""
    return f"{reading.kohm:.1f}K"


class HeadWidget(QWidget):
    """Draws the electrode topomap with colour-coded impedance status."""

    # Electrode circle radius as a fraction of the head radius
    _ELEC_RADIUS_FRACTION = 0.055

    # Hit-test radius in pixels for tooltip hover
    _HIT_RADIUS_PX = 20

    def __init__(self, cap_layout, parent=None):
        super().__init__(parent)
        self._layout = cap_layout
        self._readings: dict[str, ImpedanceReading] = {}
        self.setMinimumSize(600, 650)
        self.setMouseTracking(True)

    def set_layout(self, cap_layout) -> None:
        """Swap to a new cap layout and clear stale readings."""
        self._layout = cap_layout
        self._readings = {}
        self.update()

    def update_readings(self, readings: dict[str, ImpedanceReading]) -> None:
        """Receive classified readings and trigger a repaint."""
        self._readings = readings
        self.update()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _head_geometry(self) -> tuple[int, int, int]:
        """Return (centre_x, centre_y, radius) for the head outline circle.

        The circle occupies ~76% of the smaller widget dimension, centred
        horizontally. Vertically it is shifted upward slightly to leave room
        for the GND electrode drawn below and value text under each electrode.
        """
        w, h = self.width(), self.height()
        radius = int(min(w, h) * 0.36)
        cx = w // 2
        cy = int(h * 0.44)
        return cx, cy, radius

    def _electrode_pixel(self, x: float, y: float, cx: int, cy: int, r: int) -> tuple[int, int]:
        px = int(cx + x * r)
        py = int(cy - y * r)
        return px, py

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self._head_geometry()
        elec_r = max(10, int(r * self._ELEC_RADIUS_FRACTION))
        self._draw_head(painter, cx, cy, r)
        self._draw_electrodes(painter, cx, cy, r, elec_r)
        self._draw_legend(painter)

    def _draw_head(self, painter: QPainter, cx: int, cy: int, r: int) -> None:
        """Draw head outline circle and nose triangle."""
        pen = QPen(QColor("#333333"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        # Nose — small upward triangle centred above the head circle
        nose_w = int(r * 0.12)
        nose_h = int(r * 0.10)
        top = cy - r - nose_h
        pts = QPolygon([
            QPoint(cx, top),
            QPoint(cx - nose_w, cy - r + 4),
            QPoint(cx + nose_w, cy - r + 4),
        ])
        painter.setBrush(QColor("#333333"))
        painter.drawPolygon(pts)

    def _draw_electrodes(
        self, painter: QPainter, cx: int, cy: int, r: int, elec_r: int
    ) -> None:
        label_font = QFont()
        label_font.setPixelSize(max(8, elec_r - 2))

        value_font = QFont()
        value_font.setPixelSize(max(7, elec_r - 4))

        for elec in self._layout.electrodes:
            reading = self._readings.get(elec.label)
            status = reading.status if reading else None
            bg_colour = QColor(_STATUS_COLOURS[status])
            text_colour = QColor(_TEXT_COLOURS[status])

            px, py = self._electrode_pixel(elec.x, elec.y, cx, cy, r)

            # Circle
            painter.setPen(QPen(QColor("#222222"), 1))
            painter.setBrush(bg_colour)
            painter.drawEllipse(px - elec_r, py - elec_r, 2 * elec_r, 2 * elec_r)

            # Label centred in circle
            painter.setFont(label_font)
            painter.setPen(text_colour)
            label_rect = QRect(px - elec_r, py - elec_r, 2 * elec_r, 2 * elec_r)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, elec.label)

            # kΩ value below the circle (not shown for OPEN or no-data)
            val_text = _format_kohm(reading)
            if val_text:
                painter.setFont(value_font)
                painter.setPen(QColor("#333333"))
                val_rect = QRect(px - elec_r * 3, py + elec_r + 1, elec_r * 6, elec_r + 4)
                painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, val_text)

    def _draw_legend(self, painter: QPainter) -> None:
        """Draw a status legend in the lower-right corner."""
        w, h = self.width(), self.height()
        entry_h = 22
        swatch_w = 16
        margin = 10
        padding = 4

        font = QFont()
        font.setPixelSize(12)
        painter.setFont(font)

        legend_w = 140
        legend_h = len(_LEGEND_ENTRIES) * entry_h + padding * 2

        lx = w - legend_w - margin
        ly = h - legend_h - margin

        # Background
        painter.setPen(QPen(QColor("#aaaaaa"), 1))
        painter.setBrush(QColor(240, 240, 240, 200))
        painter.drawRoundedRect(lx, ly, legend_w, legend_h, 4, 4)

        for i, (status, label, rng) in enumerate(_LEGEND_ENTRIES):
            row_y = ly + padding + i * entry_h
            # Colour swatch (with border for white/light swatches)
            swatch_colour = QColor(_STATUS_COLOURS[status])
            painter.setPen(QPen(QColor("#aaaaaa"), 1))
            painter.setBrush(swatch_colour)
            painter.drawRect(lx + padding, row_y + 3, swatch_w, entry_h - 8)
            # Text
            painter.setPen(QColor("#000000"))
            painter.drawText(
                lx + padding + swatch_w + 4,
                row_y,
                legend_w - swatch_w - padding * 2 - 4,
                entry_h,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{label} {rng}",
            )

    # ------------------------------------------------------------------
    # Tooltip on hover
    # ------------------------------------------------------------------

    def mouseMoveEvent(self, event):  # noqa: N802
        cx, cy, r = self._head_geometry()
        elec_r = max(10, int(r * self._ELEC_RADIUS_FRACTION))
        pos = event.position()
        mx, my = int(pos.x()), int(pos.y())

        nearest_label: str | None = None
        nearest_dist = self._HIT_RADIUS_PX + elec_r

        for elec in self._layout.electrodes:
            px, py = self._electrode_pixel(elec.x, elec.y, cx, cy, r)
            dist = math.hypot(mx - px, my - py)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_label = elec.label

        if nearest_label and nearest_label in self._readings:
            reading = self._readings[nearest_label]
            tip = f"{reading.label}: {reading.kohm:.2f} kΩ ({reading.status.value})"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

        super().mouseMoveEvent(event)
