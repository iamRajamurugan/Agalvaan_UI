"""Main Window of the Rover Mission Control application."""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from mission_control.core.config import AppConfig, RoverConfig
from mission_control.core.event_bus import EventBus, get_event_bus
from mission_control.core.logger import get_logger
from mission_control.core.mission_clock import MissionClock
from mission_control.comms.base_client import BaseCommsClient
from mission_control.telemetry.state import (
    CameraId,
    ConnectionState,
    MissionMode,
    MissionPhase,
    RoverState,
    Severity,
    StateManager,
)
from mission_control.ui.components.log_console_widget import LogConsoleWidget
from mission_control.ui.components.mission_controls_widget import MissionControlsWidget
from mission_control.ui.components.mission_status_widget import MissionStatusWidget
from mission_control.ui.components.navigation_widget import NavigationWidget, ObstacleWidget
from mission_control.ui.components.telemetry_panel import TelemetryPanel
from mission_control.ui.components.telemetry_primitives import apply_severity
from mission_control.video.player_widget import LiveVideoPlayerWidget

logger = get_logger("ui.main_window")

ESTOP_TEXT = "E-STOP"
ESTOP_RESET_TEXT = "RESET E-STOP"
SAFETY_READY_TEXT = "SYSTEM READY"
SAFETY_ESTOP_TEXT = "E-STOP ACTIVE"

#: Operator-selectable control modes, in display order.
CONTROL_MODES = (
    (MissionMode.MANUAL_TELEOP, "MANUAL"),
    (MissionMode.AUTONOMOUS_NAV, "AUTONOMOUS"),
)

SIDE_PANEL_WIDTH = 250
TELEMETRY_STRIP_MAX_HEIGHT = 180


class MainWindow(QMainWindow):
    """Primary Mission Control Operator Interface Window."""

    def __init__(
        self,
        app_config: AppConfig,
        rover_config: RoverConfig,
        comms_client: BaseCommsClient,
        parent: Optional[QWidget] = None,
        event_bus: Optional[EventBus] = None,
        state_manager: Optional[StateManager] = None,
    ):
        super().__init__(parent)
        self.app_config = app_config
        self.rover_config = rover_config
        self.comms_client = comms_client
        # Telemetry reaches the UI only through the EventBus, never straight from
        # the comms client, so the state layer stays the single source of truth.
        self.event_bus = event_bus if event_bus is not None else get_event_bus()
        # Mission phase, control mode, E-Stop and camera selection are read from and
        # written to application state, never held in a widget. A standalone window
        # without a pipeline gets its own manager.
        self.state_manager = state_manager if state_manager is not None else StateManager()

        # The run countdown is operator-station time, not rover telemetry.
        self.mission_clock = MissionClock(
            duration_seconds=app_config.mission.run_duration_seconds,
            parent=self,
        )

        self._init_window()
        self._setup_ui()
        self._connect_signals()

    def _init_window(self) -> None:
        """Sets window properties from application configuration."""
        self.setWindowTitle(self.app_config.ui.window_title)
        self.resize(
            self.app_config.ui.default_width,
            self.app_config.ui.default_height,
        )
        self.setMinimumSize(
            self.app_config.ui.min_width,
            self.app_config.ui.min_height,
        )

    def _setup_ui(self) -> None:
        """Assembles the layout hierarchy."""
        central_widget = QWidget(self)
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Header Bar
        header = self._create_header_bar()
        root_layout.addWidget(header)

        # 1b. Mission Bar (phase selection + clock controls). Developer-only:
        #     hidden from the operator layout unless dev controls are enabled.
        self.mission_controls = MissionControlsWidget()
        root_layout.addWidget(self.mission_controls)

        # Content Layout
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(12)

        # 2. Main Area (dominant camera + compact navigation column)
        content_layout.addLayout(self._create_main_area(), stretch=1)

        # 3. Bottom Area (Telemetry strip — deliberately height-capped so the
        #    live camera keeps the majority of the viewport)
        bottom_panel = self._create_bottom_panel()
        content_layout.addWidget(bottom_panel, stretch=0)

        root_layout.addWidget(content_container, stretch=1)

        # 4. Terminal (collapsed to a thin strip by default)
        self.log_console = LogConsoleWidget()
        root_layout.addWidget(self.log_console)

        self.set_dev_controls_visible(self.app_config.ui.show_dev_controls)

    def _create_header_bar(self) -> QWidget:
        """Constructs the top mission control header bar."""
        header = QWidget()
        header.setObjectName("HeaderBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(16)

        # Title Block
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title_label = QLabel("ROVER MISSION CONTROL")
        title_label.setObjectName("AppTitle")
        subtitle_label = QLabel(
            f"{self.rover_config.name.upper()} • {self.app_config.mission.competition_name.upper()}"
        )
        subtitle_label.setObjectName("AppSubtitle")
        # The title takes whatever width the controls leave and is clipped first,
        # so a narrow window never squeezes the operator controls.
        for label in (title_label, subtitle_label):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_block.addWidget(title_label)
        title_block.addWidget(subtitle_label)
        layout.addLayout(title_block, stretch=1)

        # Rover connection status + connect action
        conn_block = QVBoxLayout()
        conn_block.setSpacing(2)
        conn_label_title = QLabel("ROVER LINK")
        conn_label_title.setObjectName("CardHeader")
        self.connection_badge = QLabel("NOT CONNECTED")
        self.connection_badge.setProperty("class", "Badge BadgeDisconnected")
        self.connection_badge.setAlignment(Qt.AlignCenter)
        conn_block.addWidget(conn_label_title)
        conn_block.addWidget(self.connection_badge)
        layout.addLayout(conn_block)

        self.connect_btn = QPushButton("CONNECT MOCK")
        self.connect_btn.setObjectName("PrimaryButton")
        self.connect_btn.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_btn)

        # Mission Countdown (competition run duration from configuration)
        self.mission_status = MissionStatusWidget(
            duration_seconds=self.app_config.mission.run_duration_seconds
        )
        layout.addWidget(self.mission_status)

        # MANUAL / AUTONOMOUS control mode selector
        mode_block = QVBoxLayout()
        mode_block.setSpacing(2)
        mode_title = QLabel("CONTROL MODE")
        mode_title.setObjectName("CardHeader")
        mode_block.addWidget(mode_title)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        self.mode_buttons: dict[MissionMode, QPushButton] = {}
        for mode, text in CONTROL_MODES:
            button = QPushButton(text)
            button.setObjectName("ModeButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, m=mode: self._on_mode_requested(m))
            mode_row.addWidget(button)
            self.mode_buttons[mode] = button
        mode_block.addLayout(mode_row)
        layout.addLayout(mode_block)

        # Safety status + Emergency Stop
        safety_block = QVBoxLayout()
        safety_block.setSpacing(2)
        safety_title = QLabel("SAFETY")
        safety_title.setObjectName("CardHeader")
        self.safety_badge = QLabel(SAFETY_READY_TEXT)
        self.safety_badge.setObjectName("SafetyBadge")
        self.safety_badge.setAlignment(Qt.AlignCenter)
        safety_block.addWidget(safety_title)
        safety_block.addWidget(self.safety_badge)
        layout.addLayout(safety_block)

        self.estop_btn = QPushButton(ESTOP_TEXT)
        self.estop_btn.setObjectName("EStopButton")
        self.estop_btn.clicked.connect(self._toggle_estop)
        layout.addWidget(self.estop_btn)

        return header

    def _create_main_area(self) -> QHBoxLayout:
        """Constructs the dominant camera view with the navigation column beside it."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 1. Live Camera Video Player (16:9 Aspect Ratio Locked)
        self.video_player = LiveVideoPlayerWidget(self)
        layout.addWidget(self.video_player, stretch=1)

        # 2. Compact Navigation + TF Mini obstacle column
        side_panel = QWidget()
        side_panel.setFixedWidth(SIDE_PANEL_WIDTH)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)

        self.navigation_panel = NavigationWidget()
        self.obstacle_panel = ObstacleWidget()
        for card in (self.navigation_panel, self.obstacle_panel):
            card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        side_layout.addWidget(self.navigation_panel)
        side_layout.addWidget(self.obstacle_panel)
        side_layout.addStretch()
        layout.addWidget(side_panel)

        return layout

    def _create_bottom_panel(self) -> QWidget:
        """Constructs the operator telemetry strip."""
        self.telemetry_panel = TelemetryPanel()
        self.telemetry_panel.setMaximumHeight(TELEMETRY_STRIP_MAX_HEIGHT)
        return self.telemetry_panel

    def _connect_signals(self) -> None:
        """Binds comms lifecycle signals and the EventBus telemetry feed to the UI."""
        self.comms_client.connection_state_changed.connect(self._on_connection_changed)
        self.event_bus.telemetry_updated.connect(self._on_telemetry_snapshot)
        self.event_bus.log_message_emitted.connect(self.log_console.append_message)

        # Mission clock <-> header display
        self.mission_clock.tick.connect(self.mission_status.set_remaining)
        self.mission_clock.finished.connect(self._on_mission_finished)
        self.mission_clock.running_changed.connect(self.mission_controls.set_running)

        # Development mock controls
        self.mission_controls.phase_requested.connect(self._on_phase_requested)
        self.mission_controls.start_pause_requested.connect(self.mission_clock.toggle)
        self.mission_controls.reset_requested.connect(self._on_mission_reset)

        # Camera selection
        self.video_player.camera_requested.connect(self._on_camera_requested)

        # F12 reveals the developer mission bar and diagnostics cards.
        self._dev_shortcut = QShortcut(QKeySequence(Qt.Key_F12), self)
        self._dev_shortcut.activated.connect(
            lambda: self.set_dev_controls_visible(not self.dev_controls_visible)
        )

        self._render_operator_state()

    # -- Developer controls ----------------------------------------------------

    @property
    def dev_controls_visible(self) -> bool:
        return not self.mission_controls.isHidden()

    def set_dev_controls_visible(self, visible: bool) -> None:
        """Shows or hides everything that is not part of the operator layout."""
        self.mission_controls.setVisible(visible)
        self.mission_status.set_phase_visible(visible)
        self.telemetry_panel.set_diagnostics_visible(visible)

    # -- Operator requests: write to state, then render from state --------------

    def _on_phase_requested(self, phase: MissionPhase) -> None:
        """Operator selected a mission phase: write it to state, then re-render."""
        self.state_manager.set_mission_phase(phase)
        logger.info(f"Mission phase set to {phase.value} (mock operator control).")
        self._render_mission_phase()

    def _on_mode_requested(self, mode: MissionMode) -> None:
        """Operator selected MANUAL or AUTONOMOUS control."""
        if self.state_manager.get_snapshot().is_estopped:
            # The mode is locked while the E-Stop is latched.
            self._render_operator_state()
            return
        self.state_manager.set_mission_mode(mode)
        self.comms_client.send_mission_mode(mode.value)
        self.event_bus.mission_state_changed.emit(mode.value)
        logger.info(f"Control mode set to {mode.value}.")
        self._render_operator_state()

    def _on_camera_requested(self, camera: CameraId) -> None:
        """Operator selected the FRONT or REAR camera."""
        self.state_manager.set_selected_camera(camera)
        logger.info(f"Main view switched to {camera.value} camera.")
        self._render_operator_state()

    def _toggle_estop(self) -> None:
        """Latches or releases the E-Stop held in application state."""
        engage = not self.state_manager.get_snapshot().is_estopped
        # The command goes out first; the station latch must not wait on anything.
        self.comms_client.send_estop(engage)
        self.state_manager.set_estop(engage)
        self.event_bus.emergency_stop_triggered.emit(engage)
        if engage:
            logger.warning("EMERGENCY STOP engaged by operator.")
        else:
            # Releasing drops to manual control; tell the rover the same.
            self.comms_client.send_mission_mode(MissionMode.MANUAL_TELEOP.value)
            logger.info("Emergency Stop reset. Control mode returned to MANUAL.")
        self._render_operator_state()

    def _toggle_connection(self) -> None:
        """Handles operator connect/disconnect toggle."""
        if self.comms_client.is_connected:
            self.comms_client.disconnect_rover()
        else:
            self.comms_client.connect_rover()

    # -- Mission clock ----------------------------------------------------------

    def _on_mission_finished(self) -> None:
        """Run duration elapsed: show MISSION COMPLETE and close out the timeline."""
        self.mission_status.set_complete(True)
        self.state_manager.set_mission_phase(MissionPhase.POST_RUN)
        self._render_mission_phase()

    def _on_mission_reset(self) -> None:
        """Returns the clock to full duration and the timeline to PRE-CHECK."""
        self.mission_clock.reset()
        self.mission_status.set_complete(False)
        self.mission_status.set_remaining(self.mission_clock.remaining_seconds)
        self.state_manager.set_mission_phase(MissionPhase.PRE_CHECK)
        self._render_mission_phase()

    # -- Rendering ---------------------------------------------------------------

    def _render_mission_phase(self, phase: Optional[MissionPhase] = None) -> None:
        """Renders the mission phase held in application state."""
        if phase is None:
            phase = self.state_manager.get_snapshot().mission_phase
        self.mission_status.set_phase(phase)
        self.mission_controls.set_active_phase(phase)

    def _render_operator_state(self, state: Optional[RoverState] = None) -> None:
        """Renders phase, control mode, E-Stop and camera selection from state."""
        if state is None:
            state = self.state_manager.get_snapshot()

        self._render_mission_phase(state.mission_phase)

        estopped = state.is_estopped
        for mode, button in self.mode_buttons.items():
            button.setChecked(not estopped and state.mission_mode == mode)
            button.setEnabled(not estopped)

        if self.estop_btn.property("engaged") != estopped:
            self.estop_btn.setProperty("engaged", estopped)
            self.estop_btn.setText(ESTOP_RESET_TEXT if estopped else ESTOP_TEXT)
            self.estop_btn.style().unpolish(self.estop_btn)
            self.estop_btn.style().polish(self.estop_btn)
            self.safety_badge.setText(SAFETY_ESTOP_TEXT if estopped else SAFETY_READY_TEXT)
            apply_severity(self.safety_badge, Severity.ERROR if estopped else Severity.NORMAL)

        self.video_player.set_camera(state.selected_camera)

    def _show_no_telemetry(self) -> None:
        """Drops every telemetry display to its safe no-data presentation."""
        self.telemetry_panel.show_no_data()
        self.navigation_panel.show_no_data()
        self.obstacle_panel.show_no_data()
        self.video_player.show_no_data()

    def _on_connection_changed(self, state_str: str) -> None:
        """Updates UI elements when connection state changes."""
        self.connection_badge.setText(state_str)
        if state_str == ConnectionState.MOCK_MODE.value:
            self.connection_badge.setProperty("class", "Badge BadgeMock")
            self.connect_btn.setText("DISCONNECT")
        elif state_str == ConnectionState.CONNECTED.value:
            self.connection_badge.setProperty("class", "Badge BadgeConnected")
            self.connect_btn.setText("DISCONNECT")
        else:
            self.connection_badge.setProperty("class", "Badge BadgeDisconnected")
            self.connect_btn.setText("CONNECT MOCK")
            # Link is down: drop straight to the safe no-telemetry presentation
            # instead of leaving the last received values on screen.
            self._show_no_telemetry()

        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def _on_telemetry_snapshot(self, state_snapshot) -> None:
        """Renders a rover state snapshot published by the TelemetryBridge."""
        if not isinstance(state_snapshot, RoverState):
            self._show_no_telemetry()
            return
        self.telemetry_panel.update_from_state(state_snapshot)
        self.navigation_panel.update_from_state(state_snapshot)
        self.obstacle_panel.update_from_state(state_snapshot)
        self.video_player.update_from_state(state_snapshot)
        self._render_operator_state(state_snapshot)
