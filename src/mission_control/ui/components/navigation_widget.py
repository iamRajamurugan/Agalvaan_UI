"""Navigation card (pose, target distance, navigation state) and TF Mini obstacle card."""

from typing import Optional

from PySide6.QtWidgets import QWidget

from mission_control.telemetry.state import (
    RoverState,
    Severity,
    navigation_severity,
)
from mission_control.ui.components.telemetry_primitives import (
    MetricRow,
    TelemetryCard,
)

DEGREE = "°"


class NavigationWidget(TelemetryCard):
    """Displays rover position, heading, distance to target, and navigation state."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Navigation", parent)

        self.state_row = self.add_row(MetricRow("State", status=True))
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
        self.state_row.set_value(navigation.state.value, navigation_severity(navigation.state))
        self.x_row.set_value(f"{navigation.x_m:+.2f} m", Severity.NORMAL)
        self.y_row.set_value(f"{navigation.y_m:+.2f} m", Severity.NORMAL)
        self.heading_row.set_value(f"{state.imu.yaw_deg % 360.0:.1f}{DEGREE}", Severity.NORMAL)
        self.target_row.set_value(f"{navigation.distance_to_target_m:.2f} m", Severity.NORMAL)


class ObstacleWidget(TelemetryCard):
    """Displays the TF Mini range finder's obstacle status and measured range."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("TF Mini Obstacle", parent)

        self.status_row = self.add_row(MetricRow("Status", status=True))
        self.range_row = self.add_row(MetricRow("Range"))

        self.show_no_data()

    def show_no_data(self) -> None:
        self.status_row.clear_value()
        self.range_row.clear_value()

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return

        perception = state.perception
        if perception.obstacle_detected:
            self.status_row.set_value("OBSTACLE", Severity.WARNING)
            self.range_row.set_value(f"{perception.obstacle_distance_m:.2f} m", Severity.WARNING)
        else:
            self.status_row.set_value("CLEAR", Severity.NORMAL)
            self.range_row.set_value(f"{perception.obstacle_distance_m:.2f} m", Severity.NORMAL)
