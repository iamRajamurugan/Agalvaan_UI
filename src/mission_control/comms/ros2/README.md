# ROS 2 Humble Adapter Specification

## Overview

This module provides the interface between the PySide6 Mission Control GUI and the ROS 2 Humble environment running on the rover's NVIDIA Jetson Orin Nano (Ubuntu 22.04).

## Architecture & Threading Model

```
+-------------------------------------------------------------------+
|                     PySide6 UI (Main Thread)                      |
|                 Listens to Qt Signals & Slots                     |
+-------------------------------------------------------------------+
                                ^
                                | Qt Signals (QueuedConnection)
                                v
+-------------------------------------------------------------------+
|                   ROS2WorkerThread (QThread)                      |
|  - Manages rclpy.executors.SingleThreadedExecutor / MultiThreaded |
|  - Dispatches ROS 2 subscription callbacks                        |
|  - Sends ROS 2 publisher messages                                 |
+-------------------------------------------------------------------+
                                ^
                                | DDS Network Transport
                                v
+-------------------------------------------------------------------+
|               NVIDIA Jetson Orin Nano (ROS 2 Humble)              |
+-------------------------------------------------------------------+
```

## Expected Publishers

| Topic Name | Message Type | Rate | Description |
| :--- | :--- | :--- | :--- |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 20 Hz | Manual teleoperation drive setpoints. |
| `/safety/estop` | `std_msgs/msg/Bool` | Event / 10 Hz | Emergency Stop override command. |
| `/mission/cmd` | `std_msgs/msg/String` | Event | Operator mission control commands (e.g., START, PAUSE). |

## Expected Subscribers

| Topic Name | Message Type | Rate | Description |
| :--- | :--- | :--- | :--- |
| `/rover/heartbeat` | `std_msgs/msg/Header` | 5 Hz | Latency measurement and connection watchdog. |
| `/imu/data` | `sensor_msgs/msg/Imu` | 50 Hz | Pitch, roll, yaw, and angular velocity. |
| `/odom` | `nav_msgs/msg/Odometry` | 20 Hz | Rover position and wheel velocity. |
| `/joint_states` | `sensor_msgs/msg/JointState` | 20 Hz | Excavation drum and arm actuator feedback. |
| `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` | 1 Hz | Jetson CPU/GPU load, temps, and error flags. |
| `/lidar_front/scan` | `sensor_msgs/msg/LaserScan` | 10 Hz | Front obstacle detection. |
| `/lidar_rear/scan` | `sensor_msgs/msg/LaserScan` | 10 Hz | Rear obstacle detection. |
| `/lidar_left/scan` | `sensor_msgs/msg/LaserScan` | 10 Hz | Left obstacle detection. |
| `/lidar_right/scan` | `sensor_msgs/msg/LaserScan` | 10 Hz | Right obstacle detection. |
| `/camera/image_raw/compressed` | `sensor_msgs/msg/CompressedImage` | 30 Hz | H.264 / JPEG compressed video stream. |

## Expected Services & Actions

| Service / Action Name | Type | Description |
| :--- | :--- | :--- |
| `/mission/set_mode` | `std_srvs/srv/SetBool` or custom Srv | Switches between Manual, Autonomous, and Excavation. |
| `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Dispatches autonomous navigation goal coordinates. |
| `/excavation/run_sequence` | Custom Action | Triggers automated excavation cycle. |
