"""Rover state data models and thread-safe state container."""

from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Optional


class ConnectionState(str, Enum):
    DISCONNECTED = "NOT CONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    LOST_LINK = "LOST LINK"
    MOCK_MODE = "MOCK MODE"


class MissionMode(str, Enum):
    IDLE = "IDLE / STANDBY"
    MANUAL_TELEOP = "MANUAL TELEOP"
    AUTONOMOUS_NAV = "AUTONOMOUS NAV"
    EXCAVATION = "EXCAVATION"
    DUMP_CONSTRUCTION = "DUMP / CONSTRUCTION"
    EMERGENCY_STOP = "EMERGENCY STOP"


@dataclass
class IMUData:
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class BatteryData:
    voltage: float = 0.0
    current_amps: float = 0.0
    percentage: float = 0.0
    cell_temperature_c: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class DriveData:
    linear_velocity: float = 0.0
    angular_velocity: float = 0.0
    left_wheel_rpm: float = 0.0
    right_wheel_rpm: float = 0.0
    motor_currents: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExcavationData:
    drum_rpm: float = 0.0
    drum_current_amps: float = 0.0
    arm_extension_pct: float = 0.0
    hopper_weight_kg: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class DiagnosticsData:
    cpu_usage_pct: float = 0.0
    gpu_usage_pct: float = 0.0
    ram_usage_pct: float = 0.0
    jetson_temp_c: float = 0.0
    last_heartbeat_timestamp: float = 0.0
    active_alerts: list[str] = field(default_factory=list)


@dataclass
class RoverState:
    """Thread-safe snapshot container of the overall rover state."""
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    mission_mode: MissionMode = MissionMode.IDLE
    is_estopped: bool = False
    heartbeat_latency_ms: float = 0.0
    last_heartbeat_time: float = 0.0

    imu: IMUData = field(default_factory=IMUData)
    battery: BatteryData = field(default_factory=BatteryData)
    drive: DriveData = field(default_factory=DriveData)
    excavation: ExcavationData = field(default_factory=ExcavationData)
    diagnostics: DiagnosticsData = field(default_factory=DiagnosticsData)


class StateManager:
    """Thread-safe manager for reading and updating RoverState."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = RoverState()

    def get_snapshot(self) -> RoverState:
        """Returns a shallow-copied snapshot of the current rover state."""
        with self._lock:
            return RoverState(
                connection_state=self._state.connection_state,
                mission_mode=self._state.mission_mode,
                is_estopped=self._state.is_estopped,
                heartbeat_latency_ms=self._state.heartbeat_latency_ms,
                last_heartbeat_time=self._state.last_heartbeat_time,
                imu=self._state.imu,
                battery=self._state.battery,
                drive=self._state.drive,
                excavation=self._state.excavation,
                diagnostics=self._state.diagnostics,
            )

    def set_connection_state(self, state: ConnectionState) -> None:
        with self._lock:
            self._state.connection_state = state

    def set_mission_mode(self, mode: MissionMode) -> None:
        with self._lock:
            self._state.mission_mode = mode

    def set_estop(self, estopped: bool) -> None:
        with self._lock:
            self._state.is_estopped = estopped
            if estopped:
                self._state.mission_mode = MissionMode.EMERGENCY_STOP

    def update_heartbeat(self, latency_ms: float = 0.0) -> None:
        with self._lock:
            self._state.last_heartbeat_time = time.time()
            self._state.heartbeat_latency_ms = latency_ms
