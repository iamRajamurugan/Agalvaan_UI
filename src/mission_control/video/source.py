"""Video source abstraction and implementations (Synthetic Test Pattern & OpenCV / RTSP)."""

from abc import ABC, abstractmethod
import math
import time
from typing import Optional, Tuple, Union
import cv2
import numpy as np

from mission_control.core.logger import get_logger
from mission_control.video.frame_buffer import FrameMetadata

logger = get_logger("video_source")


class BaseVideoSource(ABC):
    """Abstract interface for video ingest sources."""

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

    def open(self) -> bool:
        self._is_open = True
        self._frame_count = 0
        self._start_time = time.time()
        self._last_frame_time = time.time()
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

        # Rate limiter to maintain target FPS
        now = time.time()
        elapsed_since_last = now - self._last_frame_time
        sleep_time = self.frame_interval - elapsed_since_last
        if sleep_time > 0.001:
            time.sleep(sleep_time)

        self._last_frame_time = time.time()
        self._frame_count += 1

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
            "ROVER FRONT CAMERA [SYNTHETIC TEST PATTERN]",
            (cx - 270, cy - radius - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (241, 245, 249),
            2,
            cv2.LINE_AA,
        )

        time_str = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
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

        # Simulated jitter latency
        sim_latency = self.simulated_latency_base_ms + 4.0 * math.sin(self._frame_count * 0.1)

        metadata = FrameMetadata(
            frame_index=self._frame_count,
            timestamp_captured=now,
            resolution_width=self.width,
            resolution_height=self.height,
            source_type="test_pattern",
            estimated_latency_ms=max(1.0, sim_latency),
        )

        return frame, metadata


class OpenCVVideoSource(BaseVideoSource):
    """Captures frames from RTSP streams, local webcams, or video files via OpenCV."""

    def __init__(self, source_uri: Union[str, int] = 0):
        self.source_uri = source_uri
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count = 0

    def open(self) -> bool:
        logger.info(f"Opening OpenCV video source: {self.source_uri}...")
        try:
            if isinstance(self.source_uri, str) and self.source_uri.startswith("rtsp://"):
                # Configure low latency FFMPEG flags for RTSP
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
        now = time.time()
        h, w = frame.shape[:2]

        metadata = FrameMetadata(
            frame_index=self._frame_count,
            timestamp_captured=now,
            resolution_width=w,
            resolution_height=h,
            source_type=str(self.source_uri),
            estimated_latency_ms=0.0,
        )

        return frame, metadata
