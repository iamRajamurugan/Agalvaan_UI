# Rover Mission Control Application

A competition-grade operator interface for a Lunabotics-style planetary rover.

> **Status**: **Phase 2 — Live Camera Streaming Subsystem (Local Prototype & Architecture)**.
> This repository contains the standalone Mission Control application with an integrated 16:9 YouTube-live style video player, bounded frame buffer, and synthetic test pattern generator.

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
|   |          - Telemetry & Diagnostics Panels                 |   |
|   +-----------------------------------------------------------+   |
|                    |                           |                  |
|                    | Qt Signals                | Qt Signals       |
|                    v                           v                  |
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
- Click **CONNECT MOCK** in the top header to simulate rover connection and heartbeat.

---

## 5. Running Automated Tests

Run the full 25-test pytest suite:

```powershell
pytest
```

---

## 6. Video Subsystem Documentation

Comprehensive technical analysis, Jetson GStreamer pipeline commands, streaming comparison matrices, and network specifications are documented in:
- [`docs/video_architecture.md`](docs/video_architecture.md)

---

## 7. Current Limitations

- **Hardware Camera**: Video is currently operating with the local `TestPatternVideoSource` prototype. Live RTSP streaming from the physical Jetson camera will be connected in subsequent phases.
- **LiDAR / Map**: Displays a 2D environment map placeholder. 4-LiDAR pointcloud integration will be added in Phase 3.
- **Telemetry Sensors**: Displays placeholder units (`--V`, `--°`, `-- RPM`) pending live telemetry message parsing.
