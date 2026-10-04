"""Tests for the operator layout: E-Stop, control mode, navigation, excavation, terminal."""

import pytest
from PySide6.QtWidgets import QApplication

from mission_control.comms.mock_client import MockCommsClient
from mission_control.core.config import AppConfig, RoverConfig
from mission_control.core.event_bus import EventBus
from mission_control.telemetry.mock_generator import (
    NAV_CYCLE_S,
    TFMINI_OBSTACLE_THRESHOLD_M,
    MockTelemetryGenerator,
)
from mission_control.telemetry.state import (
    BatteryData,
    CameraId,
    ConnectionState,
    DriveData,
    ExcavationData,
    IMUData,
    MissionMode,
    NavigationData,
    NavigationState,
    PerceptionData,
    RoverState,
    StateManager,
)
from mission_control.ui.components.telemetry_primitives import NO_DATA_TEXT
from mission_control.ui.main_window import (
    ESTOP_RESET_TEXT,
    ESTOP_TEXT,
    SAFETY_ESTOP_TEXT,
    SAFETY_READY_TEXT,
    MainWindow,
)
from mission_control.video.player_widget import (
    MARKER_DETECTED_TEXT,
    MARKER_NO_DATA_TEXT,
    MARKER_NOT_DETECTED_TEXT,
)


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


def live_state(**overrides) -> RoverState:
    """A snapshot carrying live telemetry for the operator-layout fields."""
    fields = dict(
        connection_state=ConnectionState.MOCK_MODE,
        imu=IMUData(yaw_deg=137.5),
        battery=BatteryData(
            voltage=25.0, current_amps=8.0, percentage=80.0, energy_consumed_wh=12.34
        ),
        drive=DriveData(linear_velocity=0.40, angular_velocity=0.20),
        excavation=ExcavationData(bucket_position_pct=65.0, is_excavating=True),
        navigation=NavigationData(
            x_m=3.25, y_m=-1.5, distance_to_target_m=2.75, state=NavigationState.MOVING
        ),
        perception=PerceptionData(marker_detected=True, obstacle_distance_m=2.4),
        telemetry_valid=True,
        last_telemetry_time=1.0,
    )
    fields.update(overrides)
    return RoverState(**fields)


# --- State layer -----------------------------------------------------------


def test_estop_release_returns_to_manual_never_autonomous():
    manager = StateManager()
    manager.set_mission_mode(MissionMode.AUTONOMOUS_NAV)

    manager.set_estop(True)
    assert manager.get_snapshot().mission_mode == MissionMode.EMERGENCY_STOP

    manager.set_estop(False)
    snapshot = manager.get_snapshot()
    assert snapshot.is_estopped is False
    assert snapshot.mission_mode == MissionMode.MANUAL_TELEOP


def test_new_telemetry_blocks_are_merged_and_invalidated():
    manager = StateManager()
    manager.set_selected_camera(CameraId.REAR)
    manager.set_estop(True)

    manager.apply_telemetry(live_state())
    snapshot = manager.get_snapshot()
    assert snapshot.navigation.state == NavigationState.MOVING
    assert snapshot.perception.marker_detected is True
    assert snapshot.excavation.bucket_position_pct == pytest.approx(65.0)
    # A telemetry packet never rewrites operator-station state.
    assert snapshot.selected_camera == CameraId.REAR
    assert snapshot.is_estopped is True

    manager.invalidate_telemetry()
    cleared = manager.get_snapshot()
    assert cleared.navigation.state == NavigationState.IDLE
    assert cleared.perception.marker_detected is False
    assert cleared.selected_camera == CameraId.REAR
    assert cleared.is_estopped is True


@pytest.mark.parametrize(
    "linear, angular, expected",
    [
        (0.40, 0.00, "FORWARD"),
        (0.40, 0.20, "FORWARD LEFT"),
        (-0.30, -0.20, "REVERSE RIGHT"),
        (0.00, -0.30, "TURN RIGHT"),
        (0.00, 0.00, "STOPPED"),
    ],
)
def test_direction_is_derived_from_velocities(linear, angular, expected):
    assert DriveData(linear_velocity=linear, angular_velocity=angular).direction == expected


# --- Mock generator --------------------------------------------------------


def test_generator_walks_every_navigation_state_consistently():
    generator = MockTelemetryGenerator()
    packets = [generator.advance(0.5) for _ in range(int(NAV_CYCLE_S * 2))]

    assert {p.navigation.state for p in packets} == set(NavigationState)
    for packet in packets:
        excavation, perception = packet.excavation, packet.perception
        assert 0.0 <= excavation.bucket_position_pct <= 100.0
        assert excavation.is_excavating == (packet.navigation.state == NavigationState.EXCAVATING)
        assert excavation.is_dumping == (packet.navigation.state == NavigationState.DUMPING)
        assert excavation.vibration_motor_on == excavation.is_dumping
        assert perception.obstacle_detected == (
            perception.obstacle_distance_m < TFMINI_OBSTACLE_THRESHOLD_M
        )
        assert packet.navigation.distance_to_target_m >= 0.0
    assert any(p.perception.marker_detected for p in packets)
    assert any(not p.perception.marker_detected for p in packets)


def test_generator_accumulates_energy_and_resets_it():
    generator = MockTelemetryGenerator()
    first = generator.advance(60.0).battery
    later = generator.advance(60.0).battery

    assert first.energy_consumed_wh > 0.0
    assert later.energy_consumed_wh > first.energy_consumed_wh
    assert later.power_watts == pytest.approx(later.voltage * later.current_amps)

    generator.reset()
    assert generator.advance(0.0).battery.energy_consumed_wh == 0.0


# --- E-Stop ----------------------------------------------------------------


def test_estop_button_latches_through_application_state(window):
    win, manager, _ = window
    assert win.estop_btn.text() == ESTOP_TEXT
    assert win.safety_badge.text() == SAFETY_READY_TEXT

    win.estop_btn.click()

    assert manager.get_snapshot().is_estopped is True
    assert win.estop_btn.text() == ESTOP_RESET_TEXT
    assert win.safety_badge.text() == SAFETY_ESTOP_TEXT
    assert win.safety_badge.property("severity") == "ERROR"

    win.estop_btn.click()

    assert manager.get_snapshot().is_estopped is False
    assert win.estop_btn.text() == ESTOP_TEXT
    assert win.safety_badge.text() == SAFETY_READY_TEXT


def test_estop_works_without_a_rover_link(window):
    """The latch must not depend on being connected (it used to)."""
    win, manager, _ = window
    assert win.comms_client.is_connected is False

    win.estop_btn.click()
    assert manager.get_snapshot().is_estopped is True

    win.estop_btn.click()
    assert manager.get_snapshot().is_estopped is False


def test_estop_display_follows_state_not_the_badge_text(window):
    """An E-Stop arriving in a snapshot is rendered; stale badge text is ignored."""
    win, manager, bus = window

    bus.telemetry_updated.emit(RoverState(is_estopped=True))
    assert win.safety_badge.text() == SAFETY_ESTOP_TEXT
    assert win.estop_btn.text() == ESTOP_RESET_TEXT

    # State says not stopped, so the next press must ENGAGE whatever the badge shows.
    win.estop_btn.click()
    assert manager.get_snapshot().is_estopped is True


def test_estop_notifies_the_rover_and_the_event_bus(window):
    win, _, bus = window
    commands, events = [], []
    win.comms_client.command_feedback_received.connect(lambda name, ok: commands.append(name))
    bus.emergency_stop_triggered.connect(events.append)

    win.estop_btn.click()

    assert "estop" in commands
    assert events == [True]


# --- Control mode ----------------------------------------------------------


def test_mode_selector_writes_through_state_manager(window):
    win, manager, _ = window
    manual = win.mode_buttons[MissionMode.MANUAL_TELEOP]
    autonomous = win.mode_buttons[MissionMode.AUTONOMOUS_NAV]
    assert [manual.text(), autonomous.text()] == ["MANUAL", "AUTONOMOUS"]

    autonomous.click()
    assert manager.get_snapshot().mission_mode == MissionMode.AUTONOMOUS_NAV
    assert autonomous.isChecked() and not manual.isChecked()

    manual.click()
    assert manager.get_snapshot().mission_mode == MissionMode.MANUAL_TELEOP
    assert manual.isChecked() and not autonomous.isChecked()


def test_mode_selector_is_locked_while_estopped(window):
    win, manager, _ = window
    autonomous = win.mode_buttons[MissionMode.AUTONOMOUS_NAV]
    autonomous.click()

    win.estop_btn.click()
    assert not autonomous.isEnabled() and not autonomous.isChecked()
    win._on_mode_requested(MissionMode.AUTONOMOUS_NAV)
    assert manager.get_snapshot().mission_mode == MissionMode.EMERGENCY_STOP

    win.estop_btn.click()
    assert autonomous.isEnabled()
    assert win.mode_buttons[MissionMode.MANUAL_TELEOP].isChecked()
    assert not autonomous.isChecked()


# --- Camera selector and marker status -------------------------------------


def test_camera_selector_writes_through_state_manager(window):
    win, manager, _ = window
    player = win.video_player
    assert player.camera_buttons[CameraId.FRONT].isChecked()

    player.camera_buttons[CameraId.REAR].click()

    assert manager.get_snapshot().selected_camera == CameraId.REAR
    assert player.camera_buttons[CameraId.REAR].isChecked()
    assert not player.camera_buttons[CameraId.FRONT].isChecked()
    assert player.camera_title.text() == "ROVER REAR CAMERA"


def test_marker_status_follows_telemetry(window):
    win, _, bus = window
    label = win.video_player.marker_label
    assert label.text() == MARKER_NO_DATA_TEXT

    bus.telemetry_updated.emit(live_state())
    assert label.text() == MARKER_DETECTED_TEXT
    assert label.property("severity") == "NORMAL"

    bus.telemetry_updated.emit(live_state(perception=PerceptionData(marker_detected=False)))
    assert label.text() == MARKER_NOT_DETECTED_TEXT

    bus.telemetry_updated.emit(live_state(telemetry_valid=False))
    assert label.text() == MARKER_NO_DATA_TEXT


# --- Navigation and TF Mini ------------------------------------------------


def test_navigation_panel_renders_pose_and_state(window):
    win, _, bus = window
    bus.telemetry_updated.emit(live_state())

    nav = win.navigation_panel
    assert nav.x_row.value() == "+3.25 m"
    assert nav.y_row.value() == "-1.50 m"
    assert nav.heading_row.value() == "137.5°"
    assert nav.target_row.value() == "2.75 m"
    assert nav.state_row.value() == "MOVING"
    assert win.obstacle_panel.status_row.value() == "CLEAR"
    assert win.obstacle_panel.range_row.value() == "2.40 m"


def test_obstacle_is_flagged_with_text_and_severity(window):
    win, _, bus = window
    bus.telemetry_updated.emit(
        live_state(
            navigation=NavigationData(state=NavigationState.OBSTACLE_DETECTED),
            perception=PerceptionData(obstacle_detected=True, obstacle_distance_m=0.45),
        )
    )

    assert win.navigation_panel.state_row.value() == "OBSTACLE DETECTED"
    assert win.navigation_panel.state_row.value_label.property("severity") == "WARNING"
    assert win.obstacle_panel.status_row.value() == "OBSTACLE"
    assert win.obstacle_panel.status_row.value_label.property("severity") == "WARNING"


def test_navigation_panels_clear_without_telemetry(window):
    win, _, bus = window
    bus.telemetry_updated.emit(live_state())

    bus.telemetry_updated.emit(None)

    assert win.navigation_panel.x_row.value() == NO_DATA_TEXT
    assert win.navigation_panel.state_row.value() == NO_DATA_TEXT
    assert win.obstacle_panel.status_row.value() == NO_DATA_TEXT


# --- Bottom telemetry ------------------------------------------------------


def test_telemetry_strip_shows_the_operator_sections(window):
    win, _, bus = window
    bus.telemetry_updated.emit(
        live_state(
            excavation=ExcavationData(
                bucket_position_pct=65.0, is_dumping=True, vibration_motor_on=True
            )
        )
    )
    panel = win.telemetry_panel

    assert panel.power.power_row.value() == "200 W"
    assert panel.power.energy_row.value() == "12.3 Wh"
    assert panel.motion.turn_row.value() == "+0.20 rad/s"
    assert panel.motion.direction_row.value() == "FORWARD LEFT"
    assert panel.excavation.bucket_row.value() == "65%"
    assert panel.excavation.bucket_bar.percentage() == pytest.approx(65.0)
    assert panel.excavation.excavating_row.value() == "IDLE"
    assert panel.excavation.dumping_row.value() == "ACTIVE"
    assert panel.auxiliary.vibration_row.value() == "ON"

    panel.show_no_data()
    assert panel.excavation.bucket_row.value() == NO_DATA_TEXT
    assert panel.auxiliary.vibration_row.value() == NO_DATA_TEXT


# --- Developer controls and terminal ---------------------------------------


def test_developer_controls_are_hidden_from_the_operator_layout(window):
    win, _, _ = window

    assert win.mission_controls.isHidden()
    assert win.mission_status.phase_container.isHidden()
    assert win.telemetry_panel.attitude.isHidden()
    assert not win.telemetry_panel.power.isHidden()
    assert not win.telemetry_panel.excavation.isHidden()

    win.set_dev_controls_visible(True)
    assert not win.mission_controls.isHidden()
    assert not win.telemetry_panel.attitude.isHidden()


def test_terminal_is_collapsed_by_default_and_collects_log_messages(window):
    win, _, bus = window
    console = win.log_console
    assert console.is_expanded is False
    assert console.view.isHidden()

    bus.log_message_emitted.emit("WARNING", "link latency high")

    assert console.line_count() == 1
    assert "link latency high" in console.view.toPlainText()
    assert "link latency high" in console.last_message_label.text()
    assert console.last_message_label.property("severity") == "WARNING"

    console.toggle_btn.click()
    assert console.is_expanded is True
    console.toggle_btn.click()
    assert console.is_expanded is False
