"""Video source abstraction and implementations.

Sources: synthetic test pattern, OpenCV (RTSP / webcam / file), Intel RealSense
(colour stream only), an explicit "camera offline" source, and a wrapper that falls
back to another source when the preferred one cannot be opened.
"""

from abc import ABC, abstractmethod
import math
import os
import time
from typing import Any, Optional, Tuple, Union
import cv2
import numpy as np

from mission_control.core.logger import get_logger
from mission_control.video.frame_buffer import FrameMetadata

logger = get_logger("video_source")


class BaseVideoSource(ABC):
    """Abstract interface for video ingest sources."""

    #: False for a camera that is not configured at all; the worker then reports
    #: OFFLINE instead of running its reconnect loop against nothing.
    available: bool = True
    #: True while a stand-in source is being shown instead of the real camera.
    is_fallback: bool = False

    def describe(self) -> str:
        """Short operator-facing label for what is producing the frames."""
        return ""

    @abstractmethod
    def open(self) -> bool:
        """Opens and initializes the video source."""
        pass

    @abstractmethod
    def is_opened(self) -> bool:
        """Returns True if the source is active and ready to produce frames."""
        pass

    @abstractmethod
    def read_frame(self) -> Optional[Tuple[np.ndarray, FrameMetadata]]:
        """Reads the next available BGR image frame and its metadata.
        
        Returns None on stream EOF, timeout, or read failure.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Closes and releases source resources."""
        pass



class TestPatternVideoSource(BaseVideoSource):
    """Generates synthetic 16:9 test pattern frames with dynamic animations,
    timestamps, and simulated latency for standalone verification.
    """
    __test__ = False

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        target_fps: int = 30,
        simulated_latency_base_ms: float = 18.0,
        camera_name: str = "FRONT",
    ):
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.simulated_latency_base_ms = simulated_latency_base_ms

        self._is_open = False
        self._frame_count = 0
        self._last_frame_time = 0.0
        self._start_time = 0.0
        self._camera_name = camera_name

    def describe(self) -> str:
        return "SYNTHETIC"

    def open(self) -> bool:
        self._is_open = True
        self._frame_count = 0
        self._start_time = time.monotonic()
        self._last_frame_time = time.monotonic()
        logger.info(
            f"TestPatternVideoSource opened: {self.width}x{self.height} @ {self.target_fps} FPS."
        )
        return True

    def is_opened(self) -> bool:
        return self._is_open

    def close(self) -> None:
        self._is_open = False
        logger.info("TestPatternVideoSource closed.")

    def read_frame(self) -> Optional[Tuple[np.ndarray, FrameMetadata]]:
        if not self._is_open:
            return None

        # Rate limiter using monotonic clock
        now_mono = time.monotonic()
        elapsed_since_last = now_mono - self._last_frame_time
        sleep_time = self.frame_interval - elapsed_since_last
        if sleep_time > 0.001:
            time.sleep(sleep_time)

        self._last_frame_time = time.monotonic()
        self._frame_count += 1
        wall_time = time.time()

        # 1. Create dark canvas with grid background
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (18, 22, 30)  # Dark slate background BGR

        # Draw grid lines
        grid_spacing = 64
        for x in range(0, self.width, grid_spacing):
            cv2.line(frame, (x, 0), (x, self.height), (28, 34, 46), 1)
        for y in range(0, self.height, grid_spacing):
            cv2.line(frame, (0, y), (self.width, y), (28, 34, 46), 1)

        # 2. Draw Color Calibration Bars at top
        bar_height = 24
        bar_width = self.width // 7
        colors = [
            (255, 255, 255),  # White
            (0, 255, 255),    # Yellow
            (255, 255, 0),    # Cyan
            (0, 255, 0),      # Green
            (255, 0, 255),    # Magenta
            (0, 0, 255),      # Red
            (255, 0, 0),      # Blue
        ]
        for i, color in enumerate(colors):
            x1 = i * bar_width
            x2 = (i + 1) * bar_width if i < 6 else self.width
            cv2.rectangle(frame, (x1, 0), (x2, bar_height), color, -1)

        # 3. Draw Center Reticle & Radar Sweep Line (Proves Live Fluid Motion)
        cx, cy = self.width // 2, self.height // 2
        radius = 160
        cv2.circle(frame, (cx, cy), radius, (56, 189, 248), 2)       # Outer circle (Cyan)
        cv2.circle(frame, (cx, cy), radius // 2, (38, 54, 80), 1)  # Inner circle
        cv2.drawMarker(frame, (cx, cy), (56, 189, 248), cv2.MARKER_CROSS, 24, 2)

        # Rotating sweep line
        angle_rad = (self._frame_count * 0.08) % (2 * math.pi)
        sweep_x = int(cx + radius * math.cos(angle_rad))
        sweep_y = int(cy + radius * math.sin(angle_rad))
        cv2.line(frame, (cx, cy), (sweep_x, sweep_y), (52, 211, 153), 2) # Green sweep line

        # 4. Text Information Overlay
        cv2.putText(
            frame,
            f"ROVER {self._camera_name} CAMERA [SYNTHETIC TEST PATTERN]",
            (cx - 270, cy - radius - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (241, 245, 249),
            2,
            cv2.LINE_AA,
        )

        time_str = time.strftime("%H:%M:%S", time.localtime(wall_time)) + f".{int((wall_time % 1) * 1000):03d}"
        cv2.putText(
            frame,
            f"FRAME: {self._frame_count:06d}  |  TIME: {time_str}  |  RES: {self.width}x{self.height}",
            (cx - 250, cy + radius + 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (148, 163, 184),
            1,
            cv2.LINE_AA,
        )

        # Simulated jitter latency (clearly tagged as simulated)
        sim_latency = self.simulated_latency_base_ms + 4.0 * math.sin(self._frame_count * 0.1)

        metadata = FrameMetadata(
            frame_index=self._frame_count,
            timestamp_captured=now_mono,
            resolution_width=self.width,
            resolution_height=self.height,
            source_type="test_pattern",
            estimated_latency_ms=max(1.0, sim_latency),
        )

        return frame, metadata


class OpenCVVideoSource(BaseVideoSource):
    """Captures frames from RTSP streams, local webcams, or video files via OpenCV."""

    def __init__(self, source_uri: Union[str, int] = 0, rtsp_transport: str = "udp"):
        self.source_uri = source_uri
        self.rtsp_transport = rtsp_transport
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count = 0

    def describe(self) -> str:
        is_rtsp = isinstance(self.source_uri, str) and self.source_uri.startswith("rtsp://")
        return "RTSP" if is_rtsp else "OPENCV"

    def open(self) -> bool:
        logger.info(f"Opening OpenCV video source: {self.source_uri}...")
        try:
            if isinstance(self.source_uri, str) and self.source_uri.startswith("rtsp://"):
                # Configure low-latency FFMPEG environment options on Windows
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                    f"rtsp_transport;{self.rtsp_transport}|fflags;nobuffer|max_delay;0|flags;low_delay"
                )
                self._cap = cv2.VideoCapture(self.source_uri, cv2.CAP_FFMPEG)
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                self._cap = cv2.VideoCapture(self.source_uri)

            if not self._cap.isOpened():
                logger.error(f"Failed to open video source: {self.source_uri}")
                return False

            logger.info(f"OpenCV video source opened successfully: {self.source_uri}")
            return True
        except Exception as e:
            logger.error(f"Exception opening video source {self.source_uri}: {e}")
            return False

    def is_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def close(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info(f"OpenCV video source closed: {self.source_uri}")

    def read_frame(self) -> Optional[Tuple[np.ndarray, FrameMetadata]]:
        if not self.is_opened():
            return None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            return None

        self._frame_count += 1
        now_mono = time.monotonic()
        h, w = frame.shape[:2]

        metadata = FrameMetadata(
            frame_index=self._frame_count,
            timestamp_captured=now_mono,
            resolution_width=w,
            resolution_height=h,
            source_type=str(self.source_uri),
            estimated_latency_ms=0.0,  # 0.0 indicates unmeasured on real network stream
        )

        return frame, metadata


def import_realsense() -> Optional[Any]:
    """Returns the pyrealsense2 module, or None when the SDK is not installed.

    pyrealsense2 is an optional dependency: it is imported only when a RealSense
    source is actually opened, so a development machine without it still runs.
    """
    try:
        import pyrealsense2 as rs
        return rs
    except Exception as e:  # ImportError, or a broken native install
        logger.debug(f"pyrealsense2 unavailable: {e}")
        return None


def is_realsense_available() -> bool:
    """Checks whether the RealSense SDK can be imported in this environment."""
    return import_realsense() is not None


class RealSenseVideoSource(BaseVideoSource):
    """Colour stream from an Intel RealSense camera (D456) via pyrealsense2.

    Acquisition and display only: depth, point clouds and alignment are deliberately
    not enabled here.
    """

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        serial: str = "",
        frame_timeout_ms: int = 200,
        rs_module: Optional[Any] = None,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.serial = serial
        self.frame_timeout_ms = frame_timeout_ms
        # Injectable so the lifecycle can be tested without the SDK or a device.
        self._rs = rs_module
        self._pipeline: Optional[Any] = None
        self._frame_count = 0

    def describe(self) -> str:
        return "REALSENSE D456"

    def open(self) -> bool:
        rs = self._rs if self._rs is not None else import_realsense()
        if rs is None:
            logger.warning("RealSense SDK (pyrealsense2) is not installed; D456 unavailable.")
            return False

        try:
            pipeline = rs.pipeline()
            config = rs.config()
            if self.serial:
                config.enable_device(self.serial)
            config.enable_stream(
                rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps
            )
            pipeline.start(config)
        except Exception as e:
            # No device connected, device busy, or an unsupported stream profile.
            logger.warning(f"RealSense D456 could not be started: {e}")
            return False

        self._pipeline = pipeline
        self._frame_count = 0
        logger.info(
            f"RealSense colour stream started: {self.width}x{self.height} @ {self.fps} FPS."
        )
        return True

    def is_opened(self) -> bool:
        return self._pipeline is not None

    def close(self) -> None:
        pipeline, self._pipeline = self._pipeline, None
        if pipeline is None:
            return
        try:
            pipeline.stop()
        except Exception as e:
            logger.warning(f"Error stopping RealSense pipeline: {e}")
        logger.info("RealSense colour stream stopped.")

    def read_frame(self) -> Optional[Tuple[np.ndarray, FrameMetadata]]:
        if self._pipeline is None:
            return None

        try:
            ok, frames = self._pipeline.try_wait_for_frames(self.frame_timeout_ms)
            if not ok:
                return None
            color = frames.get_color_frame()
            if not color:
                return None
            # Copy out of the SDK-owned buffer before the frame object is released.
            frame = np.array(color.get_data(), copy=True)
        except Exception as e:
            # A camera unplugged mid-stream raises here; report it as a lost frame
            # so the worker's normal signal-loss / reconnect handling takes over.
            logger.debug(f"RealSense frame read failed: {e}")
            return None

        self._frame_count += 1
        h, w = frame.shape[:2]
        metadata = FrameMetadata(
            frame_index=self._frame_count,
            timestamp_captured=time.monotonic(),
            resolution_width=w,
            resolution_height=h,
            source_type="realsense",
            estimated_latency_ms=0.0,  # 0.0 indicates unmeasured
        )
        return frame, metadata


class OfflineVideoSource(BaseVideoSource):
    """Stands in for a camera that is not configured. It never produces frames."""

    available = False

    def __init__(self, reason: str = "CAMERA OFFLINE"):
        self.reason = reason

    def describe(self) -> str:
        return self.reason

    def open(self) -> bool:
        return False

    def is_opened(self) -> bool:
        return False

    def read_frame(self) -> Optional[Tuple[np.ndarray, FrameMetadata]]:
        return None

    def close(self) -> None:
        pass


class FallbackVideoSource(BaseVideoSource):
    """Opens the preferred source, or a stand-in when the preferred one is unavailable.

    The preferred source is retried on every open(), so restarting the stream (or the
    worker's reconnect after a signal loss) picks the real camera up once it appears.
    """

    def __init__(self, primary: BaseVideoSource, fallback: BaseVideoSource, primary_name: str):
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self._active: Optional[BaseVideoSource] = None

    @property
    def is_fallback(self) -> bool:
        return self._active is self.fallback

    def describe(self) -> str:
        if self.is_fallback:
            return f"{self.fallback.describe()} · {self.primary_name} UNAVAILABLE"
        return self.primary.describe()

    def open(self) -> bool:
        if self.primary.open():
            self._active = self.primary
            return True
        logger.warning(
            f"{self.primary_name} unavailable; falling back to {self.fallback.describe()} source."
        )
        if self.fallback.open():
            self._active = self.fallback
            return True
        self._active = None
        return False

    def is_opened(self) -> bool:
        return self._active is not None and self._active.is_opened()

    def read_frame(self) -> Optional[Tuple[np.ndarray, FrameMetadata]]:
        if self._active is None:
            return None
        return self._active.read_frame()

    def close(self) -> None:
        active, self._active = self._active, None
        if active is not None:
            active.close()
