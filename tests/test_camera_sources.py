"""Tests for camera source configuration, the RealSense source, fallback, and switching.

No camera hardware or RealSense SDK is required: the SDK is replaced by a fake module.
"""

import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mission_control.core.app import MissionControlApp
from mission_control.core.config import (
    CameraSourceConfig,
    RoverConfig,
    load_rover_config,
)
from mission_control.telemetry.state import CameraId
from mission_control.video import source as source_module
from mission_control.video.factory import create_camera_source
from mission_control.video.frame_buffer import FrameMetadata
from mission_control.video.player_widget import LiveVideoPlayerWidget
from mission_control.video.source import (
    BaseVideoSource,
    FallbackVideoSource,
    OfflineVideoSource,
    OpenCVVideoSource,
    RealSenseVideoSource,
    TestPatternVideoSource,
    is_realsense_available,
)
from mission_control.video.stats import StreamState, StreamStats
from mission_control.video.worker import VideoWorker


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def wait_for(qapp, condition, timeout: float = 3.0) -> bool:
    """Pumps the Qt event loop until condition() holds or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return condition()


# --- Fake RealSense SDK ----------------------------------------------------


class FakeRealSense:
    """Minimal stand-in for the pyrealsense2 module (colour stream only)."""

    class stream:
        color = "color"

    class format:
        bgr8 = "bgr8"

    def __init__(self, fail_start: bool = False, frames_available: int = 1000):
        self.fail_start = fail_start
        self.frames_available = frames_available
        self.raise_on_read = False
        self.enabled_streams = []
        self.enabled_devices = []
        self.started = 0
        self.stopped = 0

    def pipeline(self):
        return _FakePipeline(self)

    def config(self):
        return _FakeConfig(self)


class _FakeConfig:
    def __init__(self, sdk):
        self._sdk = sdk
        self.size = (0, 0)

    def enable_device(self, serial):
        self._sdk.enabled_devices.append(serial)

    def enable_stream(self, stream, width, height, fmt, fps):
        self.size = (width, height)
        self._sdk.enabled_streams.append((stream, width, height, fmt, fps))


class _FakeColorFrame:
    def __init__(self, width, height):
        self._data = np.full((height, width, 3), 7, dtype=np.uint8)

    def get_data(self):
        return self._data


class _FakeFrameSet:
    def __init__(self, width, height):
        self._color = _FakeColorFrame(width, height)

    def get_color_frame(self):
        return self._color


class _FakePipeline:
    def __init__(self, sdk):
        self._sdk = sdk
        self._size = (0, 0)

    def start(self, config):
        if self._sdk.fail_start:
            raise RuntimeError("No device connected")
        self._size = config.size
        self._sdk.started += 1

    def stop(self):
        self._sdk.stopped += 1

    def try_wait_for_frames(self, timeout_ms):
        if self._sdk.raise_on_read:
            raise RuntimeError("Frame didn't arrive: device disconnected")
        if self._sdk.frames_available <= 0:
            return False, None
        self._sdk.frames_available -= 1
        return True, _FakeFrameSet(*self._size)


@pytest.fixture
def no_realsense_sdk(monkeypatch):
    """Simulates a development machine without pyrealsense2 installed."""
    monkeypatch.setattr(source_module, "import_realsense", lambda: None)


# --- Configuration ---------------------------------------------------------


def test_default_camera_configuration():
    cameras = RoverConfig().cameras

    assert cameras.front.type == "realsense"
    assert cameras.front.fallback_to_synthetic is True
    assert cameras.rear.type == "none"
    assert cameras.rear.fallback_to_synthetic is False


def test_camera_configuration_is_loaded_from_yaml(tmp_path):
    (tmp_path / "rover_config.yaml").write_text(
        "cameras:\n"
        "  front:\n"
        "    type: RealSense\n"
        "    serial: '123456'\n"
        "    width: 848\n"
        "    height: 480\n"
        "    fps: 60\n"
        "    fallback_to_synthetic: false\n"
        "  rear:\n"
        "    type: opencv\n"
        "    url: rtsp://192.168.1.100:8554/rear_camera\n",
        encoding="utf-8",
    )

    cameras = load_rover_config(tmp_path).cameras

    assert cameras.front.type == "realsense"
    assert (cameras.front.width, cameras.front.height, cameras.front.fps) == (848, 480, 60)
    assert cameras.front.serial == "123456"
    assert cameras.front.fallback_to_synthetic is False
    assert cameras.rear.type == "opencv"
    assert cameras.rear.url == "rtsp://192.168.1.100:8554/rear_camera"
    # Omitted keys keep their defaults.
    assert cameras.rear.width == 1280


def test_missing_camera_section_uses_defaults(tmp_path):
    (tmp_path / "rover_config.yaml").write_text("rover:\n  name: Test\n", encoding="utf-8")

    cameras = load_rover_config(tmp_path).cameras

    assert cameras.front.type == "realsense"
    assert cameras.rear.type == "none"


# --- Source selection ------------------------------------------------------


def test_factory_builds_the_configured_source_type():
    synthetic = create_camera_source("FRONT", CameraSourceConfig(type="synthetic", width=640, height=360))
    assert isinstance(synthetic, TestPatternVideoSource)
    assert (synthetic.width, synthetic.height) == (640, 360)

    realsense = create_camera_source(
        "FRONT", CameraSourceConfig(type="realsense", width=848, height=480, fps=60, serial="42")
    )
    assert isinstance(realsense, RealSenseVideoSource)
    assert (realsense.width, realsense.height, realsense.fps, realsense.serial) == (848, 480, 60, "42")

    rtsp = create_camera_source("REAR", CameraSourceConfig(type="opencv", url="rtsp://rover/rear"))
    assert isinstance(rtsp, OpenCVVideoSource)
    assert rtsp.source_uri == "rtsp://rover/rear"

    webcam = create_camera_source("REAR", CameraSourceConfig(type="opencv", url="0"))
    assert webcam.source_uri == 0


def test_factory_wraps_a_real_source_with_the_synthetic_fallback():
    source = create_camera_source(
        "FRONT", CameraSourceConfig(type="realsense", fallback_to_synthetic=True)
    )

    assert isinstance(source, FallbackVideoSource)
    assert isinstance(source.primary, RealSenseVideoSource)
    assert isinstance(source.fallback, TestPatternVideoSource)


@pytest.mark.parametrize(
    "config",
    [
        CameraSourceConfig(type="none"),
        CameraSourceConfig(type="opencv", url=""),       # configured type but no URL
        CameraSourceConfig(type="thermal-imager"),       # unknown type
        CameraSourceConfig(type="none", fallback_to_synthetic=True),
    ],
)
def test_unconfigured_camera_is_offline_not_a_stand_in(config):
    source = create_camera_source("REAR", config)

    assert isinstance(source, OfflineVideoSource)
    assert source.available is False
    assert source.describe() == "REAR CAMERA OFFLINE"
    assert source.open() is False
    assert source.read_frame() is None


# --- RealSense source ------------------------------------------------------


def test_realsense_reports_unavailable_without_the_sdk(no_realsense_sdk):
    assert is_realsense_available() is False

    source = RealSenseVideoSource()
    assert source.open() is False
    assert source.is_opened() is False
    assert source.read_frame() is None
    source.close()  # closing a never-opened source must be safe


def test_realsense_streams_colour_frames_with_the_configured_profile():
    sdk = FakeRealSense()
    source = RealSenseVideoSource(width=848, height=480, fps=60, serial="123456", rs_module=sdk)

    assert source.open() is True
    assert source.is_opened() is True
    # Only the colour stream is enabled: no depth, no infrared.
    assert sdk.enabled_streams == [("color", 848, 480, "bgr8", 60)]
    assert sdk.enabled_devices == ["123456"]

    frame, metadata = source.read_frame()
    assert frame.shape == (480, 848, 3)
    assert (metadata.resolution_width, metadata.resolution_height) == (848, 480)
    assert metadata.frame_index == 1
    assert metadata.source_type == "realsense"
    assert metadata.estimated_latency_ms == 0.0  # unmeasured, never invented

    source.close()
    assert source.is_opened() is False
    assert sdk.stopped == 1


def test_realsense_open_fails_cleanly_without_a_device():
    source = RealSenseVideoSource(rs_module=FakeRealSense(fail_start=True))

    assert source.open() is False
    assert source.is_opened() is False


def test_realsense_disconnect_is_reported_as_lost_frames():
    sdk = FakeRealSense(frames_available=1)
    source = RealSenseVideoSource(rs_module=sdk)
    source.open()
    assert source.read_frame() is not None

    assert source.read_frame() is None  # frame timeout

    sdk.raise_on_read = True
    assert source.read_frame() is None  # unplugged mid-stream: no exception escapes

    source.close()


# --- Fallback --------------------------------------------------------------


def test_missing_realsense_falls_back_to_the_synthetic_source(no_realsense_sdk):
    source = create_camera_source(
        "FRONT", CameraSourceConfig(type="realsense", width=320, height=180, fallback_to_synthetic=True)
    )

    assert source.open() is True
    assert source.is_fallback is True
    assert source.describe() == "SYNTHETIC · D456 UNAVAILABLE"

    frame, metadata = source.read_frame()
    assert frame.shape == (180, 320, 3)
    assert metadata.source_type == "test_pattern"
    source.close()
    assert source.is_opened() is False


def test_fallback_uses_the_real_camera_once_it_becomes_available():
    sdk = FakeRealSense(fail_start=True)
    source = FallbackVideoSource(
        RealSenseVideoSource(width=320, height=180, rs_module=sdk),
        TestPatternVideoSource(width=320, height=180),
        primary_name="D456",
    )

    source.open()
    assert source.is_fallback is True
    source.close()

    sdk.fail_start = False  # camera plugged in
    assert source.open() is True
    assert source.is_fallback is False
    assert source.describe() == "REALSENSE D456"
    assert source.read_frame()[1].source_type == "realsense"
    source.close()


def test_realsense_without_fallback_stays_unavailable(no_realsense_sdk):
    source = create_camera_source("FRONT", CameraSourceConfig(type="realsense"))

    assert isinstance(source, RealSenseVideoSource)
    assert source.open() is False


# --- Worker: switching and state transitions -------------------------------


class DropoutVideoSource(BaseVideoSource):
    """Delivers a few frames, loses signal once, then streams normally."""
    __test__ = False

    def __init__(self):
        self.opens = 0
        self._frames = 0
        self._is_open = False

    def open(self) -> bool:
        self.opens += 1
        self._frames = 0
        self._is_open = True
        return True

    def is_opened(self) -> bool:
        return self._is_open

    def close(self) -> None:
        self._is_open = False

    def read_frame(self):
        if not self._is_open:
            return None
        self._frames += 1
        if self.opens == 1 and self._frames > 3:
            return None
        time.sleep(0.005)
        meta = FrameMetadata(self._frames, time.monotonic(), 64, 36)
        return np.zeros((36, 64, 3), dtype=np.uint8), meta


def test_worker_reports_offline_for_an_unavailable_camera(qapp):
    worker = VideoWorker(video_source=OfflineVideoSource("REAR CAMERA OFFLINE"))
    states, frames = [], []
    worker.state_changed.connect(states.append)
    worker.frame_ready.connect(lambda frame, meta: frames.append(meta))

    worker.start_stream()
    assert wait_for(qapp, lambda: StreamState.OFFLINE in states)
    worker.stop_stream()
    qapp.processEvents()

    # No reconnect storm against a camera that does not exist, and no frames.
    assert StreamState.ERROR not in states
    assert StreamState.CONNECTING not in states
    assert frames == []
    assert states[-1] == StreamState.OFFLINE
    assert worker.stats_tracker.get_stats().error_message == "REAR CAMERA OFFLINE"


def test_worker_switches_sources_while_streaming(qapp):
    front = TestPatternVideoSource(width=320, height=180, target_fps=60, camera_name="FRONT")
    rear = OfflineVideoSource("REAR CAMERA OFFLINE")
    worker = VideoWorker(video_source=front)
    states, frames = [], []
    worker.state_changed.connect(states.append)
    worker.frame_ready.connect(lambda frame, meta: frames.append(meta))

    worker.start_stream()
    assert wait_for(qapp, lambda: len(frames) > 0)
    assert states[-1] == StreamState.LIVE

    # FRONT -> REAR (offline): the front source is released, nothing is displayed.
    worker.set_source(rear)
    assert wait_for(qapp, lambda: states[-1] == StreamState.OFFLINE)
    assert worker.video_source is rear
    assert front.is_opened() is False
    frames.clear()
    wait_for(qapp, lambda: False, timeout=0.15)
    assert frames == []

    # REAR -> FRONT: reconnects on its own, without restarting the stream.
    worker.set_source(front)
    assert wait_for(qapp, lambda: len(frames) > 0)
    assert states[-1] == StreamState.LIVE
    assert worker.is_streaming is True

    worker.stop_stream()
    assert worker.isRunning() is False


def test_worker_switches_sources_while_stopped(qapp):
    front = TestPatternVideoSource(width=320, height=180)
    rear = OfflineVideoSource("REAR CAMERA OFFLINE")
    worker = VideoWorker(video_source=front)
    states = []
    worker.state_changed.connect(states.append)

    worker.set_source(rear)
    assert worker.video_source is rear
    assert states[-1] == StreamState.OFFLINE

    worker.set_source(front)
    assert worker.video_source is front
    assert states[-1] == StreamState.DISCONNECTED
    assert worker.isRunning() is False


def test_worker_state_transitions_through_signal_loss(qapp):
    """CONNECTING -> LIVE -> NO SIGNAL -> RECONNECTING -> LIVE."""
    source = DropoutVideoSource()
    worker = VideoWorker(video_source=source)
    worker._reconnect_delay = 0.05
    states = []
    worker.state_changed.connect(states.append)

    worker.start_stream()
    assert wait_for(qapp, lambda: source.opens >= 2 and states[-1] == StreamState.LIVE)
    worker.stop_stream()
    qapp.processEvents()

    assert states[:5] == [
        StreamState.CONNECTING,
        StreamState.LIVE,
        StreamState.NO_SIGNAL,
        StreamState.RECONNECTING,
        StreamState.LIVE,
    ]
    assert states[-1] == StreamState.DISCONNECTED


def test_worker_delivers_only_the_newest_frame_to_a_busy_ui(qapp):
    """A UI thread that falls behind gets fresh frames, not a backlog of stale ones."""
    worker = VideoWorker(video_source=TestPatternVideoSource(width=160, height=90, target_fps=120))
    frames = []
    worker.frame_ready.connect(lambda frame, meta: frames.append(meta))

    worker.start_stream()
    assert wait_for(qapp, lambda: len(frames) > 0)
    frames.clear()

    time.sleep(0.3)  # UI thread busy: the source keeps producing frames meanwhile
    produced = worker.frame_buffer.total_pushed_count
    qapp.processEvents()

    assert len(frames) <= 1
    assert worker.frame_buffer.size() <= worker.frame_buffer.capacity
    if frames:
        assert frames[0].frame_index >= produced - worker.frame_buffer.capacity
    assert worker.stats_tracker.get_stats().dropped_frames > 0

    worker.stop_stream()


# --- Player HUD ------------------------------------------------------------


def test_player_shows_source_states(qapp):
    player = LiveVideoPlayerWidget()

    player.handle_state_changed(StreamState.RECONNECTING)
    assert player.state_label.text() == "RECONNECTING"
    assert player.toggle_stream_btn.text() == "STOP STREAM"

    player.handle_state_changed(StreamState.OFFLINE)
    assert player.state_label.text() == "OFFLINE"
    assert player.toggle_stream_btn.isEnabled() is False

    player.handle_state_changed(StreamState.DISCONNECTED)
    assert player.toggle_stream_btn.isEnabled() is True
    assert player.toggle_stream_btn.text() == "START STREAM"


def test_player_never_keeps_a_frame_behind_a_non_live_state(qapp):
    from PySide6.QtGui import QImage

    player = LiveVideoPlayerWidget()
    player.handle_state_changed(StreamState.LIVE)
    player.handle_frame(QImage(64, 36, QImage.Format.Format_RGB888), None)
    assert player.canvas._current_frame is not None

    player.handle_state_changed(StreamState.OFFLINE)

    assert player.canvas._current_frame is None


def test_stream_button_follows_the_stream_state(qapp):
    """Start/stop is decided by the live state, not by the last stats snapshot."""
    player = LiveVideoPlayerWidget()
    requests = []
    player.stream_start_requested.connect(lambda: requests.append("start"))
    player.stream_stop_requested.connect(lambda: requests.append("stop"))

    player.handle_state_changed(StreamState.LIVE)
    player.handle_stats(StreamStats(state=StreamState.LIVE))
    player.toggle_stream_btn.click()

    player.handle_state_changed(StreamState.DISCONNECTED)
    player.toggle_stream_btn.click()

    player.handle_state_changed(StreamState.ERROR)  # worker is retrying
    player.toggle_stream_btn.click()

    assert requests == ["stop", "start", "stop"]


def test_player_labels_a_fallback_source(qapp):
    player = LiveVideoPlayerWidget()
    player.handle_state_changed(StreamState.LIVE)

    player.handle_stats(
        StreamStats(
            state=StreamState.LIVE,
            source_label="SYNTHETIC · D456 UNAVAILABLE",
            source_is_fallback=True,
        )
    )
    assert player.source_label.text() == "SYNTHETIC · D456 UNAVAILABLE"
    assert player.source_label.property("severity") == "WARNING"

    player.handle_state_changed(StreamState.DISCONNECTED)
    assert player.source_label.text() == ""


# --- Application integration -----------------------------------------------


def test_app_runs_without_camera_hardware_and_switches_front_rear(qapp, no_realsense_sdk):
    """Default configuration on a development PC: D456 -> synthetic, rear -> offline."""
    app = MissionControlApp([])
    assert app.initialize() is True
    player = app.main_window.video_player
    worker = app.video_worker

    assert isinstance(app.camera_sources[CameraId.FRONT], FallbackVideoSource)
    assert isinstance(app.camera_sources[CameraId.REAR], OfflineVideoSource)
    assert worker.video_source is app.camera_sources[CameraId.FRONT]

    # FRONT: the app still streams, and says plainly that it is not the D456.
    player.toggle_stream_btn.click()
    assert wait_for(qapp, lambda: player.source_label.text() != "")
    assert player.stream_state == StreamState.LIVE
    assert player.source_label.text() == "SYNTHETIC · D456 UNAVAILABLE"

    # REAR: offline, and the front picture is not shown in its place.
    player.camera_buttons[CameraId.REAR].click()
    assert wait_for(qapp, lambda: player.stream_state == StreamState.OFFLINE)
    assert worker.video_source is app.camera_sources[CameraId.REAR]
    assert app.state_manager.get_snapshot().selected_camera == CameraId.REAR
    assert player.state_label.text() == "OFFLINE"
    assert player.camera_title.text() == "ROVER REAR CAMERA"
    assert player.canvas._current_frame is None

    # Back to FRONT: live again without pressing START.
    player.camera_buttons[CameraId.FRONT].click()
    assert wait_for(qapp, lambda: player.stream_state == StreamState.LIVE)
    assert wait_for(qapp, lambda: player.canvas._current_frame is not None)

    app.cleanup()
    assert worker.isRunning() is False
