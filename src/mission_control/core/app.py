"""Application lifecycle and runtime initialization manager."""

import sys
from typing import Optional
from PySide6.QtWidgets import QApplication

from mission_control.core.config import AppConfig, RoverConfig, load_config
from mission_control.core.logger import setup_logger, get_logger
from mission_control.comms.base_client import BaseCommsClient
from mission_control.comms.mock_client import MockCommsClient
from mission_control.comms.ros2.client import ROS2CommsClient, is_ros2_available
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
        self.main_window: Optional[MainWindow] = None

    def initialize(self) -> bool:
        """Initializes configuration, logging, Qt application, and comms layer."""
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

        # 6. Instantiate Main Window
        self.main_window = MainWindow(
            app_config=self.app_config,
            rover_config=self.rover_config,
            comms_client=self.comms_client,
        )

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
        """Performs graceful shutdown of background comms and resources."""
        logger.info("Shutting down Mission Control application...")
        if self.comms_client:
            self.comms_client.stop()
