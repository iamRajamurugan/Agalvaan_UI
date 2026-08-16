"""ROS 2 Humble Client Adapter.

This module provides the integration point for ROS 2 Humble communications.
To protect standalone Windows development, rclpy is imported dynamically
and only initialized if the ROS 2 environment is active and available.
"""

from typing import Optional
from PySide6.QtCore import QObject

from mission_control.comms.base_client import BaseCommsClient
from mission_control.core.logger import get_logger
from mission_control.telemetry.state import ConnectionState

logger = get_logger("ros2_client")


def is_ros2_available() -> bool:
    """Checks whether rclpy can be safely imported in the current environment."""
    try:
        import rclpy  # noqa: F401
        return True
    except (ImportError, ModuleNotFoundError):
        return False
    except Exception as e:
        logger.debug(f"ROS 2 environment probe returned: {e}")
        return False


class ROS2CommsClient(BaseCommsClient):
    """ROS 2 Humble communications adapter.
    
    In future phases, this class will manage an rclpy Node inside a dedicated
    QThread worker to spin and process ROS 2 subscriptions and publishers.
    """

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._ros_available = is_ros2_available()

    @property
    def ros_available(self) -> bool:
        """Returns True if rclpy is present in the runtime environment."""
        return self._ros_available

    def start(self) -> bool:
        """Initializes ROS 2 node context if rclpy is available."""
        if not self._ros_available:
            logger.info(
                "ROS 2 environment (rclpy) is not present. "
                "ROS2CommsClient will remain in standby/placeholder mode."
            )
            return False

        logger.info("Initializing ROS 2 Humble node context...")
        # Note: In future phase, initialize rclpy.init() and launch QThread worker
        return True

    def stop(self) -> None:
        """Shuts down ROS 2 node and background executor."""
        logger.info("Stopping ROS 2 client adapter...")
        self._is_connected = False
        self._connection_state = ConnectionState.DISCONNECTED
        self.connection_state_changed.emit(self._connection_state.value)

    def connect_rover(self) -> bool:
        """Attempts to connect to the rover over the ROS 2 DDS network."""
        if not self._ros_available:
            logger.warning(
                "Cannot connect to ROS 2: rclpy is not installed/configured on this system. "
                "Switch to Mock Mode in app_config.yaml for standalone development."
            )
            self.error_occurred.emit("ROS 2 (rclpy) is unavailable on this host.")
            return False

        # In future phase, verify heartbeat topic reception
        return True

    def disconnect_rover(self) -> None:
        """Disconnects active ROS 2 session."""
        self._is_connected = False
        self._connection_state = ConnectionState.DISCONNECTED
        self.connection_state_changed.emit(self._connection_state.value)

    def send_drive_command(self, linear_x: float, angular_z: float) -> bool:
        """Publishes geometry_msgs/msg/Twist to /cmd_vel."""
        if not self._ros_available or not self._is_connected:
            return False
        # Future phase: publish to self._cmd_vel_pub
        return True

    def send_estop(self, enable: bool) -> bool:
        """Publishes std_msgs/msg/Bool to /safety/estop."""
        if not self._ros_available:
            return False
        # Future phase: publish to self._estop_pub
        return True

    def send_mission_mode(self, mode_name: str) -> bool:
        """Invokes ROS 2 Service to change mission mode."""
        if not self._ros_available:
            return False
        # Future phase: call service client
        return True
