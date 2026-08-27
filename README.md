# Rover Mission Control Application

A competition-grade operator interface for a Lunabotics-style planetary rover.

> **Status**: **Phase 3B — Mission Clock & Mission Phase**.
> This repository contains the standalone Mission Control application with an integrated 16:9 YouTube-live style video player, bounded frame buffer, synthetic test pattern generator, a live operator telemetry strip driven by **mock telemetry**, and a competition run countdown with mission phase display.
>
> ⚠️ **No real rover telemetry is connected.** Every value shown in the telemetry panel is generated locally by `MockTelemetryGenerator` for UI development and validation. These are not measurements.

---

## 1. System Overview & Architecture

The Mission Control application runs on a Windows operator laptop and provides command, telemetry monitoring, safety management, visual awareness, and diagnostics for remote manual and autonomous rover operations.

```
+-------------------------------------------------------------------+
|               Mission Control (Windows Laptop)                    |
|                                                                   |
|   +-----------------------------------------------------------+   |
|   |          PySide6 GUI Interface (Qt UI Thread)             |   |
|   |          - LiveVideoPlayerWidget (16:9 YouTube HUD)       |   |
|   |          - TelemetryPanel (Power / Motion / Attitude /    |   |
|   |            Sensors / Rover Link cards)                    |   |
|   +-----------------------------------------------------------+   |
|              ^                                 ^                  |
|              | EventBus.telemetry_updated      |                  |
|              |   (throttled to ~30 FPS)        |                  |
|   +-------------------------------+            |                  |
|   |  StateManager (source of truth)|           |                  |
|   |  <- TelemetryBridge            |           |                  |
|   +-------------------------------+            |                  |
|                    ^                           |                  |
|                    | Qt Signals                | Qt Signals       |
|                    |                           |                  |
|   +-------------------------------+   +-----------------------+   |
|   |   Communication Abstraction   |   | VideoWorker (QThread) |   |
|   |   - MockCommsClient (Default) |   | - Bounded Frame Buffer|   |
|   |   - ROS2CommsClient (Humble)  |   | - Stream Stats Tracker|   |
|   +-------------------------------+   +-----------------------+   |
+--------------------|------------------------------|---------------+
                     | Local Network                | RTSP / UDP
+--------------------|------------------------------|---------------+
|             Physical Rover (NVIDIA Jetson Orin Nano)              |
|             - ROS 2 Humble / Ubuntu 22.04                         |
|             - GStreamer Hardware Encoder (nvv4l2h264enc)          |
|             - MediaMTX RTSP Server (H.264 @ 720p 30 FPS)          |
+-------------------------------------------------------------------+
```

### Key Architectural Principles:
1. **Operator Interface, Not Robot Brain**: The GUI does not directly command hardware or run low-level motor loops. It issues high-level setpoints to onboard ROS 2 nodes.
2. **Communication Abstraction**: All communication flows through `BaseCommsClient`. The default `MockCommsClient` enables full GUI development without ROS 2 or physical hardware.
2b. **Single Source of Truth**: Telemetry never travels from a comms client straight into a widget. It flows `comms client → StateManager → EventBus → telemetry widgets`, so replacing the mock client with a real ROS 2 client requires no UI change.
3. **Dedicated Video Pipeline & Threading**: Video ingestion and frame decoding run in a dedicated `VideoWorker` (`QThread`), completely isolated from the Qt UI thread.
4. **Stale Frame Dropping**: The `BoundedFrameBuffer` (capacity: 2) drops older frames when processing lags, prioritizing lowest operator latency over displaying every stale frame.
5. **YouTube-Live Style Player**: 16:9 aspect ratio locking, 🔴 LIVE status indicator, real-time FPS/latency display, resolution badges, fullscreen mode, and seamless reconnect states.

---

## 2. Prerequisites

- **Python**: `3.10` or higher
- **OS**: Windows 10/11 (or Linux/macOS)

---

## 3. Setup & Installation

### Step 1: Clone the Repository
```powershell
git clone <repository_url>
cd US_ui
```

### Step 2: Create a Local Virtual Environment
```powershell
python -m venv .venv
```

### Step 3: Activate the Virtual Environment
- **Windows (PowerShell)**:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
- **Windows (Command Prompt)**:
  ```cmd
  .\.venv\Scripts\activate.bat
  ```

### Step 4: Install Dependencies
```powershell
pip install -e .
# Or install development dependencies:
pip install -e ".[dev]"
```

*Dependencies:* `PySide6`, `PyYAML`, `numpy`, `opencv-python`, `pytest`.

---

## 4. Running the Application

To launch the Mission Control interface in standalone development mode:

```powershell
python -m mission_control.main
```
Or via the entrypoint script:
```powershell
mission-control
```

- Click **START STREAM** on the video player to begin rendering the live 16:9 synthetic test pattern (radar sweep line, dynamic frame counter, millisecond timestamp, and simulated latency).
- Click **⛶ FULLSCREEN** (or press `Esc`) to enter and exit fullscreen video mode.
- Click **CONNECT MOCK** in the top header to start the mock link, heartbeat, and telemetry stream. The telemetry strip along the bottom begins updating immediately; clicking **DISCONNECT** returns every card to its `--` / `NO DATA` state.

---

## 4a. Mission Clock & Phase (Phase 3B)

The header carries the run countdown as the largest element in the window, next to the
current mission phase:

```
MISSION CLOCK      MISSION PHASE
   29:59             [ TELEOP ]
```

- **Countdown** — counts down from `mission.run_duration_seconds` (1800 s / `30:00` by
  default) in `config/app_config.yaml`. Remaining time is derived from a monotonic
  deadline, so a late timer callback cannot make the clock drift.
- **Severity** — cyan while normal, amber under 5 minutes, red under 1 minute.
- **MISSION COMPLETE** — at `00:00` the caption switches from `MISSION CLOCK` to a red
  **MISSION COMPLETE**, the clock stops, and the phase closes out at `POST-RUN`.
- **Phases** — `PRE-CHECK`, `TELEOP`, `AUTONOMOUS`, `DUMP`, `POST-RUN`. This is a plain
  ordered label with no transition rules, held in `StateManager` like any other state and
  rendered from snapshots — widgets never own it.

### Development mock controls

The strip below the header (`DEV MOCK CONTROLS · UI ONLY`) selects the mission phase and
runs / pauses / resets the clock. **These are UI-side development controls — they command
nothing on the rover.** When the rover reports its phase on `/mission/state`, the same
`StateManager` field is simply written by the comms client instead, and the display is
unchanged.

---

## 4b. Telemetry UI (Phase 3A)

The bottom strip shows five compact cards. All values are **MOCK DATA**.

| Card | Contents |
| :--- | :--- |
| **POWER** | Battery percentage + segmented charge bar, pack voltage, current draw, derived power state (`NORMAL` / `LOW` / `CRITICAL`). |
| **MOTION** | Ground speed (m/s), mean wheel RPM, left/right wheel split, turn rate. |
| **ATTITUDE** | Roll, pitch (signed, with tilt severity), and heading. |
| **SENSORS** | IMU / encoder / LiDAR health with dot **and** text label, plus a Jetson temperature and CPU line. |
| **ROVER LINK** | Connection state, heartbeat health, link latency, and mission mode. |

### Severity levels

`NORMAL`, `WARNING`, `ERROR`, `OFFLINE`, and `NO DATA` are rendered through the Qt dynamic
property `severity` defined in `ui/styles/stylesheet.qss`. Severity is **always** carried by
text as well as colour — a critical battery reads `CRITICAL`, an offline LiDAR reads `OFFLINE`.

### Data flow

```
MockCommsClient (20 Hz, deterministic)
        │  telemetry_received(RoverState)
        ▼
TelemetryBridge ──► StateManager  (single source of truth, thread-safe, Qt-free)
        │                 │
        │                 │ get_snapshot()  (independent deep copy, staleness evaluated on read)
        │                 ▼
        └──────► EventBus.telemetry_updated   (throttled to ui_refresh_fps, default 30 FPS)
                          ▼
                     TelemetryPanel  →  Power / Motion / Attitude / Sensors / Rover Link cards
```

The publish rate and UI cap are independent, and both are configured in `config/app_config.yaml`:

```yaml
telemetry:
  mock_rate_hz: 20        # Mock telemetry publish rate (MOCK DATA ONLY)
  ui_refresh_fps: 30      # Max telemetry widget repaint rate
  stale_timeout_ms: 2000  # Telemetry older than this is shown as STALE
```

### Mock telemetry behaviour

`MockTelemetryGenerator` produces deterministic, bounded, time-varying values — no
uncontrolled randomness — so the interface looks realistic and behaves identically on
every run:

| Channel | Behaviour |
| :--- | :--- |
| Battery | Starts near full and drains linearly (~1.5 %/min) with a small load ripple. |
| Voltage | Derived from charge level across a 7S pack range (21.0–29.4 V), sagging under current draw. |
| Speed | Smooth sine profile in a plausible ~0.09–0.55 m/s band. |
| Wheel RPM | Computed from speed and mock wheel geometry, with a left/right split from the turn rate. |
| Roll / Pitch | Small bounded oscillations (two superimposed sine terms). |
| Yaw | Integrated slow turn rate, wrapped to 0–360°. |
| Latency | Baseline ~4.2 ms with a slow swell and bounded seeded jitter. |
| Sensors | Online, with brief deterministic `DEGRADED` windows for LiDAR (every 47 s) and encoders (every 83 s). |
| Diagnostics | Jetson temperature, CPU, GPU, and RAM as bounded oscillations. |

The generator is stepped by an explicit time delta rather than the wall clock, so tests can
advance it to any point in the profile without sleeping.

### Failure and fallback states

| Condition | UI behaviour |
| :--- | :--- |
| Never connected | Every card shows `--` / `NO DATA`; heartbeat reads `OFFLINE`. |
| Disconnected | Telemetry is invalidated — values are cleared rather than frozen at their last reading. |
| Stale (no packets for `stale_timeout_ms`) | Heartbeat reads `STALE` (warning); readings are withheld instead of being presented as live. |
| Mock mode | Link card reads `MOCK MODE`. |
| Malformed / missing snapshot | Ignored safely; the panel falls back to its no-data state without raising. |

---

## 5. Running Automated Tests

Run the full 90-test pytest suite:

```powershell
pytest
```

---

## 6. Video Subsystem Documentation

Comprehensive technical analysis, Jetson GStreamer pipeline commands, streaming comparison matrices, and network specifications are documented in:
- [`docs/video_architecture.md`](docs/video_architecture.md)

---

## 7. Current Limitations

- **Telemetry is MOCK DATA**: No real rover telemetry is connected. Every value in the telemetry strip comes from `MockTelemetryGenerator` running on the operator laptop. Nothing displayed is a measurement of any physical rover.
- **ROS 2 link**: `ROS2CommsClient` remains an abstraction/stub — it implements the interface and degrades gracefully, but does not yet create a node, publish, or subscribe.
- **Hardware Camera**: Video is currently operating with the local `TestPatternVideoSource` prototype. Live RTSP streaming from the physical Jetson camera will be connected in subsequent phases.
- **LiDAR / Map**: Displays a 2D environment map placeholder. 4-LiDAR pointcloud integration will be added in a later phase.
- **Mission phase is operator-selected**: The phase comes from the development mock controls, not from the rover. There are no transition rules, no automatic progression (other than closing out at `POST-RUN` when the clock expires), and no mission state machine.
- **E-Stop**: Still toggled from the header button and inferred from the safety badge text; a latching, state-backed safety model is a future phase.
- **Excavation telemetry**: `ExcavationData` exists in the model but is not populated or displayed.
