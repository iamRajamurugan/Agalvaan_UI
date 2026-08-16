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
3. **Video Decoding Worker Thread (Future Subsystem)**:
   - Ingests incoming video stream (RTSP/WebRTC/CompressedImage).
   - Decodes frames into `QImage` format in a background worker and pushes them to the UI thread via thread-safe signals/buffers.

---

## 5. Subsystems (Current Foundation & Roadmap)

### 5.1 Telemetry & State Management
- `RoverState`: Immutable/thread-safe data container storing:
  - Connection & heartbeat status
  - IMU orientation (roll, pitch, yaw)
  - Odometry & wheel speeds
  - Battery voltage, current, and state of charge
  - Drive and excavation motor states
  - Diagnostics and system alerts

### 5.2 Safety & E-Stop Architecture
- Emergency Stop (E-Stop) has top priority in command dispatch.
- Heartbeat watchdog monitors link status; triggers `LOST LINK` alert if connection drops for $>1000\text{ ms}$.
- Teleoperation dead-man's switch: Commands expire after $500\text{ ms}$ without active operator input.

### 5.3 Live Camera Subsystem (Roadmap)
- 16:9 aspect-ratio video player with YouTube-live style HUD.
- Live stream indicator, FPS/latency tracker, resolution metrics.
- Seamless automatic reconnection logic on packet drops.

### 5.4 Spatial & 4-LiDAR Subsystem (Roadmap)
- Aggregates or switches between 4 perimeter LiDAR sensors mounted around the chassis.
- 2D proximity radar / footprint clearance visualizer.

### 5.5 Mission Timer & Competition Operations
- Official competition run duration: **30 minutes** ($1800\text{ seconds}$).
- Mission state machine tracking (Pre-Check, Manual Teleop, Autonomous Excavation, Dump/Construction, Post-Run).
