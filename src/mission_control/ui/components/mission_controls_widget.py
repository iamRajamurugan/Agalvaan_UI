"""Development-only mission controls: phase selection and clock start/pause/reset.

These are MOCK OPERATOR CONTROLS. They drive the Mission Control UI's own run
timeline and countdown; they command nothing on the rover. When the rover reports
its mission phase over ROS 2, this bar becomes a development aid only.
"""

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from mission_control.telemetry.state import MissionPhase

START_TEXT = "▶  START"
PAUSE_TEXT = "❚❚  PAUSE"


class MissionControlsWidget(QWidget):
    """Phase buttons plus mission clock controls, emitted as plain requests."""

    phase_requested = Signal(object)     # MissionPhase
    start_pause_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("MissionBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(8)

        caption = QLabel("MISSION PHASE")
        caption.setObjectName("MissionBarLabel")
        layout.addWidget(caption)

        self.phase_buttons: dict[MissionPhase, QPushButton] = {}
        self._phase_group = QButtonGroup(self)
        self._phase_group.setExclusive(True)

        for phase in MissionPhase:
            button = QPushButton(phase.value)
            button.setObjectName("PhaseButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, p=phase: self.phase_requested.emit(p))
            self._phase_group.addButton(button)
            layout.addWidget(button)
            self.phase_buttons[phase] = button

        self.phase_buttons[MissionPhase.PRE_CHECK].setChecked(True)

        layout.addStretch()

        self.start_pause_btn = QPushButton(START_TEXT)
        self.start_pause_btn.setObjectName("ClockButton")
        self.start_pause_btn.clicked.connect(self.start_pause_requested.emit)
        layout.addWidget(self.start_pause_btn)

        self.reset_btn = QPushButton("↺  RESET")
        self.reset_btn.setObjectName("ClockButton")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        layout.addWidget(self.reset_btn)

        hint = QLabel("DEV MOCK CONTROLS · UI ONLY")
        hint.setObjectName("MockControlsHint")
        layout.addWidget(hint)

    def set_active_phase(self, phase: MissionPhase) -> None:
        """Reflects the phase held in application state (never sets it)."""
        button = self.phase_buttons.get(phase)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_running(self, running: bool) -> None:
        self.start_pause_btn.setText(PAUSE_TEXT if running else START_TEXT)

    def active_phase(self) -> Optional[MissionPhase]:
        for phase, button in self.phase_buttons.items():
            if button.isChecked():
                return phase
        return None
