"""Navigation card (state, pose, target distance) and the environment / TF Mini card."""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from mission_control.telemetry.state import (
    NavigationState,
    RoverState,
    Severity,
    navigation_severity,
)
from mission_control.ui.components.environment_view import (
    CLEAR_TEXT,
    OBSTACLE_TEXT,
    EnvironmentView,
)
from mission_control.ui.components.telemetry_primitives import (
    NO_DATA_TEXT,
    MetricRow,
    TelemetryCard,
    apply_severity,
)

DEGREE = "°"

#: Below this card height the environment view cannot be drawn usefully, so only
#: the TF Mini status and range rows are shown.
ENVIRONMENT_VIEW_MIN_CARD_HEIGHT = 210

#: A distinct shape per navigation state, so the state reads without colour.
NAV_STATE_GLYPHS = {
    NavigationState.IDLE: "■",
    NavigationState.MOVING: "▶",
    NavigationState.OBSTACLE_DETECTED: "⚠",
    NavigationState.EXCAVATING: "▼",
    NavigationState.DUMPING: "▲",
    NavigationState.RETURNING: "◀",
    NavigationState.COMPLETED: "✔",
}


class NavigationStateBanner(QFrame):
    """Prominent ``glyph  STATE`` banner heading the navigation card."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("NavStateBanner")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        self.icon_label = QLabel("")
        self.icon_label.setObjectName("NavStateIcon")
        layout.addWidget(self.icon_label)

        self.value_label = QLabel(NO_DATA_TEXT)
        self.value_label.setObjectName("NavStateValue")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.value_label, stretch=1)

        self.clear_value()

    def set_state(self, state: NavigationState) -> None:
        self._render(state.value, NAV_STATE_GLYPHS.get(state, ""), navigation_severity(state))

    def clear_value(self) -> None:
        self._render(NO_DATA_TEXT, "", Severity.NO_DATA)

    def value(self) -> str:
        return self.value_label.text()

    def glyph(self) -> str:
        return self.icon_label.text()

    def _render(self, text: str, glyph: str, severity: Severity) -> None:
        if self.value_label.text() == text and self.property("severity") == severity.name:
            return
        self.value_label.setText(text)
        self.icon_label.setText(glyph)
        for widget in (self, self.icon_label, self.value_label):
            apply_severity(widget, severity)


class NavigationWidget(TelemetryCard):
    """Displays the navigation state, rover position, heading and distance to target."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Navigation", parent)

        self.state_row = self.add_row(NavigationStateBanner())
        self.x_row = self.add_row(MetricRow("X", emphasis=True))
        self.y_row = self.add_row(MetricRow("Y", emphasis=True))
        self.heading_row = self.add_row(MetricRow("Heading"))
        self.target_row = self.add_row(MetricRow("To target"))

        self.show_no_data()

    def show_no_data(self) -> None:
        self.state_row.clear_value()
        self.x_row.clear_value()
        self.y_row.clear_value()
        self.heading_row.clear_value()
        self.target_row.clear_value()

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return

        navigation = state.navigation
        self.state_row.set_state(navigation.state)
        self.x_row.set_value(f"{navigation.x_m:+.2f} m", Severity.NORMAL)
        self.y_row.set_value(f"{navigation.y_m:+.2f} m", Severity.NORMAL)
        self.heading_row.set_value(f"{state.imu.yaw_deg % 360.0:.1f}{DEGREE}", Severity.NORMAL)
        self.target_row.set_value(f"{navigation.distance_to_target_m:.2f} m", Severity.NORMAL)


class ObstacleWidget(TelemetryCard):
    """Rover-centric environment view with the TF Mini obstacle status and range."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Environment", parent)

        self.view = self.add_row(EnvironmentView())
        self.status_row = self.add_row(MetricRow("TF Mini", status=True))
        self.range_row = self.add_row(MetricRow("Range"))

        # The view takes whatever height the side column has left; when it is hidden
        # (short card), the spare height collects below the rows instead.
        self.body_layout.setStretchFactor(self.view, 1)
        self.body_layout.addStretch(0)
        self._layout.setStretchFactor(self.body_layout, 1)

        self.show_no_data()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view.setVisible(self.height() >= ENVIRONMENT_VIEW_MIN_CARD_HEIGHT)

    def show_no_data(self) -> None:
        self.view.clear()
        self.status_row.clear_value()
        self.range_row.clear_value()
        self._set_alert(False)

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return

        perception = state.perception
        self.view.set_environment(
            heading_deg=state.imu.yaw_deg,
            tfmini_range_m=perception.obstacle_distance_m,
            obstacle_detected=perception.obstacle_detected,
            obstacles=perception.nearby_obstacles,
        )
        severity = Severity.WARNING if perception.obstacle_detected else Severity.NORMAL
        self.status_row.set_value(
            OBSTACLE_TEXT if perception.obstacle_detected else CLEAR_TEXT, severity
        )
        self.range_row.set_value(f"{perception.obstacle_distance_m:.2f} m", severity)
        self._set_alert(perception.obstacle_detected)

    def _set_alert(self, active: bool) -> None:
        """Outlines the card while an obstacle is reported (re-polished only on change)."""
        severity = Severity.WARNING if active else Severity.NORMAL
        if self.property("severity") != severity.name:
            apply_severity(self, severity)
