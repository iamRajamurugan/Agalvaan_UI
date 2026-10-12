# Rover Mission Control — System Architecture

This document describes the application **as currently implemented**. The operator UI is
feature-complete and runs entirely on mock data: there is no real rover link. Planned
hardware integration is described only where it shapes the present design, and is marked as
planned.

## 1. System overview

```
+--------------------------------------------------------------------------------+
|                     Mission Control (operator laptop)                          |
|                                                                                |
|   +------------------------------------------------------------------------+   |
|   |                    PySide6 UI  (Qt main thread)                        |   |
|   |  MainWindow: header · camera player · navigation / environment ·       |   |
|   |              telemetry strip · terminal                                |   |
|   +------------------------------------------------------------------------+   |
|        ^ EventBus.telemetry_updated            ^ frame_ready / state_changed   |
|        |  (snapshots, max 30 FPS)              |  (newest frame only)          |
|   +---------------------------+        +-----------------------------------+   |
|   | StateManager              |        | VideoWorker (QThread)             |   |
|   |  single source of truth   |        |  one worker, swappable source     |   |
|   +---------------------------+        +-----------------------------------+   |
|        ^ TelemetryBridge                       ^ BaseVideoSource               |
|   +---------------------------+        +-----------------------------------+   |
|   | BaseCommsClient           |        | Synthetic · RealSense · OpenCV ·  |   |
|   |  MockCommsClient (used)   |        | Offline · Fallback                |   |
|   |  ROS2CommsClient (stub)   |        +-----------------------------------+   |
|   +---------------------------+                                                |
+--------------------------------------------------------------------------------+
            :  planned: ROS 2 / DDS               :  planned: RTSP from the rover
+--------------------------------------------------------------------------------+
|        Rover (NVIDIA Jetson Orin Nano, ROS 2 Humble) — NOT CONNECTED           |
+--------------------------------------------------------------------------------+
```

| Layer | Location |
| :--- | :--- |
| Entry point and lifecycle | `main.py`, `core/app.py` (`MissionControlApp`) |
| Configuration | `core/config.py`, `config/app_config.yaml`, `config/rover_config.yaml` |
| Communication | `comms/base_client.py`, `comms/mock_client.py`, `comms/ros2/client.py` |
| State model | `telemetry/state.py` (`RoverState`, `StateManager`, severity helpers) |
| Mock data | `telemetry/mock_generator.py` |
| Bridge and event bus | `core/telemetry_bridge.py`, `core/event_bus.py` |
| Mission clock | `core/mission_clock.py` |
| UI | `ui/main_window.py`, `ui/components/`, `ui/styles/stylesheet.qss` |
| Video | `video/` (worker, sources, factory, frame buffer, stats, player widget) |

## 2. Targets

- **Operator laptop**: Windows 10/11, Python 3.10+, PySide6 (Qt 6).
- **Rover (planned)**: NVIDIA Jetson Orin Nano, Ubuntu 22.04, ROS 2 Humble. Not connected to
  this application today.

## 3. Communication layer

All rover communication goes through the `BaseCommsClient` interface (connection lifecycle,
heartbeat and telemetry signals, and `send_drive_command` / `send_estop` /
`send_mission_mode`).

- **`MockCommsClient`** is the only working backend. It publishes a 2 Hz heartbeat and 20 Hz
  telemetry from `MockTelemetryGenerator` and accepts commands without acting on anything.
- **`ROS2CommsClient`** is a stub. It satisfies the interface and degrades gracefully when
  `rclpy` is missing, but it creates no node and neither publishes nor subscribes. The
  planned topic interface is listed in `comms/ros2/README.md`.

`app.mock_mode: true` (the default) selects the mock client.

## 4. State and telemetry data path

```
Comms client (MockCommsClient)
      │  telemetry_received(RoverState)          full rate (20 Hz)
      ▼
TelemetryBridge
      │   ├── StateManager.apply_telemetry()     every packet
      │   ├── set_connection_state() / update_heartbeat()
      │   └── invalidate_telemetry() on link loss
      ▼
StateManager                                     SINGLE SOURCE OF TRUTH
      │  get_snapshot(): independent deep copy; staleness evaluated on read
      ▼
EventBus.telemetry_updated(RoverState)           throttled to ui_refresh_fps (30)
      ▼
MainWindow._on_telemetry_snapshot → cards, navigation, environment, camera HUD
```

Rules this path enforces:

1. **Widgets never own rover state.** They render the snapshot they are given.
2. **The UI never reads telemetry from a comms client.** Only the connection badge listens to
   the client lifecycle; all values arrive through the `EventBus`.
3. **Ingest rate and repaint rate are decoupled** by the bridge's refresh timer.
4. **`StateManager` has no Qt dependency.** It is lock-guarded plain Python.
5. **Telemetry packets cannot rewrite operator-station state.** `apply_telemetry()` merges
   only the sensor payload blocks.

### 4.1 `RoverState` contents

| Block | Fields |
| :--- | :--- |
| Link | `connection_state`, heartbeat latency and time, telemetry freshness (`telemetry_valid`, `is_stale`) |
| Operator-station state | `mission_mode`, `is_estopped`, `selected_camera`, `mission_phase` |
| `imu` | roll, pitch, yaw |
| `battery` | voltage, current, percentage, energy consumed; power is derived |
| `drive` | linear and angular velocity, wheel RPM; direction is derived |
| `excavation` | bucket position, excavating, dumping, vibration motor |
| `navigation` | x, y, distance to target, `NavigationState` |
| `perception` | marker detected, TF Mini obstacle flag and range, nearby obstacles (bearing and distance in the rover frame) |
| `diagnostics`, `sensors` | Jetson load and temperature; IMU / encoder / LiDAR health |

Operator-station state is written by the UI through `StateManager` setters and rendered back
from snapshots. It is never inferred from widget text.

### 4.2 Mock telemetry

`MockTelemetryGenerator` produces deterministic, bounded values from sine and ramp functions
of elapsed time and a seeded jitter source. It is stepped by an explicit time delta, so tests
advance it without sleeping. A repeating 120-second script drives the navigation state, with
bucket position, vibration motor, TF Mini range, marker visibility and nearby obstacles
following it. It models no real subsystem and is simply not instantiated once a real
telemetry source exists.

### 4.3 Severity model

`Severity` (`NORMAL`, `WARNING`, `ERROR`, `OFFLINE`, `NO_DATA`) and the helper functions in
`telemetry/state.py` give every widget the same display rules. Severity is applied through
the Qt dynamic property `severity`, styled in `stylesheet.qss`, and is always accompanied by
text or a shape, never colour alone.

## 5. User interface

`MainWindow` assembles five regions:

| Region | Widgets |
| :--- | :--- |
| Header | title, connection badge and connect button, `MissionStatusWidget` (countdown), mission START, MANUAL / AUTONOMOUS selector, safety badge and E-Stop |
| Camera | `LiveVideoPlayerWidget` (see section 6) |
| Side column (250 px) | `NavigationWidget`, `ObstacleWidget` containing `EnvironmentView` |
| Telemetry strip (max 180 px) | `TelemetryPanel`: `PowerWidget`, `MotionWidget`, `ExcavationWidget`, `AuxiliaryWidget` |
| Terminal | `LogConsoleWidget` |

Every telemetry card implements the same contract: `update_from_state(RoverState)` and
`show_no_data()`. Missing, stale or malformed telemetry therefore degrades to `--` instead of
raising or showing frozen values.

All styling lives in `ui/styles/stylesheet.qss`. Only the custom-painted widgets
(`BatteryBar`, `StatusDot`, `EnvironmentView`, the video canvas) hold colours in Python,
because `QPainter` cannot read QSS rules.

### 5.1 Mission clock

`MissionClock` counts the configured run duration down to zero. Remaining time is computed
from a monotonic deadline rather than accumulated ticks, so the display cannot drift. It is
operator-station time, not rover telemetry, and is deliberately not routed through
`StateManager`.

The operator starts the run with the header START button. The clock never starts on
connection, and a running or finished clock ignores further start requests. Pause and reset
exist only on the developer mission bar.

### 5.2 Control mode and E-Stop

- Startup mode is `MANUAL`, set when `StateManager` is created.
- `StateManager.set_mission_mode()` refuses a change while the E-Stop is latched, so the lock
  does not depend on the selector buttons being disabled.
- The E-Stop engages on button press. Releasing it requires holding the button for 1.5
  seconds; the release always returns the mode to `MANUAL`.
- In mock mode, or with no link, the latch is station-side only. The header caption and the
  log say so explicitly. A latching, rover-acknowledged safety chain is future work.

### 5.3 Navigation and environment

`NavigationWidget` shows the navigation state as a banner (a distinct glyph and word per
state) with pose and target distance below.

`EnvironmentView` is a heading-up, rover-centric painted view: range rings to 4 m, world-axis
markers on the rim to show orientation, the TF Mini forward range as a beam, and nearby
obstacles plotted from their rover-frame bearing and distance. It holds only the last
snapshot it was given. It is a status display: there is no map, SLAM, costmap or LiDAR
processing in this application. When its card is too short to draw it usefully, the view is
hidden and the TF Mini status and range remain as text.

### 5.4 Terminal

`CallbackLogHandler` forwards the application's log records to
`EventBus.log_message_emitted`, and `LogConsoleWidget` displays them. Collapsed, it is a
one-line strip showing the latest message.

### 5.5 Developer controls

`ui.show_dev_controls` (or F12 at runtime) shows `MissionControlsWidget` (mission phase
buttons, clock start / pause / reset) and three diagnostics cards (`AttitudeWidget`,
`SensorStatusWidget`, `ConnectionStatusWidget`). They are hidden from the operator layout by
default but keep rendering every snapshot.

`MissionPhase` (Pre-Check, Teleop, Autonomous, Dump, Post-Run) is a developer timeline label
with no transition rules. It is distinct from `MissionMode`, the control mode.

## 6. Camera subsystem

```
config/rover_config.yaml  cameras.front / cameras.rear
        │
        ▼
video/factory.create_camera_source()      one source object per camera
        │
        ▼
VideoWorker (QThread)  ── set_source() ──  swaps source on FRONT / REAR selection
        │  reads frames, converts to QImage
        ▼
BoundedFrameBuffer (capacity 2)           oldest frame dropped when full
        │  one queued wake-up at a time
        ▼
UI thread takes the newest frame  →  LiveVideoPlayerWidget
```

Sources (`video/source.py`), all behind `BaseVideoSource`:

| Source | Purpose |
| :--- | :--- |
| `TestPatternVideoSource` | Synthetic pattern for development; labelled with the camera name |
| `RealSenseVideoSource` | Intel RealSense D456 colour stream. `pyrealsense2` is imported only when the stream is opened |
| `OpenCVVideoSource` | RTSP URL, file or local device index |
| `OfflineVideoSource` | A camera that is not configured; never produces frames |
| `FallbackVideoSource` | Tries a preferred source and falls back to a stand-in, retrying the preferred one on every open |

Behaviour:

- **One worker serves both cameras.** Selecting FRONT or REAR sets a pending source; the
  running thread closes the old source and opens the new one. The UI thread never blocks on
  a camera switch.
- **Stream states**: `CONNECTING`, `LIVE`, `NO SIGNAL`, `RECONNECTING`, `STREAM ERROR`,
  `OFFLINE` (camera not configured, not retried) and `DISCONNECTED` (stopped by the operator).
- **Stale frames are dropped, not queued.** The worker pushes into the bounded buffer and
  queues at most one wake-up; the UI thread drains the buffer and displays only the newest
  frame.
- **No depth, point-cloud or detection processing** is performed. Marker detection status
  shown in the HUD comes from mock telemetry.

Rover-side streaming (GStreamer, MediaMTX, RTSP) is planned and described in
`docs/video_architecture.md`. None of it has been run against hardware.

## 7. Threading model

1. **Qt main thread**: all widgets, the mock client's timers, the telemetry bridge and the
   mission clock. No blocking I/O.
2. **`VideoWorker` thread**: opening sources, reading and converting frames, reconnect
   back-off.
3. **`StateManager`** is lock-guarded so a future ROS 2 worker thread can write into it while
   the UI reads snapshots.

## 8. Not implemented

ROS 2 nodes and topics, teleoperation input, heartbeat watchdog and `LOST LINK` detection,
autonomous navigation, SLAM, LiDAR and TF Mini drivers, excavation and motor control, and
telemetry recording. The interfaces above are designed to receive that data, but none of it
exists yet.

## 9. Tests

`pytest` runs 175 tests covering configuration, the state model, the mock generator, the
telemetry pipeline, every UI card, the operator layout, E-Stop and mode safety, the mission
clock, and the camera pipeline (using a fake RealSense SDK). No hardware, RealSense SDK or
ROS 2 installation is required.
