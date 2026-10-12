# Rover Mission Control Application

A competition operator interface for a Lunabotics-style planetary rover, built with PySide6.

> **Status: operator UI feature-complete, running on mock data.**
>
> ⚠️ **No real rover is connected.** Every telemetry value on screen is generated locally by
> `MockTelemetryGenerator`. The ROS 2 client is a stub: it creates no node, publishes nothing
> and subscribes to nothing. The E-Stop, control mode and mission clock are operator-station
> state only and command no physical hardware.

---

## 1. What is real and what is mock

| Area | Status |
| :--- | :--- |
| Operator UI (header, camera view, navigation, environment, telemetry, terminal) | **Implemented** |
| Telemetry pipeline (comms client → `StateManager` → `EventBus` → widgets) | **Implemented**, fed by mock data |
| All telemetry values (power, motion, pose, navigation state, TF Mini range, obstacles, bucket, vibration motor, marker detection) | **Mock only** (`telemetry/mock_generator.py`) |
| Camera pipeline (worker thread, source switching, reconnect, HUD) | **Implemented** |
| Synthetic camera source | **Implemented** (default picture on a development PC) |
| Intel RealSense D456 colour stream | **Hardware-ready**, optional dependency. Tested against a fake SDK only, not yet against a physical D456 |
| OpenCV / RTSP camera source | **Hardware-ready**, not yet tested against a real stream |
| Rear camera | **Not configured** by default; the view shows `REAR CAMERA OFFLINE` |
| ROS 2 link (`ROS2CommsClient`) | **Stub only** |
| E-Stop, MANUAL / AUTONOMOUS | **UI and application state only**; nothing is sent to a rover |
| Teleoperation, autonomous navigation, SLAM, LiDAR / TF Mini drivers, excavation control | **Not implemented** |

---

## 2. Setup

Requires Python 3.10 or newer (developed on Windows 10/11).

```powershell
git clone <repository_url>
cd US_ui
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Dependencies: `PySide6`, `PyYAML`, `numpy`, `opencv-python`, and `pytest` for development.

Optional, for the RealSense D456 front camera:

```powershell
pip install -e ".[realsense]"
```

Without it the application still runs; the front view falls back to the synthetic pattern.

---

## 3. Running

```powershell
python -m mission_control.main
```

or, after installation, `mission-control`.

Typical session on a development PC:

1. Click **CONNECT MOCK** to start the mock rover link and telemetry.
2. Click **START STREAM** on the camera view.
3. Click **▶ START** in the header to start the mission countdown.

---

## 4. Operator interface

```
+----------------------------------------------------------------------------------+
| TITLE          [LINK STATUS]   MISSION CLOCK  [START]  CONTROL MODE     SAFETY   |
|                [CONNECT]         30:00                 [MANUAL|AUTO]   [E-STOP]  |
+----------------------------------------------------------------------------------+
| [LIVE] [FRONT|REAR]              MARKER: DETECTED  1280x720 | NAVIGATION         |
|                                                             |  > MOVING          |
|                                                             |  X / Y / heading   |
|                  MAIN CAMERA (16:9)                         |  distance to target|
|                                                             +--------------------+
|                                                             | ENVIRONMENT        |
|                                                             |  rover-centric view|
| camera name · source        FPS  latency  [STREAM] [FULL]   |  TF Mini / range   |
+----------------------------------------------------------------------------------+
| POWER            | MOTION            | EXCAVATION          | OTHER               |
+----------------------------------------------------------------------------------+
| > TERMINAL   latest log message                                                  |
+----------------------------------------------------------------------------------+
```

### Header

- **Rover link**: connection status badge above the connect / disconnect button.
- **Mission clock**: counts down from `mission.run_duration_seconds` (30:00 by default). Cyan
  normally, amber under 5 minutes, red under 1 minute, then `MISSION COMPLETE`.
- **▶ START**: the operator starts the run explicitly. Connecting never starts it. While the
  clock runs the button is disabled and reads `RUNNING`, so it cannot be started twice.
  Pause and reset are developer controls (see section 7).
- **Control mode**: `MANUAL` / `AUTONOMOUS`. Startup mode is `MANUAL`. The mode is held in
  `StateManager`, which refuses any change while the E-Stop is latched.
- **E-Stop**: engages on press. Once latched it reads `HOLD TO RESET` and must be held for
  1.5 seconds to release; a click does nothing. Releasing always returns to `MANUAL`.
  Without a real rover link the caption reads `SAFETY · MOCK`, because no physical rover has
  been commanded to stop.

### Camera view

- `FRONT` / `REAR` selector, a stream status badge (`● LIVE`, `CONNECTING`, `RECONNECTING`,
  `OFFLINE`, `NO SIGNAL`, `STREAM ERROR`, `DISCONNECTED`), marker detection status,
  resolution, FPS and latency.
- The bottom bar names the source actually producing the picture, for example
  `SYNTHETIC · D456 UNAVAILABLE` when the RealSense is missing.
- Latency is shown as `(SIM)` for the synthetic source and `LATENCY: UNMEASURED` for real
  sources. No end-to-end latency has been measured.

### Navigation and environment

- **Navigation**: the navigation state as a banner with a distinct shape and word per state
  (`IDLE`, `MOVING`, `OBSTACLE DETECTED`, `EXCAVATING`, `DUMPING`, `RETURNING`, `COMPLETED`),
  then X, Y, heading and distance to target.
- **Environment**: a heading-up, rover-centric view with range rings to 4 m, the TF Mini
  forward range drawn as a beam, and nearby obstacles plotted around the rover. `CLEAR` is a
  thin dashed green beam; `OBSTACLE` is a solid amber bar-capped beam with an amber card
  outline. The TF Mini status and range are also shown as text below.
- This is a status display, not a map. There is no SLAM, path planning or LiDAR processing.

### Telemetry strip

| Section | Contents |
| :--- | :--- |
| **POWER** | Battery % with bar, voltage, current, power (W), energy consumed (Wh), power state |
| **MOTION** | Linear velocity, angular velocity, direction, wheel RPM |
| **EXCAVATION** | Bucket position 0–100 % with bar, excavating, dumping |
| **OTHER** | Vibration motor ON / OFF |

Severity (`NORMAL`, `WARNING`, `ERROR`, `OFFLINE`, `NO DATA`) is always carried by text as well
as colour. When the link drops or telemetry goes stale, values are cleared to `--` rather than
left frozen.

### Terminal

A one-line strip at the bottom shows the latest log message. Clicking **TERMINAL** expands a
small read-only console (120 px) with the recent application log.

---

## 5. Mock mode

`MockCommsClient` publishes a 2 Hz heartbeat and 20 Hz telemetry from
`MockTelemetryGenerator`. The generator is deterministic: every value is a bounded function of
elapsed time with a fixed seed, so each run and each test sees the same profile.

It follows a repeating 120-second script through all seven navigation states. Bucket position,
vibration motor, TF Mini range, marker visibility and nearby obstacles follow that script. The
drive profile is independent of it, so the mock rover can show speed while "excavating".

Rates are set in `config/app_config.yaml`:

```yaml
telemetry:
  mock_rate_hz: 20        # Mock telemetry publish rate
  ui_refresh_fps: 30      # Max widget repaint rate
  stale_timeout_ms: 2000  # Telemetry older than this is treated as stale
```

---

## 6. Camera configuration

Cameras are configured in `config/rover_config.yaml`. Nothing about camera devices or URLs is
hard-coded in the UI.

```yaml
cameras:
  front:
    type: "realsense"            # Intel RealSense D456, colour stream only
    serial: ""                   # Optional device serial; empty = first RealSense found
    width: 1280
    height: 720
    fps: 30
    fallback_to_synthetic: true  # No SDK / no device -> labelled synthetic pattern
  rear:
    type: "none"                 # or "opencv" with a url
    url: ""
    fallback_to_synthetic: false
```

| `type` | Source |
| :--- | :--- |
| `synthetic` | Built-in test pattern |
| `realsense` | Intel RealSense colour stream via `pyrealsense2` (optional dependency) |
| `opencv` | RTSP URL, video file, or device index such as `"0"`, set in `url` |
| `none` | Camera not fitted; the view shows `<NAME> CAMERA OFFLINE` |

Behaviour when hardware is missing:

- **No RealSense SDK or no D456**: with `fallback_to_synthetic: true` the front view shows the
  synthetic pattern, labelled `SYNTHETIC · D456 UNAVAILABLE`. The real camera is retried each
  time the stream starts or reconnects.
- **Rear camera `none`**: the view shows `REAR CAMERA OFFLINE`. The front picture is never
  shown in its place.
- **Signal lost mid-stream**: `NO SIGNAL`, then `RECONNECTING`.

The RealSense source reads a camera attached by USB to the machine running this application.
A camera mounted on the rover has to reach the operator laptop as a network stream (for
example RTSP via `type: "opencv"`). See [`docs/video_architecture.md`](docs/video_architecture.md).

---

## 7. Developer controls

Hidden by default. Press **F12**, or set `ui.show_dev_controls: true` in
`config/app_config.yaml`, to show:

- the mission bar: mission phase buttons and clock start / pause / reset;
- three diagnostics cards in the telemetry strip: Attitude, Sensors and Rover Link.

With the diagnostics cards shown, the telemetry strip is cramped at the 1100 px minimum window
width. They are intended for use on a wider window.

---

## 8. Tests

```powershell
pytest
```

The suite has **175 tests** and needs no camera hardware, RealSense SDK or ROS 2 installation.
For a headless run set `QT_QPA_PLATFORM=offscreen`.

---

## 9. Further documentation

- [`docs/architecture.md`](docs/architecture.md): application architecture and data flow.
- [`docs/video_architecture.md`](docs/video_architecture.md): camera pipeline and the planned
  rover-side streaming design.
- [`src/mission_control/comms/ros2/README.md`](src/mission_control/comms/ros2/README.md): the
  planned ROS 2 topic interface (not implemented).

---

## 10. Current limitations

- All telemetry is mock data; nothing displayed is a measurement.
- `ROS2CommsClient` is a stub. No commands reach a rover: E-Stop, control mode and drive
  commands end at the mock client.
- The RealSense and RTSP camera sources have not been run against real hardware, and no
  end-to-end video latency has been measured.
- There is no teleoperation input, heartbeat watchdog or `LOST LINK` detection yet.
- The mission phase (developer bar) is selected by hand and has no transition rules.
