"""Tests for the mission clock/phase UI and its development mock controls."""

import pytest
from PySide6.QtWidgets import QApplication

from mission_control.comms.mock_client import MockCommsClient
from mission_control.core.config import AppConfig, RoverConfig
from mission_control.core.event_bus import EventBus
from mission_control.telemetry.state import MissionPhase, RoverState, StateManager
from mission_control.ui.components.mission_controls_widget import (
    PAUSE_TEXT,
    START_TEXT,
    MissionControlsWidget,
)
from mission_control.ui.components.mission_status_widget import (
    COMPLETE_CAPTION,
    CLOCK_CAPTION,
    MissionStatusWidget,
)
from mission_control.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def window(qapp):
    """A main window with its own isolated state manager and event bus."""
    client = MockCommsClient()
    client.start()
    manager = StateManager()
    bus = EventBus()
    win = MainWindow(AppConfig(), RoverConfig(), client, event_bus=bus, state_manager=manager)

    yield win, manager, bus

    client.stop()
    win.close()


# --- Status widget -------------------------------------------------------


def test_status_widget_shows_configured_duration(qapp):
    widget = MissionStatusWidget(duration_seconds=1800)

    assert widget.clock_label.text() == "30:00"
    assert widget.caption_label.text() == CLOCK_CAPTION
    assert widget.phase_badge.text() == MissionPhase.PRE_CHECK.value
    assert widget.clock_label.property("severity") == "NORMAL"


def test_status_widget_escalates_as_time_runs_out(qapp):
    widget = MissionStatusWidget(duration_seconds=1800)

    widget.set_remaining(900)
    assert widget.clock_label.text() == "15:00"
    assert widget.clock_label.property("severity") == "NORMAL"

    widget.set_remaining(240)  # under 5 minutes
    assert widget.clock_label.property("severity") == "WARNING"

    widget.set_remaining(45)  # under 1 minute
    assert widget.clock_label.text() == "00:45"
    assert widget.clock_label.property("severity") == "ERROR"


def test_status_widget_reports_mission_complete(qapp):
    widget = MissionStatusWidget(duration_seconds=1800)
    widget.set_remaining(0)
    widget.set_complete(True)

    assert widget.caption_label.text() == COMPLETE_CAPTION
    assert widget.clock_label.text() == "00:00"
    assert widget.caption_label.property("severity") == "ERROR"
    assert widget.is_complete is True


def test_status_widget_displays_every_mission_phase(qapp):
    widget = MissionStatusWidget(duration_seconds=1800)

    for phase in MissionPhase:
        widget.set_phase(phase)
        assert widget.phase_badge.text() == phase.value


# --- Mock controls -------------------------------------------------------


def test_controls_request_the_selected_phase(qapp):
    controls = MissionControlsWidget()
    requested = []
    controls.phase_requested.connect(requested.append)

    controls.phase_buttons[MissionPhase.AUTONOMOUS].click()
    controls.phase_buttons[MissionPhase.DUMP].click()

    assert requested == [MissionPhase.AUTONOMOUS, MissionPhase.DUMP]
    # Selection is exclusive: only the latest phase stays checked.
    assert controls.active_phase() == MissionPhase.DUMP
    assert controls.phase_buttons[MissionPhase.AUTONOMOUS].isChecked() is False


def test_controls_expose_all_five_phases(qapp):
    controls = MissionControlsWidget()

    labels = [b.text() for b in controls.phase_buttons.values()]
    assert labels == ["PRE-CHECK", "TELEOP", "AUTONOMOUS", "DUMP", "POST-RUN"]


def test_controls_reflect_clock_running_state(qapp):
    controls = MissionControlsWidget()
    assert controls.start_pause_btn.text() == START_TEXT

    controls.set_running(True)
    assert controls.start_pause_btn.text() == PAUSE_TEXT

    controls.set_running(False)
    assert controls.start_pause_btn.text() == START_TEXT


def test_controls_emit_clock_requests(qapp):
    controls = MissionControlsWidget()
    events = []
    controls.start_pause_requested.connect(lambda: events.append("toggle"))
    controls.reset_requested.connect(lambda: events.append("reset"))

    controls.start_pause_btn.click()
    controls.reset_btn.click()

    assert events == ["toggle", "reset"]


# --- Main window integration ---------------------------------------------


def test_window_starts_at_the_configured_duration_and_phase(window):
    win, manager, _ = window

    assert win.mission_status.clock_label.text() == "30:00"
    assert win.mission_clock.duration_seconds == AppConfig().mission.run_duration_seconds
    assert win.mission_status.phase_badge.text() == MissionPhase.PRE_CHECK.value
    assert manager.get_snapshot().mission_phase == MissionPhase.PRE_CHECK


def test_window_clock_duration_follows_configuration(qapp):
    config = AppConfig()
    config.mission.run_duration_seconds = 600
    client = MockCommsClient()
    client.start()
    win = MainWindow(config, RoverConfig(), client, event_bus=EventBus())

    assert win.mission_status.clock_label.text() == "10:00"

    client.stop()
    win.close()


def test_phase_button_writes_through_state_manager(window):
    """The UI must not own the phase: the button updates state, state drives display."""
    win, manager, _ = window

    win.mission_controls.phase_buttons[MissionPhase.TELEOP].click()

    assert manager.get_snapshot().mission_phase == MissionPhase.TELEOP
    assert win.mission_status.phase_badge.text() == "TELEOP"


def test_phase_from_a_published_snapshot_is_rendered(window):
    """A phase arriving on the EventBus updates both the badge and the controls."""
    win, _, bus = window

    bus.telemetry_updated.emit(RoverState(mission_phase=MissionPhase.AUTONOMOUS))

    assert win.mission_status.phase_badge.text() == "AUTONOMOUS"
    assert win.mission_controls.active_phase() == MissionPhase.AUTONOMOUS


def test_start_button_runs_the_mission_clock(window):
    win, _, _ = window

    win.mission_controls.start_pause_btn.click()
    assert win.mission_clock.is_running is True
    assert win.mission_controls.start_pause_btn.text() == PAUSE_TEXT

    win.mission_controls.start_pause_btn.click()
    assert win.mission_clock.is_running is False
    assert win.mission_controls.start_pause_btn.text() == START_TEXT


def test_countdown_updates_the_header_display(window):
    win, _, _ = window
    win.mission_controls.start_pause_btn.click()

    win.mission_clock.set_remaining_seconds(1234)

    assert win.mission_status.clock_label.text() == "20:34"
    win.mission_clock.pause()


def test_expired_clock_shows_mission_complete_and_closes_the_run(window):
    win, manager, _ = window
    win.mission_controls.start_pause_btn.click()

    win.mission_clock.set_remaining_seconds(0)

    assert win.mission_status.caption_label.text() == COMPLETE_CAPTION
    assert win.mission_status.clock_label.text() == "00:00"
    assert manager.get_snapshot().mission_phase == MissionPhase.POST_RUN
    assert win.mission_status.phase_badge.text() == "POST-RUN"
    assert win.mission_clock.is_running is False


def test_reset_returns_the_window_to_a_fresh_run(window):
    win, manager, _ = window
    win.mission_controls.start_pause_btn.click()
    win.mission_clock.set_remaining_seconds(0)

    win.mission_controls.reset_btn.click()

    assert win.mission_status.clock_label.text() == "30:00"
    assert win.mission_status.caption_label.text() == CLOCK_CAPTION
    assert win.mission_status.clock_label.property("severity") == "NORMAL"
    assert manager.get_snapshot().mission_phase == MissionPhase.PRE_CHECK
    assert win.mission_controls.active_phase() == MissionPhase.PRE_CHECK
    assert win.mission_clock.is_finished is False


def test_mission_ui_does_not_disturb_camera_or_telemetry(window):
    """Phase 3B must leave the existing camera and telemetry widgets intact."""
    win, _, bus = window

    assert win.video_player is not None
    assert win.telemetry_panel is not None

    win.mission_controls.phase_buttons[MissionPhase.DUMP].click()
    bus.telemetry_updated.emit(RoverState(mission_phase=MissionPhase.DUMP))

    # Telemetry still renders its own no-data fallback, camera player untouched.
    assert win.telemetry_panel.power.charge_row.value() == "--"
    assert win.video_player.toggle_stream_btn.text() == "START STREAM"
