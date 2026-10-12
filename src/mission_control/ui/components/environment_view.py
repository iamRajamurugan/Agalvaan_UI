"""Compact rover-centric environment view.

A heading-up plan view: the rover sits at the centre pointing up, range rings give
scale, the TF Mini forward range is drawn as a beam, and nearby obstacles reported in
the rover frame are plotted around it. This is a status display, not a map: nothing
is accumulated, planned or localised here.
"""

import math
from typing import Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from mission_control.telemetry.state import ObstaclePoint, Severity
from mission_control.ui.components.telemetry_primitives import (
    SEVERITY_COLORS,
    TRACK_BORDER_COLOR,
)

#: Range represented by the outer ring.
VIEW_RANGE_M = 4.0
#: Nearby obstacles closer than this are drawn as warnings.
NEAR_OBSTACLE_M = 1.0

#: Distance from the rover icon's centre to its nose, in pixels.
ROVER_NOSE_PX = 10.0

CLEAR_TEXT = "CLEAR"
OBSTACLE_TEXT = "OBSTACLE"
NO_DATA_VIEW_TEXT = "NO DATA"

ROVER_COLOR = QColor("#38bdf8")
RING_LABEL_COLOR = QColor("#4b5772")
AXIS_LABEL_COLOR = QColor("#7c8ba1")
FAR_OBSTACLE_COLOR = QColor("#94a3b8")
BACKGROUND_COLOR = QColor("#0a0d13")


class EnvironmentView(QWidget):
    """Paints the rover, its heading, the TF Mini beam and nearby obstacles.

    Holds only the values of the last snapshot it was given, for painting.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._has_data = False
        self._heading_deg = 0.0
        self._range_m = 0.0
        self._obstacle_detected = False
        self._obstacles: tuple[ObstaclePoint, ...] = ()

        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # -- State -----------------------------------------------------------------

    @property
    def has_data(self) -> bool:
        return self._has_data

    @property
    def heading_deg(self) -> float:
        return self._heading_deg

    @property
    def range_m(self) -> float:
        return self._range_m

    @property
    def obstacle_detected(self) -> bool:
        return self._obstacle_detected

    @property
    def obstacles(self) -> tuple[ObstaclePoint, ...]:
        """Nearby obstacles currently plotted (those inside the view range)."""
        return self._obstacles

    @property
    def status_text(self) -> str:
        """The word painted in the view's corner."""
        if not self._has_data:
            return NO_DATA_VIEW_TEXT
        return OBSTACLE_TEXT if self._obstacle_detected else CLEAR_TEXT

    def set_environment(
        self,
        heading_deg: float,
        tfmini_range_m: float,
        obstacle_detected: bool,
        obstacles: Sequence[ObstaclePoint] = (),
    ) -> None:
        self._has_data = True
        self._heading_deg = heading_deg % 360.0
        self._range_m = max(0.0, tfmini_range_m)
        self._obstacle_detected = obstacle_detected
        self._obstacles = tuple(o for o in obstacles if 0.0 <= o.distance_m <= VIEW_RANGE_M)
        self.update()

    def clear(self) -> None:
        """Returns the view to its no-data appearance."""
        self._has_data = False
        self._heading_deg = 0.0
        self._range_m = 0.0
        self._obstacle_detected = False
        self._obstacles = ()
        self.update()

    # -- Painting --------------------------------------------------------------

    @staticmethod
    def _offset(bearing_deg: float, distance_px: float) -> QPointF:
        """Screen offset for a rover-frame bearing (0 = ahead/up, positive = left)."""
        angle = math.radians(bearing_deg)
        return QPointF(-math.sin(angle) * distance_px, -math.cos(angle) * distance_px)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), BACKGROUND_COLOR)

        width, height = self.width(), self.height()
        radius = max(10.0, min(width, height) / 2.0 - 14.0)
        centre = QPointF(width / 2.0, height / 2.0)
        px_per_m = radius / VIEW_RANGE_M
        small_font = QFont("Segoe UI", 7, QFont.Bold)
        painter.setFont(small_font)

        # Range rings, labelled so the picture has a scale
        painter.setBrush(Qt.NoBrush)
        for ring_m in range(1, int(VIEW_RANGE_M) + 1):
            is_outer = ring_m == int(VIEW_RANGE_M)
            painter.setPen(QPen(TRACK_BORDER_COLOR, 1, Qt.SolidLine if is_outer else Qt.DotLine))
            painter.drawEllipse(centre, ring_m * px_per_m, ring_m * px_per_m)
            if ring_m % 2 == 0:
                painter.setPen(RING_LABEL_COLOR)
                label_at = centre + self._offset(-135.0, ring_m * px_per_m)
                painter.drawText(label_at + QPointF(3.0, 9.0), f"{ring_m} m")

        if self._has_data:
            self._paint_world_axes(painter, centre, radius)
            self._paint_obstacles(painter, centre, px_per_m)
            self._paint_tfmini_beam(painter, centre, radius, px_per_m)

        self._paint_rover(painter, centre)
        self._paint_status(painter)
        painter.end()

    def _paint_world_axes(self, painter: QPainter, centre: QPointF, radius: float) -> None:
        """Marks where the world +X / +Y axes lie, which shows the rover's heading."""
        painter.setPen(AXIS_LABEL_COLOR)
        for label, world_angle in (("X", 0.0), ("Y", 90.0)):
            position = centre + self._offset(world_angle - self._heading_deg, radius + 7.0)
            painter.drawText(
                QRectF(position.x() - 6.0, position.y() - 6.0, 12.0, 12.0), Qt.AlignCenter, label
            )

    def _paint_obstacles(self, painter: QPainter, centre: QPointF, px_per_m: float) -> None:
        """Near obstacles are amber squares; farther ones are grey circles."""
        painter.setPen(Qt.NoPen)
        for obstacle in self._obstacles:
            position = centre + self._offset(obstacle.bearing_deg, obstacle.distance_m * px_per_m)
            if obstacle.distance_m < NEAR_OBSTACLE_M:
                painter.setBrush(SEVERITY_COLORS[Severity.WARNING])
                painter.drawRect(QRectF(position.x() - 4.0, position.y() - 4.0, 8.0, 8.0))
            else:
                painter.setBrush(FAR_OBSTACLE_COLOR)
                painter.drawEllipse(position, 3.0, 3.0)

    def _paint_tfmini_beam(
        self, painter: QPainter, centre: QPointF, radius: float, px_per_m: float
    ) -> None:
        """Forward range: a thin dashed line when clear, a solid bar-capped one when blocked."""
        in_view = self._range_m <= VIEW_RANGE_M
        # Never drawn closer than the rover's nose, so a very near reading stays visible.
        reach = max(ROVER_NOSE_PX + 6.0, min(self._range_m * px_per_m, radius))
        end = centre + QPointF(0.0, -reach)

        if self._obstacle_detected:
            color = SEVERITY_COLORS[Severity.WARNING]
            painter.setPen(QPen(color, 3))
            painter.drawLine(centre, end)
            painter.setPen(QPen(color, 5, Qt.SolidLine, Qt.FlatCap))
            painter.drawLine(end + QPointF(-14.0, 0.0), end + QPointF(14.0, 0.0))
        else:
            color = SEVERITY_COLORS[Severity.NORMAL]
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.drawLine(centre, end)
            if in_view:
                painter.setPen(QPen(color, 1))
                painter.drawLine(end + QPointF(-5.0, 0.0), end + QPointF(5.0, 0.0))

    def _paint_rover(self, painter: QPainter, centre: QPointF) -> None:
        color = ROVER_COLOR if self._has_data else SEVERITY_COLORS[Severity.NO_DATA]
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        shape = QPolygonF(
            [
                centre + QPointF(0.0, -ROVER_NOSE_PX),
                centre + QPointF(7.0, 8.0),
                centre + QPointF(0.0, 4.0),
                centre + QPointF(-7.0, 8.0),
            ]
        )
        painter.drawPolygon(shape)

    def _paint_status(self, painter: QPainter) -> None:
        """Writes the state as a word so it never depends on colour alone."""
        if not self._has_data:
            color = SEVERITY_COLORS[Severity.NO_DATA]
        elif self._obstacle_detected:
            color = SEVERITY_COLORS[Severity.WARNING]
        else:
            color = SEVERITY_COLORS[Severity.NORMAL]
        painter.setPen(color)
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.drawText(QPointF(6.0, 14.0), self.status_text)
