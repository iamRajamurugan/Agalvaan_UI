"""Live Video Player UI Widget with 16:9 aspect ratio locking and YouTube-style HUD."""

from typing import Optional
from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QImage, QKeyEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)

from mission_control.telemetry.state import CameraId, RoverState, Severity
from mission_control.video.frame_buffer import FrameMetadata
from mission_control.video.stats import StreamState, StreamStats


def apply_severity(widget: QWidget, severity: Severity) -> None:
    """Sets the ``severity`` QSS property. Local copy of the telemetry helper:
    importing it from the ui package here would create an import cycle."""
    widget.setProperty("severity", severity.name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


#: States in which the video worker is running, so the stream button stops it.
_ACTIVE_STATES = (
    StreamState.LIVE,
    StreamState.CONNECTING,
    StreamState.RECONNECTING,
    StreamState.DEGRADED,
    StreamState.NO_SIGNAL,
    StreamState.ERROR,
)

_START_BUTTON_STYLE = (
    "QPushButton { background-color: #0284c7; color: white; font-weight: 700; font-size: 11px; "
    "padding: 4px 10px; border-radius: 3px; border: none; } "
    "QPushButton:hover { background-color: #0369a1; } "
    "QPushButton:disabled { background-color: #1e2636; color: #475569; }"
)
_STOP_BUTTON_STYLE = (
    "QPushButton { background-color: #991b1b; color: white; font-weight: 700; font-size: 11px; "
    "padding: 4px 10px; border-radius: 3px; border: none; } "
    "QPushButton:hover { background-color: #7f1d1d; }"
)
_BADGE_LIVE_STYLE = (
    "background-color: #dc2626; color: #ffffff; font-weight: 800; font-size: 11px; "
    "padding: 3px 8px; border-radius: 3px; border: 1px solid #ef4444;"
)
_BADGE_CONNECTING_STYLE = (
    "background-color: #78350f; color: #fbbf24; font-weight: 700; font-size: 11px; "
    "padding: 3px 8px; border-radius: 3px; border: 1px solid #b45309;"
)
_BADGE_IDLE_STYLE = (
    "background-color: #1e2430; color: #64748b; font-weight: 700; font-size: 11px; "
    "padding: 3px 8px; border-radius: 3px; border: 1px solid #334155;"
)

MARKER_DETECTED_TEXT = "MARKER: DETECTED"
MARKER_NOT_DETECTED_TEXT = "MARKER: NOT DETECTED"
MARKER_NO_DATA_TEXT = "MARKER: --"


class VideoCanvas(QWidget):
    """Canvas widget that paints video frames with strict 16:9 aspect ratio and letterboxing."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_frame: Optional[QImage] = None
        self._current_state: StreamState = StreamState.DISCONNECTED
        self._error_message: str = ""
        self._reconnect_count: int = 0
        self._camera_name: str = "FRONT"
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def set_frame(self, frame: QImage) -> None:
        self._current_frame = frame
        self.update()

    def set_state(self, state: StreamState, error_msg: str = "", reconnect_count: int = 0) -> None:
        self._current_state = state
        self._error_message = error_msg
        self._reconnect_count = reconnect_count
        self.update()

    def set_camera_name(self, name: str) -> None:
        if name != self._camera_name:
            self._camera_name = name
            self.update()

    def clear_frame(self) -> None:
        self._current_frame = None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        width = self.width()
        height = self.height()

        # Fill background with pure black for letterboxing
        painter.fillRect(0, 0, width, height, QColor(8, 10, 15))

        # Target 16:9 dimensions
        aspect_ratio = 16.0 / 9.0
        if width / max(1, height) > aspect_ratio:
            # Pillarbox (black bars left and right)
            target_h = height
            target_w = int(height * aspect_ratio)
            offset_x = (width - target_w) // 2
            offset_y = 0
        else:
            # Letterbox (black bars top and bottom)
            target_w = width
            target_h = int(width / aspect_ratio)
            offset_x = 0
            offset_y = (height - target_h) // 2

        render_rect = QRect(offset_x, offset_y, target_w, target_h)

        if self._current_state == StreamState.LIVE and self._current_frame is not None:
            # Draw live video frame scaled to 16:9 container
            painter.drawImage(render_rect, self._current_frame)
        else:
            # Draw offline / connecting placeholder state
            self._draw_state_placeholder(painter, render_rect)

        painter.end()

    def _draw_state_placeholder(self, painter: QPainter, rect: QRect) -> None:
        """Draws structured status overlay cards when stream is offline/connecting/error."""
        # Subtle viewport background
        painter.fillRect(rect, QColor(14, 18, 26))
        painter.setPen(QPen(QColor(35, 43, 60), 1, Qt.DashLine))
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

        cx = rect.center().x()
        cy = rect.center().y()

        painter.setPen(QColor(148, 163, 184))
        font_title = QFont("Segoe UI", 14, QFont.Bold)
        font_sub = QFont("Segoe UI", 11, QFont.Normal)

        if self._current_state in (StreamState.CONNECTING, StreamState.RECONNECTING):
            painter.setFont(font_title)
            painter.setPen(QColor(56, 189, 248))  # Cyan
            verb = "RECONNECTING" if self._current_state == StreamState.RECONNECTING else "CONNECTING"
            msg = f"{verb} TO {self._camera_name} CAMERA..."
            painter.drawText(QRect(cx - 250, cy - 40, 500, 30), Qt.AlignCenter, msg)

            painter.setFont(font_sub)
            painter.setPen(QColor(148, 163, 184))
            sub = f"Negotiating stream link • Attempt #{self._reconnect_count + 1}"
            painter.drawText(QRect(cx - 250, cy, 500, 30), Qt.AlignCenter, sub)

        elif self._current_state == StreamState.ERROR:
            painter.setFont(font_title)
            painter.setPen(QColor(239, 68, 68))  # Red
            painter.drawText(QRect(cx - 250, cy - 40, 500, 30), Qt.AlignCenter, "STREAM ERROR")

            painter.setFont(font_sub)
            painter.setPen(QColor(203, 213, 225))
            err_text = self._error_message or "Connection to camera failed. Auto-retrying..."
            painter.drawText(QRect(cx - 300, cy, 600, 30), Qt.AlignCenter, err_text)

        elif self._current_state == StreamState.NO_SIGNAL:
            painter.setFont(font_title)
            painter.setPen(QColor(245, 158, 11))  # Amber
            painter.drawText(QRect(cx - 250, cy - 40, 500, 30), Qt.AlignCenter, "NO SIGNAL DETECTED")

            painter.setFont(font_sub)
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(QRect(cx - 250, cy, 500, 30), Qt.AlignCenter, "Stream timed out • Retrying stream ingestion...")

        elif self._current_state == StreamState.OFFLINE:
            painter.setFont(font_title)
            painter.setPen(QColor(245, 158, 11))  # Amber
            painter.drawText(
                QRect(cx - 250, cy - 40, 500, 30),
                Qt.AlignCenter,
                f"{self._camera_name} CAMERA OFFLINE",
            )

            painter.setFont(font_sub)
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(
                QRect(cx - 300, cy, 600, 30),
                Qt.AlignCenter,
                "No camera source is configured for this view",
            )

        else:  # DISCONNECTED
            painter.setFont(font_title)
            painter.setPen(QColor(100, 116, 139))  # Muted slate
            painter.drawText(
                QRect(cx - 250, cy - 40, 500, 30),
                Qt.AlignCenter,
                f"ROVER {self._camera_name} CAMERA",
            )

            painter.setFont(font_sub)
            painter.setPen(QColor(71, 85, 105))
            painter.drawText(
                QRect(cx - 300, cy, 600, 30),
                Qt.AlignCenter,
                "STREAM STOPPED • Click 'START STREAM' to begin",
            )


class LiveVideoPlayerWidget(QFrame):
    """Full-featured YouTube-Live style video player for rover operations."""

    stream_start_requested = Signal()
    stream_stop_requested = Signal()
    fullscreen_toggled = Signal(bool)
    camera_requested = Signal(object)   # CameraId the operator asked for

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LiveVideoPlayer")
        self.setFrameShape(QFrame.StyledPanel)

        self._is_fullscreen = False
        self._stats = StreamStats()
        self._state = StreamState.DISCONNECTED
        self._camera = CameraId.FRONT

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top HUD Overlay Bar
        self.top_bar = self._create_top_hud()
        layout.addWidget(self.top_bar)

        # 2. Main 16:9 Canvas
        self.canvas = VideoCanvas(self)
        layout.addWidget(self.canvas, stretch=1)

        # 3. Bottom HUD Overlay Bar
        self.bottom_bar = self._create_bottom_hud()
        layout.addWidget(self.bottom_bar)

    def _create_top_hud(self) -> QWidget:
        top_widget = QWidget(self)
        top_widget.setObjectName("VideoTopHUD")
        top_widget.setStyleSheet(
            "QWidget#VideoTopHUD { background-color: rgba(14, 18, 26, 0.92); border-bottom: 1px solid #232a38; padding: 4px 12px; }"
        )
        layout = QHBoxLayout(top_widget)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        # 🔴 LIVE Badge
        self.live_badge = QLabel("● LIVE")
        self.live_badge.setStyleSheet(
            "background-color: #2b171a; color: #f87171; font-weight: 800; font-size: 11px; "
            "padding: 3px 8px; border-radius: 3px; border: 1px solid #7f1d1d;"
        )
        layout.addWidget(self.live_badge)

        # Stream State Text
        self.state_label = QLabel("DISCONNECTED")
        self.state_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.state_label)

        # FRONT / REAR camera selector. The selection lives in application state;
        # a click only requests it and set_camera() reflects what state holds.
        self.camera_buttons: dict[CameraId, QPushButton] = {}
        for camera in CameraId:
            button = QPushButton(camera.value)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, c=camera: self._on_camera_clicked(c))
            layout.addWidget(button)
            self.camera_buttons[camera] = button
        self.camera_buttons[self._camera].setChecked(True)

        layout.addStretch()

        # Marker detection status (text + colour, never colour alone)
        self.marker_label = QLabel(MARKER_NO_DATA_TEXT)
        self.marker_label.setObjectName("MarkerStatus")
        apply_severity(self.marker_label, Severity.NO_DATA)
        layout.addWidget(self.marker_label)

        # Stream Resolution
        self.resolution_label = QLabel("1280×720 HD")
        self.resolution_label.setStyleSheet(
            "background-color: #1e2638; color: #38bdf8; font-family: monospace; font-size: 11px; "
            "font-weight: 700; padding: 2px 6px; border-radius: 3px; border: 1px solid #0369a1;"
        )
        layout.addWidget(self.resolution_label)

        return top_widget

    def _create_bottom_hud(self) -> QWidget:
        bottom_widget = QWidget(self)
        bottom_widget.setObjectName("VideoBottomHUD")
        bottom_widget.setStyleSheet(
            "QWidget#VideoBottomHUD { background-color: rgba(14, 18, 26, 0.92); border-top: 1px solid #232a38; padding: 4px 12px; }"
        )
        layout = QHBoxLayout(bottom_widget)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(16)

        # Stream Title / Camera ID
        self.camera_title = QLabel("ROVER FRONT CAMERA")
        self.camera_title.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 12px; letter-spacing: 0.5px;")
        layout.addWidget(self.camera_title)

        # What is actually producing the frames (e.g. a synthetic stand-in)
        self.source_label = QLabel("")
        self.source_label.setObjectName("VideoSourceLabel")
        apply_severity(self.source_label, Severity.NORMAL)
        layout.addWidget(self.source_label)

        layout.addStretch()

        # FPS Display
        self.fps_label = QLabel("-- FPS")
        self.fps_label.setStyleSheet("color: #38bdf8; font-family: monospace; font-weight: 700; font-size: 12px;")
        layout.addWidget(self.fps_label)

        # Latency Display
        self.latency_label = QLabel("~-- ms")
        self.latency_label.setStyleSheet("color: #34d399; font-family: monospace; font-weight: 700; font-size: 12px;")
        layout.addWidget(self.latency_label)

        # Stream Toggle Button
        self.toggle_stream_btn = QPushButton("START STREAM")
        self.toggle_stream_btn.setStyleSheet(_START_BUTTON_STYLE)
        self.toggle_stream_btn.clicked.connect(self._on_toggle_stream)
        layout.addWidget(self.toggle_stream_btn)

        # Fullscreen Toggle Button
        self.fullscreen_btn = QPushButton("⛶ FULLSCREEN")
        self.fullscreen_btn.setStyleSheet(
            "QPushButton { background-color: #1e2636; color: #cbd5e1; font-weight: 600; font-size: 11px; "
            "padding: 4px 10px; border-radius: 3px; border: 1px solid #334155; } "
            "QPushButton:hover { background-color: #334155; color: white; }"
        )
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        layout.addWidget(self.fullscreen_btn)

        return bottom_widget

    def handle_frame(self, frame: QImage, metadata: FrameMetadata) -> None:
        """Slot for incoming decoded frames from VideoWorker."""
        self.canvas.set_frame(frame)

    def handle_stats(self, stats: StreamStats) -> None:
        """Slot for stream statistics updates."""
        self._stats = stats
        self.fps_label.setText(stats.fps_str)
        self.latency_label.setText(stats.latency_str)
        if stats.resolution_width > 0:
            self.resolution_label.setText(f"{stats.resolution_str} HD")
        if self._state in _ACTIVE_STATES and self.source_label.text() != stats.source_label:
            self.source_label.setText(stats.source_label)
            apply_severity(
                self.source_label,
                Severity.WARNING if stats.source_is_fallback else Severity.NORMAL,
            )

    @property
    def stream_state(self) -> StreamState:
        return self._state

    def handle_state_changed(self, state: StreamState) -> None:
        """Slot for stream state transitions."""
        self._state = state
        self.state_label.setText(state.value)
        self.canvas.set_state(state, self._stats.error_message, self._stats.reconnect_count)

        if state == StreamState.LIVE:
            self.live_badge.setStyleSheet(_BADGE_LIVE_STYLE)
        else:
            # Never leave another camera's (or a stale) frame behind a non-live state.
            self.canvas.clear_frame()
            self.fps_label.setText("-- FPS")
            self.latency_label.setText("~-- ms")
            self.live_badge.setStyleSheet(
                _BADGE_CONNECTING_STYLE
                if state in (StreamState.CONNECTING, StreamState.RECONNECTING)
                else _BADGE_IDLE_STYLE
            )

        if state in _ACTIVE_STATES:
            # The worker is running (live, connecting or retrying): the button stops it.
            self.toggle_stream_btn.setText(
                "CONNECTING..." if state == StreamState.CONNECTING else "STOP STREAM"
            )
            self.toggle_stream_btn.setStyleSheet(_STOP_BUTTON_STYLE)
        else:
            self.toggle_stream_btn.setText("START STREAM")
            self.toggle_stream_btn.setStyleSheet(_START_BUTTON_STYLE)
            self.source_label.setText("")
            self.resolution_label.setText(StreamStats().resolution_str)
        # An unconfigured camera has nothing to start.
        self.toggle_stream_btn.setEnabled(state != StreamState.OFFLINE)

    # -- Application state rendering -----------------------------------------

    @property
    def camera(self) -> CameraId:
        return self._camera

    def set_camera(self, camera: CameraId) -> None:
        """Reflects the camera selection held in application state."""
        self._camera = camera
        for candidate, button in self.camera_buttons.items():
            button.setChecked(candidate == camera)
        title = f"ROVER {camera.value} CAMERA"
        if self.camera_title.text() != title:
            self.camera_title.setText(title)
        self.canvas.set_camera_name(camera.value)

    def update_from_state(self, state: RoverState) -> None:
        """Renders the camera selection and marker detection from a state snapshot."""
        self.set_camera(state.selected_camera)
        if not state.has_telemetry:
            self.show_no_data()
        elif state.perception.marker_detected:
            self._set_marker(MARKER_DETECTED_TEXT, Severity.NORMAL)
        else:
            self._set_marker(MARKER_NOT_DETECTED_TEXT, Severity.OFFLINE)

    def show_no_data(self) -> None:
        """Marker status is unknown without live telemetry."""
        self._set_marker(MARKER_NO_DATA_TEXT, Severity.NO_DATA)

    def _set_marker(self, text: str, severity: Severity) -> None:
        if self.marker_label.text() != text:
            self.marker_label.setText(text)
            apply_severity(self.marker_label, severity)

    def _on_camera_clicked(self, camera: CameraId) -> None:
        # Undo the button's own toggle; the selection is re-rendered from state.
        self.set_camera(self._camera)
        self.camera_requested.emit(camera)

    def _on_toggle_stream(self) -> None:
        if self._state in _ACTIVE_STATES:
            self.stream_stop_requested.emit()
        else:
            self.stream_start_requested.emit()

    def toggle_fullscreen(self) -> None:
        """Toggles fullscreen display mode for the video player."""
        if not self._is_fullscreen:
            self.setWindowFlags(Qt.Window)
            self.showFullScreen()
            self._is_fullscreen = True
            self.fullscreen_btn.setText("✕ EXIT FULLSCREEN")
        else:
            self.setWindowFlags(Qt.Widget)
            self.showNormal()
            self._is_fullscreen = False
            self.fullscreen_btn.setText("⛶ FULLSCREEN")
        self.fullscreen_toggled.emit(self._is_fullscreen)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Allows ESC key to exit fullscreen mode."""
        if event.key() == Qt.Key_Escape and self._is_fullscreen:
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)
