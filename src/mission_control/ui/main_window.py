"""Main Window of the Rover Mission Control application."""

from typing import Optional
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSplitter,
    QSizePolicy,
)

from mission_control.core.config import AppConfig, RoverConfig
from mission_control.core.event_bus import EventBus, get_event_bus
from mission_control.core.logger import get_logger
from mission_control.core.mission_clock import MissionClock
from mission_control.comms.base_client import BaseCommsClient
from mission_control.telemetry.state import (
    ConnectionState,
    MissionPhase,
    RoverState,
    StateManager,
)
from mission_control.ui.components.mission_controls_widget import MissionControlsWidget
from mission_control.ui.components.mission_status_widget import MissionStatusWidget
from mission_control.ui.components.telemetry_panel import TelemetryPanel
from mission_control.video.player_widget import LiveVideoPlayerWidget

logger = get_logger("ui.main_window")


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
        # Mission phase is read from and written to application state, never held
        # in a widget. A standalone window without a pipeline gets its own manager.
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

        # 1b. Mission Bar (phase selection + clock controls, development mock)
        self.mission_controls = MissionControlsWidget()
        root_layout.addWidget(self.mission_controls)

        # Content Layout
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(16, 14, 16, 14)
        content_layout.setSpacing(14)

        # 2. Main Visualization Area (Camera + Map Placeholders)
        main_splitter = self._create_main_visualization_area()
        content_layout.addWidget(main_splitter, stretch=4)

        # 3. Bottom Area (Telemetry strip — deliberately height-capped so the
        #    live camera keeps the majority of the viewport)
        bottom_panel = self._create_bottom_panel()
        content_layout.addWidget(bottom_panel, stretch=0)

        root_layout.addWidget(content_container, stretch=1)

    def _create_header_bar(self) -> QWidget:
        """Constructs the top mission control header bar."""
        header = QWidget()
        header.setObjectName("HeaderBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(20)

        # Title Block
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title_label = QLabel("ROVER MISSION CONTROL")
        title_label.setObjectName("AppTitle")
        subtitle_label = QLabel(
            f"{self.rover_config.name.upper()} • {self.app_config.mission.competition_name.upper()}"
        )
        subtitle_label.setObjectName("AppSubtitle")
        title_block.addWidget(title_label)
        title_block.addWidget(subtitle_label)
        layout.addLayout(title_block)

        layout.addStretch()

        # Connection Status Indicator
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

        # Mission Countdown & Phase (competition run duration from configuration)
        self.mission_status = MissionStatusWidget(
            duration_seconds=self.app_config.mission.run_duration_seconds
        )
        layout.addWidget(self.mission_status)

        # Safety / System Status Placeholder
        safety_block = QVBoxLayout()
        safety_block.setSpacing(2)
        safety_title = QLabel("SAFETY STATUS")
        safety_title.setObjectName("CardHeader")
        self.safety_badge = QLabel("READY / STANDBY")
        self.safety_badge.setProperty("class", "Badge BadgeWarning")
        self.safety_badge.setAlignment(Qt.AlignCenter)
        safety_block.addWidget(safety_title)
        safety_block.addWidget(self.safety_badge)
        layout.addLayout(safety_block)

        # Action Buttons
        self.connect_btn = QPushButton("CONNECT MOCK")
        self.connect_btn.setObjectName("PrimaryButton")
        self.connect_btn.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_btn)

        self.estop_btn = QPushButton("E-STOP")
        self.estop_btn.setObjectName("EStopButton")
        self.estop_btn.clicked.connect(self._toggle_estop)
        layout.addWidget(self.estop_btn)

        return header

    def _create_main_visualization_area(self) -> QSplitter:
        """Constructs the central split-view containing Video and Map placeholders."""
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 1. Live Camera Video Player (16:9 Aspect Ratio Locked)
        self.video_player = LiveVideoPlayerWidget(self)
        splitter.addWidget(self.video_player)

        # 2. Environment & LiDAR Map Placeholder
        map_frame = QFrame()
        map_frame.setObjectName("MapPlaceholder")
        map_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        map_layout = QVBoxLayout(map_frame)
        map_layout.setAlignment(Qt.AlignCenter)
        map_layout.setSpacing(8)

        map_title = QLabel("ENVIRONMENT & 4-LiDAR MAP")
        map_title.setObjectName("PlaceholderTitle")
        map_status = QLabel("NO MAP DATA")
        map_status.setProperty("class", "Badge BadgeDisconnected")
        map_status.setAlignment(Qt.AlignCenter)
        map_desc = QLabel("2D Perimeter Obstacle Footprint / Costmap [Pending Setup]")
        map_desc.setObjectName("PlaceholderSubtitle")

        map_layout.addWidget(map_title, alignment=Qt.AlignCenter)
        map_layout.addWidget(map_status, alignment=Qt.AlignCenter)
        map_layout.addWidget(map_desc, alignment=Qt.AlignCenter)
        splitter.addWidget(map_frame)

        # Set initial 60/40 visual balance
        splitter.setSizes([850, 550])
        return splitter

    def _create_bottom_panel(self) -> QWidget:
        """Constructs the operator telemetry strip."""
        self.telemetry_panel = TelemetryPanel()
        self.telemetry_panel.setMaximumHeight(180)
        return self.telemetry_panel

    def _connect_signals(self) -> None:
        """Binds comms lifecycle signals and the EventBus telemetry feed to the UI."""
        self.comms_client.connection_state_changed.connect(self._on_connection_changed)
        self.event_bus.telemetry_updated.connect(self._on_telemetry_snapshot)

        # Mission clock <-> header display
        self.mission_clock.tick.connect(self.mission_status.set_remaining)
        self.mission_clock.finished.connect(self._on_mission_finished)
        self.mission_clock.running_changed.connect(self.mission_controls.set_running)

        # Development mock controls
        self.mission_controls.phase_requested.connect(self._on_phase_requested)
        self.mission_controls.start_pause_requested.connect(self.mission_clock.toggle)
        self.mission_controls.reset_requested.connect(self._on_mission_reset)

        self._render_mission_phase()

    def _on_phase_requested(self, phase: MissionPhase) -> None:
        """Operator selected a mission phase: write it to state, then re-render."""
        self.state_manager.set_mission_phase(phase)
        logger.info(f"Mission phase set to {phase.value} (mock operator control).")
        self._render_mission_phase()

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

    def _render_mission_phase(self, phase: Optional[MissionPhase] = None) -> None:
        """Renders the mission phase held in application state."""
        if phase is None:
            phase = self.state_manager.get_snapshot().mission_phase
        self.mission_status.set_phase(phase)
        self.mission_controls.set_active_phase(phase)

    def _toggle_connection(self) -> None:
        """Handles operator connect/disconnect toggle."""
        if self.comms_client.is_connected:
            self.comms_client.disconnect_rover()
        else:
            self.comms_client.connect_rover()

    def _toggle_estop(self) -> None:
        """Handles emergency stop trigger."""
        is_currently_estopped = (
            self.comms_client.connection_state == ConnectionState.MOCK_MODE
            and self.safety_badge.text() == "EMERGENCY STOP"
        )
        self.comms_client.send_estop(not is_currently_estopped)
        if not is_currently_estopped:
            self.safety_badge.setText("EMERGENCY STOP")
            self.safety_badge.setProperty("class", "Badge BadgeDisconnected")
        else:
            self.safety_badge.setText("READY / STANDBY")
            self.safety_badge.setProperty("class", "Badge BadgeWarning")
        self.safety_badge.style().unpolish(self.safety_badge)
        self.safety_badge.style().polish(self.safety_badge)

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
            self.telemetry_panel.show_no_data()

        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def _on_telemetry_snapshot(self, state_snapshot) -> None:
        """Renders a rover state snapshot published by the TelemetryBridge."""
        if not isinstance(state_snapshot, RoverState):
            self.telemetry_panel.show_no_data()
            return
        self.telemetry_panel.update_from_state(state_snapshot)
        self._render_mission_phase(state_snapshot.mission_phase)
