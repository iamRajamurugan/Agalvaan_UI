"""Tests for navigation state display, the environment view, excavation, and E-Stop safety."""

import math
import time

import pytest
from PySide6.QtWidgets import QApplication

from mission_control.comms.mock_client import MockCommsClient
from mission_control.core.config import AppConfig, RoverConfig
from mission_control.core.event_bus import EventBus
from mission_control.telemetry.mock_generator import (
    MOCK_OBSTACLES_XY_M,
    NAV_CYCLE_S,
    NEARBY_OBSTACLE_RANGE_M,
    TFMINI_OBSTACLE_THRESHOLD_M,
    MockTelemetryGenerator,
)
from mission_control.telemetry.state import (
    ConnectionState,
    ExcavationData,
    IMUData,
    MissionMode,
    NavigationData,
    NavigationState,
    ObstaclePoint,
    PerceptionData,
    RoverState,
    StateManager,
)
from mission_control.ui.components.environment_view import (
    CLEAR_TEXT,
    NO_DATA_VIEW_TEXT,
    OBSTACLE_TEXT,
    VIEW_RANGE_M,
    EnvironmentView,
)
from mission_control.ui.components.excavation_widget import AuxiliaryWidget, ExcavationWidget
from mission_control.ui.components.navigation_widget import (
    NAV_STATE_GLYPHS,
    NavigationWidget,
    ObstacleWidget,
)
from mission_control.ui.components.telemetry_primitives import NO_DATA_TEXT
from mission_control.ui.main_window import (
    ESTOP_HOLDING_TEXT,
    ESTOP_RESET_TEXT,
    ESTOP_TEXT,
    SAFETY_CAPTION,
    SAFETY_ESTOP_TEXT,
    SAFETY_MOCK_CAPTION,
    SAFETY_READY_TEXT,
    MainWindow,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def window(qapp):
    client = MockCommsClient()
    client.start()
    manager = StateManager()
    bus = EventBus()
    win = MainWindow(AppConfig(), RoverConfig(), client, event_bus=bus, state_manager=manager)

    yield win, manager, bus

    client.stop()
    win.close()


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def live_state(**overrides) -> RoverState:
    fields = dict(
        connection_state=ConnectionState.MOCK_MODE,
        imu=IMUData(yaw_deg=90.0),
        navigation=NavigationData(
            x_m=3.25, y_m=-1.5, distance_to_target_m=2.75, state=NavigationState.MOVING
        ),
        perception=PerceptionData(obstacle_distance_m=2.4),
        telemetry_valid=True,
        last_telemetry_time=1.0,
    )
    fields.update(overrides)
    return RoverState(**fields)


# --- Navigation ------------------------------------------------------------


def test_navigation_states_are_exactly_the_allowed_set():
    assert [state.value for state in NavigationState] == [
        "IDLE",
        "MOVING",
        "OBSTACLE DETECTED",
        "EXCAVATING",
        "DUMPING",
        "RETURNING",
        "COMPLETED",
    ]


def test_every_navigation_state_has_its_own_word_and_shape(qapp):
    """The state must be readable without colour: unique text and a unique glyph."""
    widget = NavigationWidget()
    seen = set()

    for state in NavigationState:
        widget.update_from_state(live_state(navigation=NavigationData(state=state)))
        assert widget.state_row.value() == state.value
        assert widget.state_row.glyph() == NAV_STATE_GLYPHS[state]
        seen.add((widget.state_row.value(), widget.state_row.glyph()))

    assert len(seen) == len(NavigationState)
    assert len(set(NAV_STATE_GLYPHS.values())) == len(NavigationState)


def test_navigation_panel_shows_pose_and_clears_without_telemetry(qapp):
    widget = NavigationWidget()
    widget.update_from_state(live_state())

    assert widget.x_row.value() == "+3.25 m"
    assert widget.y_row.value() == "-1.50 m"
    assert widget.heading_row.value() == "90.0°"
    assert widget.target_row.value() == "2.75 m"

    widget.update_from_state(live_state(telemetry_valid=False))
    assert widget.state_row.value() == NO_DATA_TEXT
    assert widget.state_row.glyph() == ""
    assert widget.x_row.value() == NO_DATA_TEXT


# --- Environment view and TF Mini ------------------------------------------


def test_environment_card_distinguishes_clear_from_obstacle(qapp):
    card = ObstacleWidget()

    card.update_from_state(live_state(perception=PerceptionData(obstacle_distance_m=2.4)))
    assert card.status_row.value() == CLEAR_TEXT
    assert card.status_row.value_label.property("severity") == "NORMAL"
    assert card.range_row.value() == "2.40 m"
    assert card.view.status_text == CLEAR_TEXT
    assert card.property("severity") == "NORMAL"

    card.update_from_state(
        live_state(perception=PerceptionData(obstacle_detected=True, obstacle_distance_m=0.45))
    )
    assert card.status_row.value() == OBSTACLE_TEXT
    assert card.status_row.value_label.property("severity") == "WARNING"
    assert card.range_row.value() == "0.45 m"
    assert card.view.status_text == OBSTACLE_TEXT
    assert card.view.obstacle_detected is True
    # The whole card is outlined while an obstacle is reported.
    assert card.property("severity") == "WARNING"


def test_environment_view_holds_the_snapshot_it_was_given(qapp):
    card = ObstacleWidget()
    obstacles = [
        ObstaclePoint(bearing_deg=30.0, distance_m=0.8),
        ObstaclePoint(bearing_deg=-120.0, distance_m=2.5),
        ObstaclePoint(bearing_deg=0.0, distance_m=VIEW_RANGE_M + 3.0),  # outside the view
    ]

    card.update_from_state(
        live_state(
            imu=IMUData(yaw_deg=450.0),
            perception=PerceptionData(obstacle_distance_m=1.7, nearby_obstacles=obstacles),
        )
    )
    view = card.view

    assert view.has_data is True
    assert view.heading_deg == pytest.approx(90.0)
    assert view.range_m == pytest.approx(1.7)
    assert [o.distance_m for o in view.obstacles] == [0.8, 2.5]


def test_environment_view_clears_without_telemetry(qapp):
    card = ObstacleWidget()
    card.update_from_state(
        live_state(perception=PerceptionData(obstacle_detected=True, obstacle_distance_m=0.4))
    )

    card.update_from_state(live_state(telemetry_valid=False))

    assert card.view.has_data is False
    assert card.view.obstacles == ()
    assert card.view.status_text == NO_DATA_VIEW_TEXT
    assert card.status_row.value() == NO_DATA_TEXT
    assert card.property("severity") == "NORMAL"


@pytest.mark.parametrize("size", [(226, 110), (226, 300), (60, 40)])
def test_environment_view_paints_every_state(qapp, size):
    """Painting must not raise for no-data, clear, obstacle and out-of-range input."""
    view = EnvironmentView()
    view.resize(*size)

    view.grab()
    view.set_environment(45.0, 2.0, False, [ObstaclePoint(10.0, 0.5), ObstaclePoint(170.0, 3.0)])
    view.grab()
    view.set_environment(300.0, 0.3, True, [])
    view.grab()
    view.set_environment(0.0, VIEW_RANGE_M * 5, False, [])
    assert view.grab().isNull() is False


def test_window_renders_the_environment_from_event_bus_snapshots(window):
    win, _, bus = window

    bus.telemetry_updated.emit(
        live_state(
            navigation=NavigationData(state=NavigationState.OBSTACLE_DETECTED),
            perception=PerceptionData(
                obstacle_detected=True,
                obstacle_distance_m=0.6,
                nearby_obstacles=[ObstaclePoint(5.0, 0.6)],
            ),
        )
    )
    assert win.navigation_panel.state_row.value() == "OBSTACLE DETECTED"
    assert win.obstacle_panel.view.obstacle_detected is True
    assert len(win.obstacle_panel.view.obstacles) == 1

    bus.telemetry_updated.emit(None)
    assert win.obstacle_panel.view.has_data is False


# --- Mock data -------------------------------------------------------------


def test_mock_tfmini_and_obstacles_are_deterministic_and_consistent():
    left, right = MockTelemetryGenerator(seed=5), MockTelemetryGenerator(seed=5)

    for _ in range(int(NAV_CYCLE_S)):
        a, b = left.advance(1.0), right.advance(1.0)
        assert a.perception.obstacle_distance_m == b.perception.obstacle_distance_m
        assert a.perception.nearby_obstacles == b.perception.nearby_obstacles
        assert a.navigation.state == b.navigation.state

        perception = a.perception
        assert perception.obstacle_distance_m > 0.0
        assert perception.obstacle_detected == (
            perception.obstacle_distance_m < TFMINI_OBSTACLE_THRESHOLD_M
        )
        assert len(perception.nearby_obstacles) <= len(MOCK_OBSTACLES_XY_M)
        distances = [o.distance_m for o in perception.nearby_obstacles]
        assert distances == sorted(distances)
        for obstacle in perception.nearby_obstacles:
            assert 0.0 <= obstacle.distance_m <= NEARBY_OBSTACLE_RANGE_M
            assert -180.0 <= obstacle.bearing_deg <= 180.0


def test_mock_obstacle_bearings_match_the_rover_pose():
    """Rover-frame bearing/distance must reproduce the fixed world obstacle positions."""
    packet = MockTelemetryGenerator().advance(20.0)
    x, y = packet.navigation.x_m, packet.navigation.y_m
    yaw = math.radians(packet.imu.yaw_deg)

    assert packet.perception.nearby_obstacles
    for obstacle in packet.perception.nearby_obstacles:
        world_angle = yaw + math.radians(obstacle.bearing_deg)
        world_xy = (
            x + obstacle.distance_m * math.cos(world_angle),
            y + obstacle.distance_m * math.sin(world_angle),
        )
        assert any(
            world_xy == pytest.approx(known, abs=1e-6) for known in MOCK_OBSTACLES_XY_M
        )


def test_mock_bucket_fills_while_excavating_and_empties_while_dumping():
    generator = MockTelemetryGenerator()
    excavating, dumping = [], []

    for _ in range(int(NAV_CYCLE_S * 2)):
        packet = generator.advance(0.5)
        if packet.excavation.is_excavating:
            excavating.append(packet.excavation.bucket_position_pct)
        elif excavating and not dumping and not packet.excavation.is_dumping:
            assert packet.excavation.bucket_position_pct == pytest.approx(100.0)  # in transit
        if packet.excavation.is_dumping:
            dumping.append(packet.excavation.bucket_position_pct)
        assert not (packet.excavation.is_excavating and packet.excavation.is_dumping)
        if len(dumping) and not packet.excavation.is_dumping:
            break

    assert excavating == sorted(excavating) and excavating[-1] > 90.0
    assert dumping == sorted(dumping, reverse=True) and dumping[-1] < 10.0


# --- Excavation and vibration motor ----------------------------------------


@pytest.mark.parametrize(
    "position, expected_text, expected_bar",
    [(0.0, "0%", 0.0), (42.4, "42%", 42.4), (100.0, "100%", 100.0), (130.0, "100%", 100.0), (-5.0, "0%", 0.0)],
)
def test_bucket_position_is_shown_within_0_to_100(qapp, position, expected_text, expected_bar):
    card = ExcavationWidget()
    card.update_from_state(live_state(excavation=ExcavationData(bucket_position_pct=position)))

    assert card.bucket_row.value() == expected_text
    assert card.bucket_bar.percentage() == pytest.approx(expected_bar)


def test_excavating_and_dumping_states_are_shown_as_words(qapp):
    card = ExcavationWidget()

    card.update_from_state(live_state(excavation=ExcavationData(is_excavating=True)))
    assert (card.excavating_row.value(), card.dumping_row.value()) == ("ACTIVE", "IDLE")

    card.update_from_state(live_state(excavation=ExcavationData(is_dumping=True)))
    assert (card.excavating_row.value(), card.dumping_row.value()) == ("IDLE", "ACTIVE")

    card.update_from_state(live_state(telemetry_valid=False))
    assert card.excavating_row.value() == NO_DATA_TEXT
    assert card.bucket_bar.percentage() is None


def test_vibration_motor_is_shown_on_or_off(qapp):
    card = AuxiliaryWidget()
    assert card.vibration_row.label.text() == "VIBRATION MOTOR"

    card.update_from_state(live_state(excavation=ExcavationData(vibration_motor_on=True)))
    assert card.vibration_row.value() == "ON"

    card.update_from_state(live_state(excavation=ExcavationData(vibration_motor_on=False)))
    assert card.vibration_row.value() == "OFF"

    card.update_from_state(live_state(telemetry_valid=False))
    assert card.vibration_row.value() == NO_DATA_TEXT


# --- Control mode ----------------------------------------------------------


def test_startup_mode_is_manual_and_held_in_application_state(window):
    win, manager, _ = window

    assert StateManager().get_snapshot().mission_mode == MissionMode.MANUAL_TELEOP
    assert manager.get_snapshot().mission_mode == MissionMode.MANUAL_TELEOP
    assert win.mode_buttons[MissionMode.MANUAL_TELEOP].isChecked()
    assert not win.mode_buttons[MissionMode.AUTONOMOUS_NAV].isChecked()


def test_state_refuses_mode_changes_while_estop_is_latched():
    manager = StateManager()
    manager.set_estop(True)

    assert manager.set_mission_mode(MissionMode.AUTONOMOUS_NAV) is False
    assert manager.get_snapshot().mission_mode == MissionMode.EMERGENCY_STOP

    manager.set_estop(False)
    assert manager.set_mission_mode(MissionMode.AUTONOMOUS_NAV) is True
    assert manager.get_snapshot().mission_mode == MissionMode.AUTONOMOUS_NAV


def test_latched_estop_blocks_autonomous_and_tells_the_rover_nothing(window):
    win, manager, _ = window
    commands = []
    win.estop_btn.click()
    win.comms_client.command_feedback_received.connect(lambda name, ok: commands.append(name))

    win._on_mode_requested(MissionMode.AUTONOMOUS_NAV)

    assert manager.get_snapshot().mission_mode == MissionMode.EMERGENCY_STOP
    assert "mission_mode" not in commands
    assert not win.mode_buttons[MissionMode.AUTONOMOUS_NAV].isEnabled()
    assert not win.mode_buttons[MissionMode.AUTONOMOUS_NAV].isChecked()


# --- E-Stop reset safety ---------------------------------------------------


def test_a_click_engages_estop_immediately_but_never_resets_it(window):
    win, manager, _ = window

    win.estop_btn.click()
    assert manager.get_snapshot().is_estopped is True
    assert win.safety_badge.text() == SAFETY_ESTOP_TEXT
    assert win.estop_btn.text() == ESTOP_RESET_TEXT

    for _ in range(5):
        win.estop_btn.click()
    pump(0.05)

    assert manager.get_snapshot().is_estopped is True
    assert win.safety_badge.text() == SAFETY_ESTOP_TEXT
    assert win.estop_btn.text() == ESTOP_RESET_TEXT


def test_estop_engages_on_press_before_release(window):
    win, manager, _ = window

    win.estop_btn.pressed.emit()

    assert manager.get_snapshot().is_estopped is True
    # Still holding the press that engaged it must not start a reset.
    win.estop_reset_hold_ms = 10
    pump(0.08)
    assert manager.get_snapshot().is_estopped is True


def test_a_short_hold_is_cancelled_on_release(window):
    win, manager, _ = window
    win.estop_btn.click()
    win.estop_reset_hold_ms = 400

    win.estop_btn.pressed.emit()
    assert win.estop_btn.text() == ESTOP_HOLDING_TEXT
    pump(0.05)
    win.estop_btn.released.emit()
    pump(0.5)  # well past the hold time: a cancelled hold must not complete later

    assert manager.get_snapshot().is_estopped is True
    assert win.estop_btn.text() == ESTOP_RESET_TEXT


def test_holding_the_button_resets_estop_and_returns_to_manual(window):
    win, manager, _ = window
    win.mode_buttons[MissionMode.AUTONOMOUS_NAV].click()
    win.estop_btn.click()
    win.estop_reset_hold_ms = 60

    win.estop_btn.pressed.emit()
    pump(0.03)
    assert manager.get_snapshot().is_estopped is True  # not yet
    pump(0.25)
    win.estop_btn.released.emit()

    snapshot = manager.get_snapshot()
    assert snapshot.is_estopped is False
    assert snapshot.mission_mode == MissionMode.MANUAL_TELEOP  # never back to autonomous
    assert win.estop_btn.text() == ESTOP_TEXT
    assert win.safety_badge.text() == SAFETY_READY_TEXT
    assert win.mode_buttons[MissionMode.MANUAL_TELEOP].isChecked()


def test_estop_survives_snapshots_and_keeps_the_ui_live(window):
    """The latch holds across telemetry updates, and the rest of the UI keeps updating."""
    win, manager, bus = window
    win.estop_btn.click()

    for _ in range(3):
        manager.apply_telemetry(live_state())
        bus.telemetry_updated.emit(manager.get_snapshot())

    assert manager.get_snapshot().is_estopped is True
    assert win.safety_badge.text() == SAFETY_ESTOP_TEXT
    assert win.navigation_panel.state_row.value() == "MOVING"
    assert win.obstacle_panel.status_row.value() == CLEAR_TEXT


def test_latched_estop_does_not_claim_the_rover_has_stopped_in_mock_mode(window):
    win, _, _ = window
    assert win.safety_caption.text() == SAFETY_CAPTION

    win.comms_client.connect_rover()  # MOCK MODE link, not a real rover
    win.estop_btn.click()

    assert win.safety_caption.text() == SAFETY_MOCK_CAPTION
    assert "MOCK" in win.safety_caption.text()

    win.estop_reset_hold_ms = 10
    win.estop_btn.pressed.emit()
    pump(0.1)
    win.estop_btn.released.emit()
    assert win.safety_caption.text() == SAFETY_CAPTION
