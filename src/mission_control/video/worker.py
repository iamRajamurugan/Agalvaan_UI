"""Background Video Ingestion and Decoding Worker Thread."""

import threading
import time
from typing import Optional
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage

from mission_control.core.logger import get_logger
from mission_control.video.frame_buffer import BoundedFrameBuffer, FrameMetadata
from mission_control.video.source import BaseVideoSource
from mission_control.video.stats import StreamState, StreamStats, StreamStatisticsTracker

logger = get_logger("video_worker")


class VideoWorker(QThread):
    """Dedicated background worker thread for non-blocking video ingestion,
    decoding, frame buffer management, and automatic stream recovery.

    One worker serves every operator camera: set_source() swaps the source it reads
    from, and the running thread picks the change up without blocking the UI thread.
    """

    frame_ready = Signal(QImage, object)       # (QImage frame, FrameMetadata)
    stats_updated = Signal(object)              # (StreamStats snapshot)
    state_changed = Signal(object)              # (StreamState enum)
    error_occurred = Signal(str)                # (error_message)

    # Wakes the UI thread to collect the newest buffered frame.
    _frame_queued = Signal()

    def __init__(
        self,
        video_source: BaseVideoSource,
        buffer_capacity: int = 2,
        parent=None,
    ):
        super().__init__(parent)
        self.video_source = video_source
        self.frame_buffer = BoundedFrameBuffer(max_capacity=buffer_capacity)
        self.stats_tracker = StreamStatisticsTracker()

        self._is_running = False
        self._reconnect_backoff_base = 1.0
        self._max_backoff = 8.0
        self._reconnect_delay = 1.0  # pause before reopening after a signal loss
        self._stats_emit_interval = 0.2  # 5 Hz stats updates
        self._last_stats_emit_time = 0.0

        self._source_lock = threading.Lock()
        self._pending_source: Optional[BaseVideoSource] = None

        # Frames are handed to the UI thread through the bounded buffer: at most one
        # wake-up is ever queued, and the UI takes the newest frame, so a busy UI
        # thread drops stale frames instead of accumulating a backlog of them.
        self._delivery_pending = False
        self._frame_queued.connect(self._deliver_latest_frame, Qt.QueuedConnection)

    @property
    def is_streaming(self) -> bool:
        return self._is_running

    # -- Controls (called from the UI thread) ----------------------------------

    def start_stream(self) -> None:
        """Starts the background video decoding thread."""
        if not self.isRunning():
            self._apply_pending_source()
            self._is_running = True
            self.start()
            logger.info("VideoWorker thread started.")

    def stop_stream(self) -> None:
        """Stops the thread gracefully and closes the video source."""
        logger.info("Stopping VideoWorker thread...")
        self._is_running = False
        self.requestInterruption()
        self.wait(2000)

        try:
            self.video_source.close()
        except Exception as e:
            logger.warning(f"Error closing video source: {e}")

        self._apply_pending_source()
        self.frame_buffer.clear()
        self._announce_idle_state()
        logger.info("VideoWorker thread stopped cleanly.")

    def set_source(self, source: BaseVideoSource) -> None:
        """Switches the camera this worker streams.

        While streaming, the running thread closes the old source and connects to
        the new one on its next iteration. While stopped, the swap is immediate and
        only the idle state (DISCONNECTED or OFFLINE) is announced.
        """
        with self._source_lock:
            self._pending_source = source
        if not self.isRunning():
            self._apply_pending_source()
            self._announce_idle_state()

    # -- Internals -------------------------------------------------------------

    def _has_pending_source(self) -> bool:
        with self._source_lock:
            return self._pending_source is not None

    def _apply_pending_source(self) -> bool:
        """Swaps in a requested source. Returns True if the source changed."""
        with self._source_lock:
            pending, self._pending_source = self._pending_source, None
        if pending is None or pending is self.video_source:
            return False
        self.video_source = pending
        self.frame_buffer.clear()
        self.stats_tracker.reset()
        return True

    def _set_state(self, state: StreamState, message: str = "") -> None:
        self.stats_tracker.set_state(state, message)
        self.state_changed.emit(state)

    def _announce_idle_state(self) -> None:
        """Reports the not-streaming state: OFFLINE for an unavailable camera."""
        if self.video_source.available:
            self._set_state(StreamState.DISCONNECTED)
        else:
            self._set_state(StreamState.OFFLINE, self.video_source.describe())

    def _should_continue(self) -> bool:
        return self._is_running and not self.isInterruptionRequested()

    def _interruptible_sleep(self, duration: float) -> None:
        """Sleeps unless the stream is stopped or another camera is selected."""
        sleep_start = time.monotonic()
        while time.monotonic() - sleep_start < duration:
            if not self._should_continue() or self._has_pending_source():
                return
            time.sleep(0.05)

    @Slot()
    def _deliver_latest_frame(self) -> None:
        """UI-thread slot: forwards the newest buffered frame, dropping older ones."""
        self._delivery_pending = False
        latest = None
        while True:
            item = self.frame_buffer.pop(timeout=0.0)
            if item is None:
                break
            if latest is not None:
                self.stats_tracker.record_frame_dropped()
            latest = item
        if latest is None or not self._is_running:
            return
        self.stats_tracker.record_frame_displayed()
        self.frame_ready.emit(latest[0], latest[1])

    def run(self) -> None:
        """Main execution loop for frame capture and decoding."""
        backoff = self._reconnect_backoff_base
        reconnecting = False

        while self._should_continue():
            if self._apply_pending_source():
                backoff = self._reconnect_backoff_base
                reconnecting = False
            source = self.video_source

            # 0. Camera not configured: report OFFLINE and wait for a switch or stop.
            if not source.available:
                logger.info(f"VideoWorker: {source.describe()}.")
                self._set_state(StreamState.OFFLINE, source.describe())
                while self._should_continue() and not self._has_pending_source():
                    time.sleep(0.05)
                continue

            # 1. Connecting Phase
            self._set_state(StreamState.RECONNECTING if reconnecting else StreamState.CONNECTING)
            logger.info("VideoWorker: Attempting to open video source...")

            if not source.open():
                error_msg = f"Failed to connect to video source. Retrying in {backoff:.1f}s..."
                logger.warning(f"VideoWorker: {error_msg}")
                self.stats_tracker.record_reconnect_attempt()
                self._set_state(StreamState.ERROR, error_msg)
                self.error_occurred.emit(error_msg)

                self._interruptible_sleep(backoff)
                backoff = min(backoff * 1.5, self._max_backoff)
                reconnecting = True
                continue

            # Connected successfully
            backoff = self._reconnect_backoff_base
            self.stats_tracker.set_source_info(source.describe(), source.is_fallback)
            self._set_state(StreamState.LIVE)
            self.stats_updated.emit(self.stats_tracker.get_stats())
            logger.info(f"VideoWorker: Stream connected and LIVE ({source.describe() or 'source'}).")

            consecutive_failures = 0
            self._last_stats_emit_time = time.monotonic()

            # 2. Continuous Ingestion Loop
            while self._should_continue() and not self._has_pending_source():
                try:
                    result = source.read_frame()
                    if result is None:
                        consecutive_failures += 1
                        if consecutive_failures > 15:  # ~0.5s of consecutive missing frames
                            logger.warning("VideoWorker: Stream signal lost or timeout.")
                            self._set_state(StreamState.NO_SIGNAL)
                            break
                        time.sleep(0.01)
                        continue

                    consecutive_failures = 0
                    bgr_frame, metadata = result

                    # Convert BGR NumPy array to QImage safely
                    height, width, channels = bgr_frame.shape
                    bytes_per_line = channels * width

                    # Create deep copy of image bytes into QImage
                    qimage = QImage(
                        bgr_frame.data,
                        width,
                        height,
                        bytes_per_line,
                        QImage.Format.Format_BGR888,
                    ).copy()

                    # Push to Bounded Frame Buffer (stale frame dropping)
                    was_dropped = self.frame_buffer.push(qimage, metadata)
                    if was_dropped:
                        self.stats_tracker.record_frame_dropped()

                    # Record statistics
                    byte_size = bgr_frame.nbytes
                    self.stats_tracker.record_frame_received(
                        width=width,
                        height=height,
                        byte_size=byte_size,
                        latency_ms=metadata.estimated_latency_ms,
                        is_simulated_latency=(metadata.source_type == "test_pattern"),
                    )

                    # Wake the UI thread, unless a wake-up is already on its way
                    if not self._delivery_pending:
                        self._delivery_pending = True
                        self._frame_queued.emit()

                    # Periodic stats emission using monotonic clock
                    now_mono = time.monotonic()
                    if now_mono - self._last_stats_emit_time >= self._stats_emit_interval:
                        self._last_stats_emit_time = now_mono
                        stats = self.stats_tracker.get_stats()
                        self.stats_updated.emit(stats)

                except Exception as e:
                    logger.error(f"VideoWorker exception in frame decode loop: {e}")
                    self.error_occurred.emit(str(e))
                    break

            # Close source before reconnect attempt or camera switch
            try:
                source.close()
            except Exception as e:
                logger.warning(f"Error closing video source on reconnect: {e}")

            if self._should_continue() and not self._has_pending_source():
                reconnecting = True
                self.stats_tracker.record_reconnect_attempt()
                self._interruptible_sleep(self._reconnect_delay)
