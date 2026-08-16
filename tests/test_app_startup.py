"""Tests for application startup, imports, and UI layout initialization."""

import pytest
from PySide6.QtWidgets import QApplication

from mission_control.core.app import MissionControlApp
from mission_control.core.config import AppConfig, RoverConfig
from mission_control.comms.mock_client import MockCommsClient
from mission_control.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_app_initialization(qapp):
    """Verifies that MissionControlApp initializes cleanly in standalone mode."""
    app = MissionControlApp([])
    initialized = app.initialize()

    assert initialized is True
    assert app.app_config is not None
    assert app.rover_config is not None
    assert app.comms_client is not None
    assert app.main_window is not None

    # Clean shutdown
    app.cleanup()


def test_main_window_structure(qapp):
    """Verifies that MainWindow contains the expected mission control placeholders."""
    app_cfg = AppConfig()
    rover_cfg = RoverConfig()
    client = MockCommsClient()
    client.start()

    window = MainWindow(app_cfg, rover_cfg, client)

    assert window.windowTitle() == app_cfg.ui.window_title
    assert window.connection_badge.text() == "NOT CONNECTED"
    assert window.timer_label.text() == "30:00"
    assert window.telemetry_card.value_label.text() == "NO TELEMETRY"

    # Simulate mock connection toggle in UI
    window.connect_btn.click()
    assert window.connection_badge.text() == "MOCK MODE"
    assert window.connect_btn.text() == "DISCONNECT"

    # Simulate disconnect toggle
    window.connect_btn.click()
    assert window.connection_badge.text() == "NOT CONNECTED"
    assert window.connect_btn.text() == "CONNECT MOCK"

    client.stop()
    window.close()
