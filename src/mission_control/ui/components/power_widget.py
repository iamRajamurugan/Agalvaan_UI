"""Power card: battery charge bar, pack voltage, draw, and power state."""

from typing import Optional

from PySide6.QtWidgets import QWidget

from mission_control.telemetry.state import (
    RoverState,
    Severity,
    battery_severity,
)
from mission_control.ui.components.telemetry_primitives import (
    NO_DATA_TEXT,
    BatteryBar,
    MetricRow,
    TelemetryCard,
)

#: Operator wording for each battery severity level (state is never colour-only).
POWER_STATE_TEXT = {
    Severity.NORMAL: "NORMAL",
    Severity.WARNING: "LOW",
    Severity.ERROR: "CRITICAL",
    Severity.OFFLINE: "OFFLINE",
    Severity.NO_DATA: "NO DATA",
}


class PowerWidget(TelemetryCard):
    """Displays battery charge, voltage, current draw, and derived power state."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Power", parent)

        self.charge_row = self.add_row(MetricRow("Battery", emphasis=True))
        self.battery_bar = self.add_row(BatteryBar())
        self.voltage_row = self.add_row(MetricRow("Voltage"))
        self.current_row = self.add_row(MetricRow("Draw"))
        self.state_row = self.add_row(MetricRow("Power state", status=True))

        self.show_no_data()

    def show_no_data(self) -> None:
        self.charge_row.clear_value()
        self.battery_bar.set_percentage(None, Severity.NO_DATA)
        self.voltage_row.clear_value()
        self.current_row.clear_value()
        self.state_row.set_value(POWER_STATE_TEXT[Severity.NO_DATA], Severity.NO_DATA)

    def update_from_state(self, state: RoverState) -> None:
        if not state.has_telemetry:
            self.show_no_data()
            return

        battery = state.battery
        severity = battery_severity(battery, has_telemetry=True)

        self.charge_row.set_value(f"{battery.percentage:.0f}%", severity)
        self.battery_bar.set_percentage(battery.percentage, severity)
        self.voltage_row.set_value(f"{battery.voltage:.1f} V", Severity.NORMAL)
        self.current_row.set_value(f"{battery.current_amps:.1f} A", Severity.NORMAL)
        self.state_row.set_value(POWER_STATE_TEXT[severity], severity)
