"""Main Window of the Rover Mission Control application."""

import time
from typing import Optional
from PySide6.QtCore import Qt, QTimer
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
from mission_control.ui.components.telemetry_primitives import ElidedLabel, apply_severity
from mission_control.video.player_widget import LiveVideoPlayerWidget

logger = get_logger("ui.main_window")

ESTOP_TEXT = "E-STOP"
ESTOP_RESET_TEXT = "HOLD TO RESET"
ESTOP_HOLDING_TEXT = "KEEP HOLDING…"
SAFETY_READY_TEXT = "SYSTEM READY"
SAFETY_ESTOP_TEXT = "E-STOP ACTIVE"
MISSION_START_TEXT = "▶  START"
MISSION_RESUME_TEXT = "▶  RESUME"
MISSION_RUNNING_TEXT = "RUNNING"
MISSION_COMPLETE_TEXT = "COMPLETE"

SAFETY_CAPTION = "SAFETY"
# Shown while latched without a real rover link: the latch is station-side only.
SAFETY_MOCK_CAPTION = "SAFETY · MOCK"

#: How long the E-Stop button must be held to release the latch.
ESTOP_RESET_HOLD_MS = 1500

#: Operator-selectable control modes, in display order.
CONTROL_MODES = (
    (MissionMode.MANUAL_TELEOP, "MANUAL"),
    (MissionMode.AUTONOMOUS_NAV, "AUTONOMOUS"),
)

SIDE_PANEL_WIDTH = 250
#: Fixed width of the header's E-Stop column, so latching never shifts the header.
ESTOP_COLUMN_WIDTH = 204
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

        # Releasing the E-Stop takes a deliberate press-and-hold, never a click.
        self.estop_reset_hold_ms = ESTOP_RESET_HOLD_MS
        self._estop_hold_started: Optional[float] = None
        self._estop_hold_timer = QTimer(self)
        self._estop_hold_timer.setInterval(25)
        self._estop_hold_timer.timeout.connect(self._on_estop_hold_tick)

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

        # The header shows the countdown only; the phase is a developer timeline and
        # is visible on the developer mission bar.
        self.mission_status.set_phase_visible(False)
        self.set_dev_controls_visible(self.app_config.ui.show_dev_controls)

    def _create_header_bar(self) -> QWidget:
        """Constructs the top mission control header bar."""
        header = QWidget()
        header.setObjectName("HeaderBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(14)

        # Title Block
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title_label = QLabel("ROVER MISSION CONTROL")
        title_label.setObjectName("AppTitle")
        # The title block takes whatever width the controls leave. In a narrow
        # window the subtitle is shortened before any control is squeezed.
        subtitle_label = ElidedLabel(
            f"{self.rover_config.name.upper()} • {self.app_config.mission.competition_name.upper()}"
        )
        subtitle_label.setObjectName("AppSubtitle")
        title_block.addWidget(title_label)
        title_block.addWidget(subtitle_label)
        layout.addLayout(title_block, stretch=1)

        # Rover connection status over the connect action
        conn_block = QVBoxLayout()
        conn_block.setSpacing(4)
        self.connection_badge = QLabel("NOT CONNECTED")
        self.connection_badge.setProperty("class", "Badge BadgeDisconnected")
        self.connection_badge.setAlignment(Qt.AlignCenter)
        self.connect_btn = QPushButton("CONNECT MOCK")
        self.connect_btn.setObjectName("PrimaryButton")
        self.connect_btn.clicked.connect(self._toggle_connection)
        conn_block.addWidget(self.connection_badge)
        conn_block.addWidget(self.connect_btn)
        layout.addLayout(conn_block)

        # Mission Countdown (competition run duration from configuration)
        self.mission_status = MissionStatusWidget(
            duration_seconds=self.app_config.mission.run_duration_seconds
        )
        layout.addWidget(self.mission_status)

        # Mission START. The only clock control in the operator layout: pause and
        # reset stay on the developer mission bar.
        self.mission_start_btn = QPushButton(MISSION_START_TEXT)
        self.mission_start_btn.setObjectName("MissionStartButton")
        self.mission_start_btn.clicked.connect(self._on_mission_start_requested)
        # Sits on the same baseline as the other header buttons.
        layout.addWidget(self.mission_start_btn, alignment=Qt.AlignBottom)

        # MANUAL / AUTONOMOUS control mode selector
        mode_block = QVBoxLayout()
        mode_block.setSpacing(4)
        mode_title = QLabel("CONTROL MODE")
        mode_title.setObjectName("HeaderCaption")
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

        # Safety status over the Emergency Stop, in one fixed-width column
        safety_column = QWidget()
        safety_column.setFixedWidth(ESTOP_COLUMN_WIDTH)
        safety_block = QVBoxLayout(safety_column)
        safety_block.setContentsMargins(0, 0, 0, 0)
        safety_block.setSpacing(4)
        safety_row = QHBoxLayout()
        safety_row.setSpacing(6)
        self.safety_caption = QLabel(SAFETY_CAPTION)
        self.safety_caption.setObjectName("HeaderCaption")
        self.safety_badge = QLabel(SAFETY_READY_TEXT)
        self.safety_badge.setObjectName("SafetyBadge")
        self.safety_badge.setAlignment(Qt.AlignCenter)
        safety_row.addWidget(self.safety_caption)
        safety_row.addStretch()
        safety_row.addWidget(self.safety_badge)
        safety_block.addLayout(safety_row)

        self.estop_btn = QPushButton(ESTOP_TEXT)
        self.estop_btn.setObjectName("EStopButton")
        # Engages on press (not on release); releasing the latch needs a hold.
        self.estop_btn.pressed.connect(self._on_estop_pressed)
        self.estop_btn.released.connect(self._cancel_estop_reset_hold)
        safety_block.addWidget(self.estop_btn)
        layout.addWidget(safety_column)

        return header

    def _create_main_area(self) -> QHBoxLayout:
        """Constructs the dominant camera view with the navigation column beside it."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 1. Live Camera Video Player (16:9 Aspect Ratio Locked)
        self.video_player = LiveVideoPlayerWidget(self)
        layout.addWidget(self.video_player, stretch=1)

        # 2. Compact Navigation + Environment / TF Mini column
        side_panel = QWidget()
        side_panel.setFixedWidth(SIDE_PANEL_WIDTH)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)

        self.navigation_panel = NavigationWidget()
        self.obstacle_panel = ObstacleWidget()
        self.navigation_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        side_layout.addWidget(self.navigation_panel)
        # The environment view grows into whatever height the column has left.
        side_layout.addWidget(self.obstacle_panel, stretch=1)
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
        self.mission_clock.running_changed.connect(self._render_mission_start)
        self.mission_clock.finished.connect(self._render_mission_start)

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
        self.telemetry_panel.set_diagnostics_visible(visible)

    # -- Operator requests: write to state, then render from state --------------

    def _on_phase_requested(self, phase: MissionPhase) -> None:
        """Operator selected a mission phase: write it to state, then re-render."""
        self.state_manager.set_mission_phase(phase)
        logger.info(f"Mission phase set to {phase.value} (mock operator control).")
        self._render_mission_phase()

    def _on_mode_requested(self, mode: MissionMode) -> None:
        """Operator selected MANUAL or AUTONOMOUS control."""
        if not self.state_manager.set_mission_mode(mode):
            # Refused by application state: the mode is locked while E-Stop is latched.
            logger.warning(f"Control mode change to {mode.value} refused: E-STOP is latched.")
            self._render_operator_state()
            return
        self.comms_client.send_mission_mode(mode.value)
        self.event_bus.mission_state_changed.emit(mode.value)
        logger.info(f"Control mode set to {mode.value}.")
        self._render_operator_state()

    def _on_camera_requested(self, camera: CameraId) -> None:
        """Operator selected the FRONT or REAR camera."""
        self.state_manager.set_selected_camera(camera)
        logger.info(f"Main view switched to {camera.value} camera.")
        self._render_operator_state()

    # -- E-Stop: engage on press, release only by press-and-hold ------------------

    @property
    def _has_real_rover_link(self) -> bool:
        return self.comms_client.connection_state == ConnectionState.CONNECTED

    def _on_estop_pressed(self) -> None:
        """A press engages the E-Stop at once; on a latched E-Stop it starts the hold."""
        if not self.state_manager.get_snapshot().is_estopped:
            self._engage_estop()
            return
        self._estop_hold_started = time.monotonic()
        self.estop_btn.setText(ESTOP_HOLDING_TEXT)
        self._estop_hold_timer.start()

    def _on_estop_hold_tick(self) -> None:
        if self._estop_hold_started is None:
            self._estop_hold_timer.stop()
            return
        held_ms = (time.monotonic() - self._estop_hold_started) * 1000.0
        if held_ms >= self.estop_reset_hold_ms:
            self._estop_hold_started = None
            self._estop_hold_timer.stop()
            self._reset_estop()

    def _cancel_estop_reset_hold(self) -> None:
        """Button released (or pointer left it) before the hold completed."""
        if self._estop_hold_started is None:
            return
        self._estop_hold_started = None
        self._estop_hold_timer.stop()
        if self.state_manager.get_snapshot().is_estopped:
            self.estop_btn.setText(ESTOP_RESET_TEXT)
            logger.info("E-Stop reset cancelled: hold the button to reset.")

    def _engage_estop(self) -> None:
        """Latches the E-Stop in application state."""
        # The command goes out first; the station latch must not wait on anything.
        self.comms_client.send_estop(True)
        self.state_manager.set_estop(True)
        self.event_bus.emergency_stop_triggered.emit(True)
        if self._has_real_rover_link:
            logger.warning("EMERGENCY STOP engaged by operator.")
        else:
            logger.warning(
                "EMERGENCY STOP latched at the operator station. "
                "MOCK / no rover link: no physical rover has been commanded to stop."
            )
        self._render_operator_state()

    def _reset_estop(self) -> None:
        """Releases the latch after a completed hold; control returns to MANUAL."""
        self.comms_client.send_estop(False)
        self.state_manager.set_estop(False)
        self.event_bus.emergency_stop_triggered.emit(False)
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

    def _on_mission_start_requested(self) -> None:
        """Operator started the run. A running or finished clock ignores the request."""
        if self.mission_clock.start():
            logger.info("Mission started by operator.")
        self._render_mission_start()

    def _render_mission_start(self, *_args) -> None:
        """Reflects the clock in the START control; it is only enabled when startable."""
        clock = self.mission_clock
        if clock.is_finished:
            text = MISSION_COMPLETE_TEXT
        elif clock.is_running:
            text = MISSION_RUNNING_TEXT
        elif clock.remaining_seconds < clock.duration_seconds:
            text = MISSION_RESUME_TEXT   # paused from the developer bar
        else:
            text = MISSION_START_TEXT
        self.mission_start_btn.setText(text)
        self.mission_start_btn.setEnabled(not clock.is_running and not clock.is_finished)

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
        self._render_mission_start()

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

        # Without a real rover link the latch is station-side only: say so.
        caption = SAFETY_MOCK_CAPTION if estopped and not self._has_real_rover_link else SAFETY_CAPTION
        if self.safety_caption.text() != caption:
            self.safety_caption.setText(caption)

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
