"""Tests for LiveVideoPlayerWidget layout, HUD updating, and state handling."""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

from mission_control.video.player_widget import LiveVideoPlayerWidget
from mission_control.video.frame_buffer import FrameMetadata
from mission_control.video.stats import StreamState, StreamStats


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_video_player_widget_init(qapp):
    """Verifies default widget layout, labels, and state."""
    player = LiveVideoPlayerWidget()

    assert player.camera_title.text() == "ROVER FRONT CAMERA"
    assert player.state_label.text() == "DISCONNECTED"
    assert player.fps_label.text() == "-- FPS"
    assert player.latency_label.text() == "~-- ms"
    assert player.toggle_stream_btn.text() == "START STREAM"
    assert player.fullscreen_btn.text() == "⛶ FULLSCREEN"


def test_video_player_handle_stats(qapp):
    """Verifies HUD label updates upon receiving StreamStats snapshot."""
    player = LiveVideoPlayerWidget()

    stats = StreamStats(
        state=StreamState.LIVE,
        received_fps=30.0,
        displayed_fps=29.8,
        dropped_frames=0,
        resolution_width=1280,
        resolution_height=720,
        estimated_latency_ms=17.5,
    )

    player.handle_stats(stats)
    assert player.fps_label.text() == "30 FPS"
    assert player.latency_label.text() == "~18 ms"
    assert "1280×720 HD" in player.resolution_label.text()


def test_video_player_state_transitions(qapp):
    """Verifies button text and badge updates across StreamState changes."""
    player = LiveVideoPlayerWidget()

    # Transition to CONNECTING
    player.handle_state_changed(StreamState.CONNECTING)
    assert player.state_label.text() == StreamState.CONNECTING.value
    assert player.toggle_stream_btn.text() == "CONNECTING..."

    # Transition to LIVE
    player.handle_state_changed(StreamState.LIVE)
    assert player.state_label.text() == StreamState.LIVE.value
    assert player.toggle_stream_btn.text() == "STOP STREAM"

    # Transition to DISCONNECTED
    player.handle_state_changed(StreamState.DISCONNECTED)
    assert player.state_label.text() == StreamState.DISCONNECTED.value
    assert player.toggle_stream_btn.text() == "START STREAM"


def test_video_player_handle_frame(qapp):
    """Verifies canvas frame assignment without errors."""
    player = LiveVideoPlayerWidget()
    test_img = QImage(320, 180, QImage.Format.Format_RGB888)
    meta = FrameMetadata(frame_index=1, timestamp_captured=1.0, resolution_width=320, resolution_height=180)

    player.handle_frame(test_img, meta)
    assert player.canvas._current_frame is not None


def test_video_player_fullscreen_toggle(qapp):
    """Verifies fullscreen toggle and signal emission."""
    player = LiveVideoPlayerWidget()
    toggled_states = []
    player.fullscreen_toggled.connect(lambda fs: toggled_states.append(fs))

    player.toggle_fullscreen()
    assert player._is_fullscreen is True
    assert player.fullscreen_btn.text() == "✕ EXIT FULLSCREEN"
    assert True in toggled_states

    player.toggle_fullscreen()
    assert player._is_fullscreen is False
    assert player.fullscreen_btn.text() == "⛶ FULLSCREEN"
    assert False in toggled_states
