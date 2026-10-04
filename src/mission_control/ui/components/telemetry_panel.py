"""Telemetry strip assembling the operator telemetry cards into one row."""

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from mission_control.telemetry.state import RoverState
from mission_control.ui.components.attitude_widget import AttitudeWidget
from mission_control.ui.components.connection_widget import ConnectionStatusWidget
from mission_control.ui.components.excavation_widget import AuxiliaryWidget, ExcavationWidget
from mission_control.ui.components.motion_widget import MotionWidget
from mission_control.ui.components.power_widget import PowerWidget
from mission_control.ui.components.sensor_status_widget import SensorStatusWidget


class TelemetryPanel(QWidget):
    """Single entry point the main window uses to render a rover state snapshot.

    The panel owns no state of its own: every repaint is driven by a snapshot handed
    in from the StateManager via the EventBus.

    The operator sees four sections (Power, Motion, Excavation, Other). The attitude,
    sensor-health and rover-link cards are engineering diagnostics: they keep
    rendering every snapshot but stay hidden unless diagnostics are switched on.
    """

    def __init__(self, parent: Optional[QWidget] = None, show_diagnostics: bool = False):
        super().__init__(parent)
        self.setObjectName("TelemetryPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.power = PowerWidget()
        self.motion = MotionWidget()
        self.excavation = ExcavationWidget()
        self.auxiliary = AuxiliaryWidget()
        self.attitude = AttitudeWidget()
        self.sensors = SensorStatusWidget()
        self.connection = ConnectionStatusWidget()

        self._operator_cards = (self.power, self.motion, self.excavation, self.auxiliary)
        self._diagnostic_cards = (self.attitude, self.sensors, self.connection)
        self._cards = self._operator_cards + self._diagnostic_cards

        for card in self._cards:
            # The single-row "Other" card needs less width than the dense ones.
            layout.addWidget(card, stretch=2 if card is self.auxiliary else 3)

        self.set_diagnostics_visible(show_diagnostics)

    @property
    def cards(self) -> tuple:
        return self._cards

    @property
    def diagnostics_visible(self) -> bool:
        return not self.attitude.isHidden()

    def set_diagnostics_visible(self, visible: bool) -> None:
        """Shows or hides the engineering diagnostics cards."""
        for card in self._diagnostic_cards:
            card.setVisible(visible)

    def update_from_state(self, state: Optional[RoverState]) -> None:
        """Refreshes every card from a state snapshot; a missing snapshot is safe."""
        if not isinstance(state, RoverState):
            self.show_no_data()
            return
        for card in self._cards:
            card.update_from_state(state)

    def show_no_data(self) -> None:
        """Renders the safe fallback appearance for every card."""
        for card in self._cards:
            card.show_no_data()
