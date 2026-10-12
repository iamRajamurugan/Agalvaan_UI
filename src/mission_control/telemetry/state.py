"""Rover state data models and thread-safe state container."""

import copy
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


class MissionPhase(str, Enum):
    """Segment of the competition run the operator is currently working through.

    This is the run timeline, not a rover control mode (see MissionMode). It is a
    plain ordered label with no transition rules: the operator selects it, and in a
    later phase the rover will report it on /mission/state.
    """
    PRE_CHECK = "PRE-CHECK"
    TELEOP = "TELEOP"
    AUTONOMOUS = "AUTONOMOUS"
    DUMP = "DUMP"
    POST_RUN = "POST-RUN"


class NavigationState(str, Enum):
    """Navigation activity reported by the rover (mock-generated for now)."""
    IDLE = "IDLE"
    MOVING = "MOVING"
    OBSTACLE_DETECTED = "OBSTACLE DETECTED"
    EXCAVATING = "EXCAVATING"
    DUMPING = "DUMPING"
    RETURNING = "RETURNING"
    COMPLETED = "COMPLETED"


class CameraId(str, Enum):
    """Camera feed the operator has selected for the main view."""
    FRONT = "FRONT"
    REAR = "REAR"


class SensorStatus(str, Enum):
    """Reported health of an individual rover sensor group."""
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    """Operator-facing severity level driving telemetry widget styling.

    The enum *name* (NORMAL, WARNING, ERROR, OFFLINE, NO_DATA) is used as the Qt
    dynamic property value matched in stylesheet.qss; the enum *value* is the
    text shown to the operator, so state is never communicated by colour alone.
    """
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"
    NO_DATA = "NO DATA"


# --- Operator display thresholds (presentation only, not rover safety limits) ---
BATTERY_WARNING_PCT = 50.0
BATTERY_ERROR_PCT = 20.0
LATENCY_WARNING_MS = 50.0
LATENCY_ERROR_MS = 150.0
TILT_WARNING_DEG = 15.0
TILT_ERROR_DEG = 25.0
DEFAULT_STALE_TIMEOUT_S = 2.0
DIRECTION_LINEAR_EPS = 0.02   # m/s below which the rover reads as not translating
DIRECTION_ANGULAR_EPS = 0.05  # rad/s below which the rover reads as not turning


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
    energy_consumed_wh: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def power_watts(self) -> float:
        """Instantaneous power consumption derived from voltage and current."""
        return self.voltage * self.current_amps


@dataclass
class DriveData:
    linear_velocity: float = 0.0
    angular_velocity: float = 0.0
    left_wheel_rpm: float = 0.0
    right_wheel_rpm: float = 0.0
    motor_currents: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    timestamp: float = field(default_factory=time.time)

    @property
    def average_wheel_rpm(self) -> float:
        """Mean of the left and right wheel speeds."""
        return (self.left_wheel_rpm + self.right_wheel_rpm) / 2.0

    @property
    def direction(self) -> str:
        """Operator wording for the current motion (positive angular = left)."""
        turning = abs(self.angular_velocity) >= DIRECTION_ANGULAR_EPS
        turn = "LEFT" if self.angular_velocity > 0.0 else "RIGHT"
        if self.linear_velocity >= DIRECTION_LINEAR_EPS:
            return f"FORWARD {turn}" if turning else "FORWARD"
        if self.linear_velocity <= -DIRECTION_LINEAR_EPS:
            return f"REVERSE {turn}" if turning else "REVERSE"
        return f"TURN {turn}" if turning else "STOPPED"


@dataclass
class ExcavationData:
    drum_rpm: float = 0.0
    drum_current_amps: float = 0.0
    arm_extension_pct: float = 0.0
    hopper_weight_kg: float = 0.0
    bucket_position_pct: float = 0.0
    is_excavating: bool = False
    is_dumping: bool = False
    vibration_motor_on: bool = False
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
class SensorHealthData:
    """Reported online/degraded/offline health of the rover sensor groups."""
    imu: SensorStatus = SensorStatus.UNKNOWN
    encoders: SensorStatus = SensorStatus.UNKNOWN
    lidar: SensorStatus = SensorStatus.UNKNOWN
    timestamp: float = field(default_factory=time.time)


@dataclass
class NavigationData:
    """Rover pose and navigation progress. Heading is reported by IMUData.yaw_deg."""
    x_m: float = 0.0
    y_m: float = 0.0
    distance_to_target_m: float = 0.0
    state: NavigationState = NavigationState.IDLE
    timestamp: float = field(default_factory=time.time)


@dataclass
class ObstaclePoint:
    """One nearby obstacle in the rover frame.

    bearing_deg is measured from straight ahead, positive to the rover's left.
    """
    bearing_deg: float = 0.0
    distance_m: float = 0.0


@dataclass
class PerceptionData:
    """Marker detection, TF Mini range-finder status, and nearby obstacles."""
    marker_detected: bool = False
    obstacle_detected: bool = False
    obstacle_distance_m: float = 0.0
    nearby_obstacles: list[ObstaclePoint] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class RoverState:
    """Thread-safe snapshot container of the overall rover state."""
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    mission_mode: MissionMode = MissionMode.IDLE
    mission_phase: MissionPhase = MissionPhase.PRE_CHECK
    selected_camera: CameraId = CameraId.FRONT
    is_estopped: bool = False
    heartbeat_latency_ms: float = 0.0
    last_heartbeat_time: float = 0.0

    imu: IMUData = field(default_factory=IMUData)
    battery: BatteryData = field(default_factory=BatteryData)
    drive: DriveData = field(default_factory=DriveData)
    excavation: ExcavationData = field(default_factory=ExcavationData)
    diagnostics: DiagnosticsData = field(default_factory=DiagnosticsData)
    sensors: SensorHealthData = field(default_factory=SensorHealthData)
    navigation: NavigationData = field(default_factory=NavigationData)
    perception: PerceptionData = field(default_factory=PerceptionData)

    # Telemetry freshness tracking (maintained by StateManager)
    telemetry_valid: bool = False
    last_telemetry_time: float = 0.0
    is_stale: bool = False

    @property
    def has_telemetry(self) -> bool:
        """True only when telemetry has been received and is not stale."""
        return self.telemetry_valid and not self.is_stale


# --------------------------------------------------------------------------
# Severity helpers — display rules live here so every widget agrees on them.
# --------------------------------------------------------------------------

def battery_severity(battery: BatteryData, has_telemetry: bool = True) -> Severity:
    """Maps a battery reading to an operator severity level."""
    if not has_telemetry:
        return Severity.NO_DATA
    if battery.percentage < BATTERY_ERROR_PCT:
        return Severity.ERROR
    if battery.percentage < BATTERY_WARNING_PCT:
        return Severity.WARNING
    return Severity.NORMAL


def latency_severity(latency_ms: float, has_telemetry: bool = True) -> Severity:
    """Maps a link latency measurement to an operator severity level."""
    if not has_telemetry or latency_ms <= 0.0:
        return Severity.NO_DATA
    if latency_ms >= LATENCY_ERROR_MS:
        return Severity.ERROR
    if latency_ms >= LATENCY_WARNING_MS:
        return Severity.WARNING
    return Severity.NORMAL


def attitude_severity(angle_deg: float, has_telemetry: bool = True) -> Severity:
    """Maps a roll/pitch tilt magnitude to an operator severity level."""
    if not has_telemetry:
        return Severity.NO_DATA
    magnitude = abs(angle_deg)
    if magnitude >= TILT_ERROR_DEG:
        return Severity.ERROR
    if magnitude >= TILT_WARNING_DEG:
        return Severity.WARNING
    return Severity.NORMAL


def sensor_severity(status: SensorStatus) -> Severity:
    """Maps a sensor health status to an operator severity level."""
    if status == SensorStatus.ONLINE:
        return Severity.NORMAL
    if status == SensorStatus.DEGRADED:
        return Severity.WARNING
    if status == SensorStatus.OFFLINE:
        return Severity.ERROR
    return Severity.NO_DATA


def navigation_severity(state: NavigationState) -> Severity:
    """Maps a navigation state to an operator severity level."""
    if state == NavigationState.OBSTACLE_DETECTED:
        return Severity.WARNING
    if state == NavigationState.IDLE:
        return Severity.OFFLINE
    return Severity.NORMAL


def connection_severity(state: RoverState) -> Severity:
    """Maps the overall link condition to an operator severity level."""
    if state.connection_state == ConnectionState.DISCONNECTED:
        return Severity.OFFLINE
    if state.connection_state == ConnectionState.LOST_LINK:
        return Severity.ERROR
    if state.is_stale:
        return Severity.WARNING
    if state.connection_state in (ConnectionState.CONNECTED, ConnectionState.MOCK_MODE):
        return Severity.NORMAL
    return Severity.WARNING


class StateManager:
    """Thread-safe manager for reading and updating RoverState.

    This is the single source of truth for the current rover state: communication
    clients write into it, the UI reads independent snapshots out of it. The class
    deliberately has no PySide6/widget dependency, so it stays unit testable and is
    reused unchanged when real ROS 2 telemetry replaces the mock client.
    """

    def __init__(self, stale_timeout_seconds: float = DEFAULT_STALE_TIMEOUT_S):
        self._lock = threading.Lock()
        # The operator station always starts under manual control; autonomy is opt-in.
        self._state = RoverState(mission_mode=MissionMode.MANUAL_TELEOP)
        self._stale_timeout = stale_timeout_seconds

    @property
    def stale_timeout_seconds(self) -> float:
        return self._stale_timeout

    def get_snapshot(self) -> RoverState:
        """Returns an independent deep-copied snapshot of the current rover state.

        Staleness is evaluated at read time, so the UI sees telemetry go stale even
        when no further packets arrive to trigger an update.
        """
        with self._lock:
            snapshot = copy.deepcopy(self._state)

        if snapshot.telemetry_valid and snapshot.last_telemetry_time > 0.0:
            snapshot.is_stale = (time.time() - snapshot.last_telemetry_time) > self._stale_timeout
        else:
            snapshot.is_stale = False
        return snapshot

    def set_connection_state(self, state: ConnectionState) -> None:
        with self._lock:
            self._state.connection_state = state

    def set_mission_mode(self, mode: MissionMode) -> bool:
        """Sets the control mode. Refused (returns False) while the E-Stop is latched,
        so nothing can move the station into an active mode until it is reset."""
        with self._lock:
            if self._state.is_estopped:
                return False
            self._state.mission_mode = mode
            return True

    def set_mission_phase(self, phase: MissionPhase) -> None:
        """Records the current run-timeline phase (operator-selected for now)."""
        with self._lock:
            self._state.mission_phase = phase

    def set_selected_camera(self, camera: CameraId) -> None:
        """Records which camera feed the operator has selected."""
        with self._lock:
            self._state.selected_camera = camera

    def set_estop(self, estopped: bool) -> None:
        """Latches or releases the E-Stop.

        Releasing never resumes the previous mode: the rover drops back to manual
        control so an autonomous run cannot restart without an operator decision.
        """
        with self._lock:
            self._state.is_estopped = estopped
            if estopped:
                self._state.mission_mode = MissionMode.EMERGENCY_STOP
            elif self._state.mission_mode == MissionMode.EMERGENCY_STOP:
                self._state.mission_mode = MissionMode.MANUAL_TELEOP

    def update_heartbeat(self, latency_ms: float = 0.0) -> None:
        with self._lock:
            self._state.last_heartbeat_time = time.time()
            self._state.heartbeat_latency_ms = latency_ms

    def apply_telemetry(self, incoming: RoverState) -> None:
        """Merges an inbound telemetry packet into the managed state.

        Only the sensor payload blocks are copied. Connection and safety fields stay
        owned by the client lifecycle (set_connection_state / set_estop) so a
        telemetry packet can never silently rewrite link or E-Stop status.
        """
        if incoming is None:
            return

        with self._lock:
            self._state.imu = copy.deepcopy(incoming.imu)
            self._state.battery = copy.deepcopy(incoming.battery)
            self._state.drive = copy.deepcopy(incoming.drive)
            self._state.excavation = copy.deepcopy(incoming.excavation)
            self._state.diagnostics = copy.deepcopy(incoming.diagnostics)
            self._state.sensors = copy.deepcopy(incoming.sensors)
            self._state.navigation = copy.deepcopy(incoming.navigation)
            self._state.perception = copy.deepcopy(incoming.perception)

            if incoming.heartbeat_latency_ms > 0.0:
                self._state.heartbeat_latency_ms = incoming.heartbeat_latency_ms
            if incoming.last_heartbeat_time > 0.0:
                self._state.last_heartbeat_time = incoming.last_heartbeat_time

            self._state.telemetry_valid = True
            self._state.last_telemetry_time = time.time()
            self._state.is_stale = False

    def invalidate_telemetry(self) -> None:
        """Marks telemetry as unavailable (link dropped, or client stopped).

        Sensor payloads are reset to defaults so the UI cannot keep presenting the
        last known values as if they were live.
        """
        with self._lock:
            self._state.telemetry_valid = False
            self._state.last_telemetry_time = 0.0
            self._state.is_stale = False
            self._state.heartbeat_latency_ms = 0.0
            self._state.imu = IMUData()
            self._state.battery = BatteryData()
            self._state.drive = DriveData()
            self._state.excavation = ExcavationData()
            self._state.diagnostics = DiagnosticsData()
            self._state.sensors = SensorHealthData()
            self._state.navigation = NavigationData()
            self._state.perception = PerceptionData()
