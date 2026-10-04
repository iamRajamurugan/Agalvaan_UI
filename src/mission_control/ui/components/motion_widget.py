"""Motion card: linear and angular velocity, direction, and wheel speeds."""

from typing import Optional

from PySide6.QtWidgets import QWidget

from mission_control.telemetry.state import RoverState, Severity
from mission_control.ui.components.telemetry_primitives import (
    MetricRow,
    TelemetryCard,
)


class MotionWidget(TelemetryCard):
    """Displays linear/angular velocity, direction of travel, and wheel speeds."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Motion", parent)

        self.speed_row = self.add_row(MetricRow("Linear", emphasis=True))
        self.turn_row = self.add_row(MetricRow("Angular"))
        self.direction_row = self.add_row(MetricRow("Direction", status=True))
        self.rpm_row, self.wheels_row = self.add_row_pair(
            MetricRow("Wheel RPM"), MetricRow("L / R")
        )

        self.show_no_data()

    def show_no_data(self) -> None:
        self.speed_row.clear_value()
        self.turn_row.clear_value()
        self.direction_row.clear_value()
        self.rpm_row.clear_value()
        self.wheels_row.clear_value()

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return

        drive = state.drive
        self.speed_row.set_value(f"{drive.linear_velocity:.2f} m/s", Severity.NORMAL)
        self.turn_row.set_value(f"{drive.angular_velocity:+.2f} rad/s", Severity.NORMAL)
        direction = drive.direction
        self.direction_row.set_value(
            direction, Severity.OFFLINE if direction == "STOPPED" else Severity.NORMAL
        )
        self.rpm_row.set_value(f"{drive.average_wheel_rpm:.0f} RPM", Severity.NORMAL)
        self.wheels_row.set_value(
            f"{drive.left_wheel_rpm:.0f} / {drive.right_wheel_rpm:.0f}",
            Severity.NORMAL,
        )
