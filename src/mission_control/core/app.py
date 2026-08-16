"""Application lifecycle and runtime initialization manager."""

import sys
from typing import Optional
from PySide6.QtWidgets import QApplication

from mission_control.core.config import AppConfig, RoverConfig, load_config
from mission_control.core.logger import setup_logger, get_logger
from mission_control.comms.base_client import BaseCommsClient
from mission_control.comms.mock_client import MockCommsClient
from mission_control.comms.ros2.client import ROS2CommsClient, is_ros2_available
from mission_control.video.worker import VideoWorker
from mission_control.video.source import TestPatternVideoSource, OpenCVVideoSource
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
        self.video_worker: Optional[VideoWorker] = None
        self.main_window: Optional[MainWindow] = None

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
        if self.app_config.mock_mode or not is_ros2_available():
            logger.info("Operating in MOCK MODE (Standalone development).")
            self.comms_client = MockCommsClient()
        else:
            logger.info("ROS 2 environment detected. Initializing ROS2CommsClient...")
            self.comms_client = ROS2CommsClient()

        self.comms_client.start()

        # 6. Initialize Video Subsystem (Standalone Test Pattern by default)
        video_source = TestPatternVideoSource(
            width=self.rover_config.sensors.camera.resolution.width if hasattr(self.rover_config.sensors, "camera") else 1280,
            height=self.rover_config.sensors.camera.resolution.height if hasattr(self.rover_config.sensors, "camera") else 720,
            target_fps=self.rover_config.sensors.camera.target_fps if hasattr(self.rover_config.sensors, "camera") else 30,
        )
        self.video_worker = VideoWorker(video_source=video_source, buffer_capacity=2)

        # 7. Instantiate Main Window
        self.main_window = MainWindow(
            app_config=self.app_config,
            rover_config=self.rover_config,
            comms_client=self.comms_client,
        )

        # 8. Bind Video Worker Signals to Video Player Widget
        if self.video_worker and self.main_window.video_player:
            player = self.main_window.video_player
            self.video_worker.frame_ready.connect(player.handle_frame)
            self.video_worker.stats_updated.connect(player.handle_stats)
            self.video_worker.state_changed.connect(player.handle_state_changed)
            player.stream_start_requested.connect(self.video_worker.start_stream)
            player.stream_stop_requested.connect(self.video_worker.stop_stream)

        return True

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
        if self.video_worker:
            self.video_worker.stop_stream()
        if self.comms_client:
            self.comms_client.stop()
