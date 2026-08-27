# Rover Mission Control — System Architecture

## 1. System Overview

The Rover Mission Control application is a competition-grade operator station interface for a planetary rover (Lunabotics competition). The system provides command, telemetry monitoring, safety management, visual awareness, and diagnostics for remote manual and autonomous operations.

```
+-------------------------------------------------------------+
|               Mission Control (Windows Laptop)              |
|                                                             |
|   +-----------------------------------------------------+   |
|   |             PySide6 GUI (Qt UI Thread)              |   |
|   +-----------------------------------------------------+   |
|                              | Qt Signals / Slots           |
|   +-----------------------------------------------------+   |
|   |         Communication Abstraction Layer             |   |
|   |          (BaseCommsClient Interface)                |   |
|   +-----------------------------------------------------+   |
|                 /                         \                 |
|   +--------------------------+   +----------------------+   |
|   | MockCommsClient (Worker) |   | ROS2CommsClient      |   |
|   |   (Standalone Dev Mode)  |   | (rclpy QThread)      |   |
|   +--------------------------+   +----------------------+   |
+----------------------------------------------|--------------+
                                               | Local Network
+----------------------------------------------|--------------+
|             Physical Rover (Jetson Orin Nano)               |
|                                                             |
|   +-----------------------------------------------------+   |
|   |         ROS 2 Humble Nodes (Ubuntu 22.04)           |   |
|   +-----------------------------------------------------+   |
|          |                 |                 |              |
|   +--------------+  +---------------+  +----------------+   |
|   | 4x LiDARs    |  | IMU & Encoders|  | Front Camera   |   |
|   +--------------+  +---------------+  +----------------+   |
+-------------------------------------------------------------+
```

---

## 2. Hardware and Environment Targets

- **Mission Control Laptop**:
  - OS: Windows 10/11
  - Runtime: Python 3.10+
  - UI Toolkit: PySide6 (Qt 6)
  - Role: Operator Station (visualization, safety interlocks, teleop commanding, telemetry logging).
- **Rover Onboard Computer**:
  - Hardware: NVIDIA Jetson Orin Nano
  - OS: Ubuntu 22.04 LTS
  - Middleware: ROS 2 Humble Hawksbill
  - Role: Autonomous flight control, motion planning, motor control, sensor acquisition, video encoding.
- **Network Link**:
  - High-speed local wireless / wired Ethernet link.

---

## 3. Communication Abstraction & Modes

To enable agile development and testing on Windows laptops without requiring physical hardware or a local ROS 2 installation, all communications are routed through the `BaseCommsClient` abstraction.

### 3.1 Mode 1: Mock / Standalone Mode (Default Dev Backend)
- Active when running without ROS 2 or without physical rover.
- Deterministic simulation of rover heartbeat, connection state, and telemetry container.
- Guarantees zero runtime dependencies on `rclpy`.

### 3.2 Mode 2: ROS 2 Humble Mode
- Activated when deployed in a ROS 2 environment (or connected to Jetson network).
- Isolated behind `ROS2CommsClient`.
- Uses a background `QThread` to execute ROS 2 executor spins (`rclpy.spin()`), emitting Qt signals upon receiving topic messages.
- Does not block or freeze the PySide6 UI thread.

---

## 4. Threading Principles & Concurrency Model

1. **Qt Main Thread (GUI Thread)**:
   - Dedicated strictly to widget rendering, user interaction, animation, and handling Qt signals.
   - **Zero blocking operations**: Network calls, frame decoding, file I/O, and ROS spin loops are strictly forbidden in this thread.
2. **Communication Worker Thread**:
   - Manages ROS 2 callbacks or Mock telemetry timer.
   - Converts inbound message payloads into thread-safe `RoverState` updates and emits Qt signals to the UI.
   - Updates are written into the lock-guarded `StateManager`; the UI reads independent snapshots
     on the Qt thread at a capped refresh rate, so no widget ever touches shared mutable state.
3. **Video Decoding Worker Thread (Future Subsystem)**:
   - Ingests incoming video stream (RTSP/WebRTC/CompressedImage).
   - Decodes frames into `QImage` format in a background worker and pushes them to the UI thread via thread-safe signals/buffers.

---

## 5. Subsystems (Current Foundation & Roadmap)

### 5.1 Telemetry & State Management (Implemented — Phase 3A)
- `RoverState`: Thread-safe data container storing:
  - Connection & heartbeat status
  - IMU orientation (roll, pitch, yaw)
  - Odometry & wheel speeds
  - Battery voltage, current, and state of charge
  - Drive and excavation motor states
  - Diagnostics and system alerts
  - Sensor group health (`SensorHealthData`: IMU / encoders / LiDAR)
  - Telemetry freshness (`telemetry_valid`, `last_telemetry_time`, `is_stale`)

#### Telemetry data path

```
Comms client (MockCommsClient today, ROS2CommsClient later)
      │  telemetry_received(RoverState)      full rate (mock: 20 Hz)
      ▼
TelemetryBridge (core/telemetry_bridge.py)
      │            ├── StateManager.apply_telemetry()   every packet
      │            ├── StateManager.set_connection_state() / update_heartbeat()
      │            └── invalidate_telemetry() on link loss
      ▼
StateManager (telemetry/state.py)   ← SINGLE SOURCE OF TRUTH
      │  get_snapshot(): independent deep copy; staleness evaluated at read time
      ▼
EventBus.telemetry_updated(RoverState)   throttled to ui_refresh_fps (default 30)
      ▼
MainWindow._on_telemetry_snapshot → TelemetryPanel.update_from_state()
```

Design rules enforced by this path:
1. **UI widgets never own rover state.** They render a snapshot handed to them and hold no
   authoritative values of their own.
2. **The UI never subscribes to a comms client for telemetry.** Only `MainWindow`'s connection
   badge listens to the client lifecycle; all values arrive via the EventBus.
3. **Ingest rate and repaint rate are decoupled.** Telemetry may arrive far faster than 30 Hz;
   the bridge's refresh timer caps repaints so a high-rate real feed cannot flood the UI thread.
4. **`StateManager` stays free of PySide6.** It is plain, lock-guarded Python, so it is unit
   testable and unchanged by the eventual ROS 2 swap.
5. **Telemetry packets cannot rewrite link or safety state.** `apply_telemetry()` merges only
   sensor payload blocks; connection state and E-Stop remain owned by the client lifecycle.

#### Mock telemetry (development only)
`telemetry/mock_generator.py` provides `MockTelemetryGenerator`: deterministic, bounded,
time-varying values built from sine/ramp functions and a seeded jitter source. It exists purely
to develop and validate the UI — it models no rover subsystem, and is simply not instantiated
once a real telemetry source is connected.

#### Severity model
`Severity` (`NORMAL` / `WARNING` / `ERROR` / `OFFLINE` / `NO_DATA`) and the helper functions
`battery_severity`, `latency_severity`, `attitude_severity`, `sensor_severity`, and
`connection_severity` live alongside the state model so every widget applies identical display
rules. Severity is rendered through the Qt dynamic property `severity` in `stylesheet.qss` and
is always accompanied by explicit text, never signalled by colour alone.

### 5.2 Safety & E-Stop Architecture
- Emergency Stop (E-Stop) has top priority in command dispatch.
- Heartbeat watchdog monitors link status; triggers `LOST LINK` alert if connection drops for $>1000\text{ ms}$.
- Teleoperation dead-man's switch: Commands expire after $500\text{ ms}$ without active operator input.

### 5.2b Operator Telemetry UI (Implemented — Phase 3A)
- `ui/components/telemetry_panel.py` assembles five compact cards into a height-capped strip so
  the live camera keeps the majority of the viewport.
- Reusable components: `PowerWidget`, `MotionWidget`, `AttitudeWidget`, `SensorStatusWidget`,
  `ConnectionStatusWidget`, built on shared primitives (`TelemetryCard`, `MetricRow`, `SensorRow`,
  `StatusDot`, `BatteryBar`) in `ui/components/telemetry_primitives.py`.
- Every card implements the same two-method contract: `update_from_state(RoverState)` and
  `show_no_data()`, so missing, stale, or malformed telemetry degrades safely instead of crashing.

### 5.3 Live Camera Subsystem (Roadmap)
- 16:9 aspect-ratio video player with YouTube-live style HUD.
- Live stream indicator, FPS/latency tracker, resolution metrics.
- Seamless automatic reconnection logic on packet drops.

### 5.4 Spatial & 4-LiDAR Subsystem (Roadmap)
- Aggregates or switches between 4 perimeter LiDAR sensors mounted around the chassis.
- 2D proximity radar / footprint clearance visualizer.

### 5.5 Mission Timer & Competition Operations (Implemented — Phase 3B)
- Official competition run duration: **30 minutes** ($1800\text{ seconds}$), read from
  `mission.run_duration_seconds`.
- `core/mission_clock.py` — `MissionClock` counts the run down to zero. Remaining time is
  computed from a monotonic deadline rather than accumulated ticks, so the display cannot
  drift; ticks are emitted only when the displayed second changes. The clock is operator
  station time, not rover telemetry, so it is deliberately **not** routed through
  `StateManager`.
- On expiry the header shows **MISSION COMPLETE** and the timeline closes out at `POST-RUN`.
- `MissionPhase` (Pre-Check, Teleop, Autonomous, Dump, Post-Run) is an ordered label held in
  `StateManager` and rendered from snapshots, consistent with every other state value. It is
  intentionally **not** a state machine: there are no transition rules or guards, because
  nothing in the current scope requires them. The rover will eventually report this field on
  `/mission/state`; until then `MissionControlsWidget` provides development mock controls.
- `MissionPhase` (run timeline) is distinct from `MissionMode` (rover control mode, shown as
  `CTRL MODE` in the Rover Link card).
