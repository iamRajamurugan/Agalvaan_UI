"""Deterministic Mock Communication Client for standalone Windows development."""

import time
from typing import Optional
from PySide6.QtCore import QObject, QTimer

from mission_control.comms.base_client import BaseCommsClient
from mission_control.core.logger import get_logger
from mission_control.telemetry.state import ConnectionState, RoverState, MissionMode

logger = get_logger("mock_client")


class MockCommsClient(BaseCommsClient):
    """Mock client providing deterministic state and heartbeat updates for UI development
    without requiring a physical rover, Jetson, or ROS 2 network.
    """

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._heartbeat_timer: Optional[QTimer] = None
        self._state = RoverState(connection_state=ConnectionState.DISCONNECTED)
        self._mock_latency_ms: float = 4.2

    def start(self) -> bool:
        """Initializes mock resources and timers."""
        logger.info("MockCommsClient started in standalone development mode.")
        if self._heartbeat_timer is None:
            self._heartbeat_timer = QTimer(self)
            self._heartbeat_timer.timeout.connect(self._on_heartbeat_tick)
        return True

    def stop(self) -> None:
        """Stops mock timers and clears active session."""
        logger.info("MockCommsClient stopping...")
        if self._heartbeat_timer and self._heartbeat_timer.isActive():
            self._heartbeat_timer.stop()
        self._is_connected = False
        self._connection_state = ConnectionState.DISCONNECTED
        self.connection_state_changed.emit(self._connection_state.value)

    def connect_rover(self) -> bool:
        """Simulates establishing a connection in mock mode."""
        self._is_connected = True
        self._connection_state = ConnectionState.MOCK_MODE
        self._state.connection_state = ConnectionState.MOCK_MODE
        logger.info("MockCommsClient: Connected (MOCK MODE).")
        
        self.connection_state_changed.emit(self._connection_state.value)

        if self._heartbeat_timer is None:
            self._heartbeat_timer = QTimer(self)
            self._heartbeat_timer.timeout.connect(self._on_heartbeat_tick)
        
        if not self._heartbeat_timer.isActive():
            self._heartbeat_timer.start(500)  # 2 Hz heartbeat

        return True

    def disconnect_rover(self) -> None:
        """Simulates disconnecting the session."""
        self._is_connected = False
        self._connection_state = ConnectionState.DISCONNECTED
        self._state.connection_state = ConnectionState.DISCONNECTED
        logger.info("MockCommsClient: Disconnected.")

        if self._heartbeat_timer and self._heartbeat_timer.isActive():
            self._heartbeat_timer.stop()

        self.connection_state_changed.emit(self._connection_state.value)

    def send_drive_command(self, linear_x: float, angular_z: float) -> bool:
        """Simulates receiving a drive command."""
        logger.debug(f"MockCommsClient received drive command: linear_x={linear_x:.2f}, angular_z={angular_z:.2f}")
        self.command_feedback_received.emit("cmd_vel", True)
        return True

    def send_estop(self, enable: bool) -> bool:
        """Simulates emergency stop command dispatch."""
        self._state.is_estopped = enable
        if enable:
            self._state.mission_mode = MissionMode.EMERGENCY_STOP
            logger.warning("MockCommsClient: EMERGENCY STOP ACTIVATED.")
        else:
            self._state.mission_mode = MissionMode.IDLE
            logger.info("MockCommsClient: Emergency Stop reset.")

        self.command_feedback_received.emit("estop", True)
        return True

    def send_mission_mode(self, mode_name: str) -> bool:
        """Simulates requesting a mission mode transition."""
        try:
            mode = MissionMode(mode_name)
            self._state.mission_mode = mode
            logger.info(f"MockCommsClient: Mission mode changed to {mode_name}")
            self.command_feedback_received.emit("mission_mode", True)
            return True
        except ValueError:
            logger.error(f"MockCommsClient: Invalid mission mode '{mode_name}'")
            self.command_feedback_received.emit("mission_mode", False)
            return False

    def _on_heartbeat_tick(self) -> None:
        """Simulates a periodic heartbeat packet from the rover."""
        if not self._is_connected:
            return
        self._state.last_heartbeat_time = time.time()
        self._state.heartbeat_latency_ms = self._mock_latency_ms
        self.heartbeat_received.emit(self._mock_latency_ms)
        self.telemetry_received.emit(self._state)
