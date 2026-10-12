"""Excavation card (bucket position, excavating, dumping) and the auxiliary card."""

from typing import Optional

from PySide6.QtWidgets import QWidget

from mission_control.telemetry.state import RoverState, Severity
from mission_control.ui.components.telemetry_primitives import (
    BatteryBar,
    MetricRow,
    TelemetryCard,
)


def _set_activity(row: MetricRow, active: bool, on_text: str, off_text: str) -> None:
    """Writes an on/off state word: highlighted while active, muted while inactive."""
    if active:
        row.set_value(on_text, Severity.NORMAL)
    else:
        row.set_value(off_text, Severity.OFFLINE)


class ExcavationWidget(TelemetryCard):
    """Displays bucket position (0-100 %) and the excavating / dumping activity."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Excavation", parent)

        self.bucket_row = self.add_row(MetricRow("Bucket", emphasis=True))
        self.bucket_bar = self.add_row(BatteryBar())
        self.excavating_row = self.add_row(MetricRow("Excavating", status=True))
        self.dumping_row = self.add_row(MetricRow("Dumping", status=True))

        self.show_no_data()

    def show_no_data(self) -> None:
        self.bucket_row.clear_value()
        self.bucket_bar.set_percentage(None, Severity.NO_DATA)
        self.excavating_row.clear_value()
        self.dumping_row.clear_value()

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return

        excavation = state.excavation
        position = max(0.0, min(100.0, excavation.bucket_position_pct))
        self.bucket_row.set_value(f"{position:.0f}%", Severity.NORMAL)
        self.bucket_bar.set_percentage(position, Severity.NORMAL)
        _set_activity(self.excavating_row, excavation.is_excavating, "ACTIVE", "IDLE")
        _set_activity(self.dumping_row, excavation.is_dumping, "ACTIVE", "IDLE")


class AuxiliaryWidget(TelemetryCard):
    """Displays auxiliary actuators that belong to no other section."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Other", parent)

        self.vibration_row = self.add_row(MetricRow("Vibration motor", status=True))

        self.show_no_data()

    def show_no_data(self) -> None:
        self.vibration_row.clear_value()

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return
        _set_activity(self.vibration_row, state.excavation.vibration_motor_on, "ON", "OFF")
