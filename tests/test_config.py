"""Tests for configuration loading."""

from pathlib import Path
import pytest

from mission_control.core.config import (
    AppConfig,
    RoverConfig,
    load_app_config,
    load_rover_config,
    load_config,
)


def test_load_app_config():
    """Verifies that app_config.yaml loads with valid properties and 30-minute run duration."""
    config_dir = Path(__file__).resolve().parents[1] / "config"
    app_cfg = load_app_config(config_dir)

    assert isinstance(app_cfg, AppConfig)
    assert app_cfg.name == "Rover Mission Control"
    assert app_cfg.mock_mode is True
    # Official competition run duration must be 30 minutes (1800 seconds)
    assert app_cfg.mission.run_duration_seconds == 1800
    assert app_cfg.ui.default_width >= 1100
    assert app_cfg.ui.default_height >= 700


def test_load_rover_config():
    """Verifies that rover_config.yaml loads sensor topics and Jetson hardware targets."""
    config_dir = Path(__file__).resolve().parents[1] / "config"
    rover_cfg = load_rover_config(config_dir)

    assert isinstance(rover_cfg, RoverConfig)
    assert rover_cfg.computer == "NVIDIA Jetson Orin Nano"
    assert rover_cfg.ros_distro == "Humble"
    assert rover_cfg.topics.cmd_vel == "/cmd_vel"
    assert rover_cfg.topics.estop == "/safety/estop"
    assert rover_cfg.topics.heartbeat == "/rover/heartbeat"


def test_load_config_convenience():
    """Verifies that load_config returns both AppConfig and RoverConfig tuples."""
    app_cfg, rover_cfg = load_config()
    assert app_cfg is not None
    assert rover_cfg is not None
