"""Configuration loading and data models for application and rover settings."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from mission_control.core.logger import get_logger

logger = get_logger("config")


@dataclass
class UIConfig:
    window_title: str = "Rover Mission Control"
    default_width: int = 1440
    default_height: int = 900
    min_width: int = 1100
    min_height: int = 700
    theme: str = "dark"
    fps_limit: int = 30


@dataclass
class MissionConfig:
    competition_name: str = "Lunabotics Competition"
    run_duration_seconds: int = 1800  # 30 minutes competition run
    teleoperation_timeout_ms: int = 500
    heartbeat_timeout_ms: int = 1000


@dataclass
class TelemetryConfig:
    """Telemetry pipeline rates.

    mock_rate_hz drives the mock publish rate; ui_refresh_fps caps how often the
    telemetry widgets repaint, independently of how fast telemetry arrives.
    """
    mock_rate_hz: int = 20
    ui_refresh_fps: int = 30
    stale_timeout_ms: int = 2000


@dataclass
class AppConfig:
    name: str = "Rover Mission Control"
    version: str = "0.1.0"
    mock_mode: bool = True
    log_level: str = "INFO"
    ui: UIConfig = field(default_factory=UIConfig)
    mission: MissionConfig = field(default_factory=MissionConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)


@dataclass
class ROSTopicsConfig:
    cmd_vel: str = "/cmd_vel"
    heartbeat: str = "/rover/heartbeat"
    imu: str = "/imu/data"
    odometry: str = "/odom"
    joint_states: str = "/joint_states"
    lidar_front: str = "/lidar_front/scan"
    lidar_rear: str = "/lidar_rear/scan"
    lidar_left: str = "/lidar_left/scan"
    lidar_right: str = "/lidar_right/scan"
    camera_image: str = "/camera/image_raw"
    camera_compressed: str = "/camera/image_raw/compressed"
    mission_state: str = "/mission/state"
    diagnostics: str = "/diagnostics"
    estop: str = "/safety/estop"


@dataclass
class ResolutionConfig:
    width: int = 1280
    height: int = 720


@dataclass
class CameraSensorConfig:
    mount: str = "front"
    aspect_ratio: str = "16:9"
    target_fps: int = 30
    resolution: ResolutionConfig = field(default_factory=ResolutionConfig)


@dataclass
class SensorsConfig:
    lidar_count: int = 4
    camera: CameraSensorConfig = field(default_factory=CameraSensorConfig)


@dataclass
class RoverConfig:
    name: str = "Lunabotics Rover"
    computer: str = "NVIDIA Jetson Orin Nano"
    os: str = "Ubuntu 22.04 LTS"
    ros_distro: str = "Humble"
    ros_domain_id: int = 0
    rover_ip: str = "192.168.1.100"
    mission_control_ip: str = "192.168.1.50"
    topics: ROSTopicsConfig = field(default_factory=ROSTopicsConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)


def load_yaml_file(path: Path) -> Dict[str, Any]:
    """Safely loads a YAML file from disk, returning an empty dict on failure."""
    if not path.exists():
        logger.warning(f"Configuration file not found: {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            return content if isinstance(content, dict) else {}
    except Exception as e:
        logger.error(f"Failed to parse configuration file {path}: {e}")
        return {}


def load_app_config(config_dir: Optional[Path] = None) -> AppConfig:
    """Loads AppConfig from YAML or returns defaults."""
    if config_dir is None:
        # Default config directory relative to repo root
        config_dir = Path(__file__).resolve().parents[3] / "config"

    app_path = config_dir / "app_config.yaml"
    data = load_yaml_file(app_path)

    app_section = data.get("app", {})
    ui_section = data.get("ui", {})
    mission_section = data.get("mission", {})
    telemetry_section = data.get("telemetry", {})

    ui_config = UIConfig(
        window_title=ui_section.get("window_title", "Rover Mission Control"),
        default_width=ui_section.get("default_width", 1440),
        default_height=ui_section.get("default_height", 900),
        min_width=ui_section.get("min_width", 1100),
        min_height=ui_section.get("min_height", 700),
        theme=ui_section.get("theme", "dark"),
        fps_limit=ui_section.get("fps_limit", 30),
    )

    mission_config = MissionConfig(
        competition_name=mission_section.get("competition_name", "Lunabotics Competition"),
        run_duration_seconds=mission_section.get("run_duration_seconds", 1800),
        teleoperation_timeout_ms=mission_section.get("teleoperation_timeout_ms", 500),
        heartbeat_timeout_ms=mission_section.get("heartbeat_timeout_ms", 1000),
    )

    telemetry_config = TelemetryConfig(
        mock_rate_hz=telemetry_section.get("mock_rate_hz", 20),
        # Falls back to the shared UI frame cap when not explicitly configured.
        ui_refresh_fps=telemetry_section.get("ui_refresh_fps", ui_config.fps_limit),
        stale_timeout_ms=telemetry_section.get("stale_timeout_ms", 2000),
    )

    return AppConfig(
        name=app_section.get("name", "Rover Mission Control"),
        version=app_section.get("version", "0.1.0"),
        mock_mode=app_section.get("mock_mode", True),
        log_level=app_section.get("log_level", "INFO"),
        ui=ui_config,
        mission=mission_config,
        telemetry=telemetry_config,
    )


def load_rover_config(config_dir: Optional[Path] = None) -> RoverConfig:
    """Loads RoverConfig from YAML or returns defaults."""
    if config_dir is None:
        config_dir = Path(__file__).resolve().parents[3] / "config"

    rover_path = config_dir / "rover_config.yaml"
    data = load_yaml_file(rover_path)

    rover_section = data.get("rover", {})
    network_section = data.get("network", {})
    topics_section = data.get("ros_topics", {})

    topics_config = ROSTopicsConfig(
        cmd_vel=topics_section.get("cmd_vel", "/cmd_vel"),
        heartbeat=topics_section.get("heartbeat", "/rover/heartbeat"),
        imu=topics_section.get("imu", "/imu/data"),
        odometry=topics_section.get("odometry", "/odom"),
        joint_states=topics_section.get("joint_states", "/joint_states"),
        lidar_front=topics_section.get("lidar_front", "/lidar_front/scan"),
        lidar_rear=topics_section.get("lidar_rear", "/lidar_rear/scan"),
        lidar_left=topics_section.get("lidar_left", "/lidar_left/scan"),
        lidar_right=topics_section.get("lidar_right", "/lidar_right/scan"),
        camera_image=topics_section.get("camera_image", "/camera/image_raw"),
        camera_compressed=topics_section.get("camera_compressed", "/camera/image_raw/compressed"),
        mission_state=topics_section.get("mission_state", "/mission/state"),
        diagnostics=topics_section.get("diagnostics", "/diagnostics"),
        estop=topics_section.get("estop", "/safety/estop"),
    )

    sensors_section = data.get("sensors", {})
    camera_data = sensors_section.get("camera", {})
    res_data = camera_data.get("resolution", {})

    camera_config = CameraSensorConfig(
        mount=camera_data.get("mount", "front"),
        aspect_ratio=camera_data.get("aspect_ratio", "16:9"),
        target_fps=camera_data.get("target_fps", 30),
        resolution=ResolutionConfig(
            width=res_data.get("width", 1280),
            height=res_data.get("height", 720),
        ),
    )

    sensors_config = SensorsConfig(
        lidar_count=sensors_section.get("lidar_count", 4),
        camera=camera_config,
    )

    return RoverConfig(
        name=rover_section.get("name", "Lunabotics Rover"),
        computer=rover_section.get("computer", "NVIDIA Jetson Orin Nano"),
        os=rover_section.get("os", "Ubuntu 22.04 LTS"),
        ros_distro=rover_section.get("ros_distro", "Humble"),
        ros_domain_id=rover_section.get("ros_domain_id", 0),
        rover_ip=network_section.get("rover_ip", "192.168.1.100"),
        mission_control_ip=network_section.get("mission_control_ip", "192.168.1.50"),
        topics=topics_config,
        sensors=sensors_config,
    )


def load_config(config_dir: Optional[Path] = None) -> tuple[AppConfig, RoverConfig]:
    """Convenience function to load both AppConfig and RoverConfig."""
    return load_app_config(config_dir), load_rover_config(config_dir)
