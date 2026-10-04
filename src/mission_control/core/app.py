"""Application lifecycle and runtime initialization manager."""

import logging
import sys
from typing import Optional
from PySide6.QtWidgets import QApplication

from mission_control.core.config import AppConfig, RoverConfig, load_config
from mission_control.core.event_bus import EventBus, get_event_bus
from mission_control.core.logger import CallbackLogHandler, setup_logger, get_logger
from mission_control.core.telemetry_bridge import TelemetryBridge
from mission_control.comms.base_client import BaseCommsClient
from mission_control.comms.mock_client import MockCommsClient
from mission_control.comms.ros2.client import ROS2CommsClient, is_ros2_available
from mission_control.telemetry.state import CameraId, MissionMode, StateManager
from mission_control.video.factory import create_camera_source
from mission_control.video.source import BaseVideoSource
from mission_control.video.worker import VideoWorker
from mission_control.ui.main_window import MainWindow
from mission_control.ui.styles import load_stylesheet

logger = get_logger("app")


class MissionControlApp:
    """Encapsulates the complete Mission Control runtime lifecycle."""

    def __init__(self, sys_argv: Optional[list[str]] = None):
        self.argv = sys_argv if sys_argv is not None else sys.argv
        self.app_config: AppConfig
        self.rover_config: RoverConfig
        self.qapp: Optional[QApplication] = None
        self.comms_client: Optional[BaseCommsClient] = None
        self.state_manager: Optional[StateManager] = None
        self.event_bus: Optional[EventBus] = None
        self.telemetry_bridge: Optional[TelemetryBridge] = None
        self.video_worker: Optional[VideoWorker] = None
        self.camera_sources: dict[CameraId, BaseVideoSource] = {}
        self.main_window: Optional[MainWindow] = None
        self._log_handler: Optional[CallbackLogHandler] = None

    def initialize(self) -> bool:
        """Initializes configuration, logging, Qt application, comms, and video pipeline."""
        # 1. Load Configurations
        self.app_config, self.rover_config = load_config()

        # 2. Setup Logging
        setup_logger(level=self.app_config.log_level)
        logger.info(f"Initializing {self.app_config.name} v{self.app_config.version}...")

        # 3. Create QApplication
        self.qapp = QApplication.instance()
        if self.qapp is None:
            self.qapp = QApplication(self.argv)
        self.qapp.setApplicationName(self.app_config.name)

        # 4. Apply Dark Theme Stylesheet
        stylesheet = load_stylesheet()
        if stylesheet:
            self.qapp.setStyleSheet(stylesheet)

        # 5. Initialize Communication Backend
        telemetry_cfg = self.app_config.telemetry

        if self.app_config.mock_mode or not is_ros2_available():
            logger.info("Operating in MOCK MODE (Standalone development).")
            self.comms_client = MockCommsClient(
                telemetry_interval_ms=int(1000 / max(1, telemetry_cfg.mock_rate_hz)),
            )
        else:
            logger.info("ROS 2 environment detected. Initializing ROS2CommsClient...")
            self.comms_client = ROS2CommsClient()

        self.comms_client.start()

        # 5b. Telemetry Pipeline: comms -> StateManager -> EventBus -> UI widgets
        self.event_bus = get_event_bus()
        self.state_manager = StateManager(
            stale_timeout_seconds=telemetry_cfg.stale_timeout_ms / 1000.0,
        )
        # The operator station starts under manual control; autonomy is opt-in.
        self.state_manager.set_mission_mode(MissionMode.MANUAL_TELEOP)
        self.telemetry_bridge = TelemetryBridge(
            comms_client=self.comms_client,
            state_manager=self.state_manager,
            event_bus=self.event_bus,
            refresh_fps=telemetry_cfg.ui_refresh_fps,
        )

        # 6. Initialize Video Subsystem: one source per operator camera, built from
        #    configuration. A single worker streams whichever camera is selected.
        cameras_cfg = self.rover_config.cameras
        self.camera_sources = {
            CameraId.FRONT: create_camera_source(CameraId.FRONT.value, cameras_cfg.front),
            CameraId.REAR: create_camera_source(CameraId.REAR.value, cameras_cfg.rear),
        }
        selected_camera = self.state_manager.get_snapshot().selected_camera
        self.video_worker = VideoWorker(
            video_source=self.camera_sources[selected_camera], buffer_capacity=2
        )

        # 7. Instantiate Main Window
        self.main_window = MainWindow(
            app_config=self.app_config,
            rover_config=self.rover_config,
            comms_client=self.comms_client,
            event_bus=self.event_bus,
            state_manager=self.state_manager,
        )

        # 7a. Mirror application log messages into the operator terminal
        self._log_handler = CallbackLogHandler(self.event_bus.log_message_emitted.emit)
        logging.getLogger("mission_control").addHandler(self._log_handler)
        logger.info("Mission Control ready. All rover data is MOCK DATA.")

        # 7b. Start throttled telemetry publication now that the UI is listening
        self.telemetry_bridge.start()

        # 8. Bind Video Worker Signals to Video Player Widget
        if self.video_worker and self.main_window.video_player:
            player = self.main_window.video_player
            self.video_worker.frame_ready.connect(player.handle_frame)
            self.video_worker.stats_updated.connect(player.handle_stats)
            self.video_worker.state_changed.connect(player.handle_state_changed)
            player.stream_start_requested.connect(self.video_worker.start_stream)
            player.stream_stop_requested.connect(self.video_worker.stop_stream)
            player.camera_requested.connect(self._on_camera_requested)

        return True

    def _on_camera_requested(self, camera: CameraId) -> None:
        """Points the video worker at the source for the camera the operator selected."""
        source = self.camera_sources.get(camera)
        if source is not None and self.video_worker is not None:
            self.video_worker.set_source(source)

    def run(self) -> int:
        """Launches the Qt event loop."""
        if self.main_window is None:
            if not self.initialize():
                return 1
        
        self.main_window.show()
        logger.info("Mission Control Window displayed. Starting Qt event loop.")
        exit_code = self.qapp.exec()
        
        self.cleanup()
        return exit_code

    def cleanup(self) -> None:
        """Performs graceful shutdown of background comms, video workers, and resources."""
        logger.info("Shutting down Mission Control application...")
        if self._log_handler:
            logging.getLogger("mission_control").removeHandler(self._log_handler)
            self._log_handler = None
        if self.video_worker:
            self.video_worker.stop_stream()
        if self.telemetry_bridge:
            self.telemetry_bridge.stop()
        if self.comms_client:
            self.comms_client.stop()
