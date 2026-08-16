# Rover Mission Control Application

A competition-grade operator interface for a Lunabotics-style planetary rover.

> **Status**: **Phase 1 — Clean Foundation & Architecture**.
> This repository contains the standalone Mission Control application foundation. It is **NOT** yet connected to physical rover hardware or live video cameras.

---

## 1. System Overview & Architecture

The Mission Control application runs on a Windows operator laptop and provides command, telemetry monitoring, safety management, visual awareness, and diagnostics for remote manual and autonomous rover operations.

```
+-------------------------------------------------------------------+
|               Mission Control (Windows Laptop)                    |
|                                                                   |
|   +-----------------------------------------------------------+   |
|   |          PySide6 GUI Interface (Qt UI Thread)             |   |
|   +-----------------------------------------------------------+   |
|                                 | Qt Signals / Slots              |
|   +-----------------------------------------------------------+   |
|   |               Communication Abstraction                   |   |
|   |              (BaseCommsClient Interface)                  |   |
|   +-----------------------------------------------------------+   |
|                     /                       \                     |
|   +-------------------------------+   +-----------------------+   |
|   |   MockCommsClient (Default)   |   | ROS2CommsClient       |   |
|   | (Standalone Local Dev Backend)|   | (rclpy QThread Worker)|   |
|   +-------------------------------+   +-----------------------+   |
+---------------------------------------------------|---------------+
                                                    | Local Network
+---------------------------------------------------|---------------+
|             Physical Rover (NVIDIA Jetson Orin Nano)              |
|                   ROS 2 Humble / Ubuntu 22.04                     |
+-------------------------------------------------------------------+
```

### Key Architectural Principles:
1. **Operator Interface, Not Robot Brain**: The GUI does not directly command hardware or run low-level motor loops. It issues high-level setpoints to onboard ROS 2 nodes.
2. **Communication Abstraction**: All communication flows through `BaseCommsClient`. The default `MockCommsClient` enables full GUI development without ROS 2 or physical hardware.
3. **Zero UI Thread Blocking**: Telemetry ingestion, video decoding, and ROS executor spins run in dedicated background `QThread` workers, emitting thread-safe Qt Signals to the UI.
4. **Safety Watchdog & E-Stop**: Watchdog monitoring with automatic "LOST LINK" handling, dead-man's switch timeouts, and emergency stop interlocks.

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
- **Linux / macOS**:
  ```bash
  source .venv/bin/activate
  ```

### Step 4: Install Dependencies
```powershell
pip install -e .
# Or install development dependencies:
pip install -e ".[dev]"
```

*Initial minimal dependencies:* `PySide6`, `PyYAML`, `pytest`.

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

---

## 5. Running Automated Tests

Run the full pytest test suite:

```powershell
pytest
```

---

## 6. Development Workflow & Mock Mode

By default, `app_config.yaml` has `mock_mode: true`.

- When launched in Mock Mode, the application operates with the `MockCommsClient`.
- Clicking **CONNECT MOCK** establishes a simulated link, starts a periodic 2 Hz heartbeat, and updates UI status badges without requiring ROS 2 or network access.
- Clicking **E-STOP** simulates emergency stop dispatch and safety state transitions.

---

## 7. Future ROS 2 Integration

When deploying to an environment connected to the rover's Jetson Orin Nano:
1. Ensure the ROS 2 Humble environment is sourced (`local_setup.ps1` or WSL2/Linux bridge).
2. Set `mock_mode: false` in `config/app_config.yaml`.
3. The application will dynamically utilize `ROS2CommsClient` to spin subscribers and publishers across the DDS network.

---

## 8. Current Limitations

- **Video Stream**: Displays a 16:9 placeholder. The low-latency hardware-accelerated video decoding worker will be implemented in the video subsystem phase.
- **LiDAR / Map**: Displays a 2D environment map placeholder. 4-LiDAR pointcloud integration will be added in subsequent phases.
- **Telemetry Sensors**: Displays explicit placeholder states (`NO TELEMETRY`, `--V`, `--°`) rather than live sensor readings.
