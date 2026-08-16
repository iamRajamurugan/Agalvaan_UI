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

from mission_control.video.frame_buffer import FrameMetadata
from mission_control.video.stats import StreamState, StreamStats


class VideoCanvas(QWidget):
    """Canvas widget that paints video frames with strict 16:9 aspect ratio and letterboxing."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_frame: Optional[QImage] = None
        self._current_state: StreamState = StreamState.DISCONNECTED
        self._error_message: str = ""
        self._reconnect_count: int = 0
        
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

        if self._current_state == StreamState.CONNECTING:
            painter.setFont(font_title)
            painter.setPen(QColor(56, 189, 248))  # Cyan
            msg = "CONNECTING TO ROVER CAMERA..."
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

        else:  # DISCONNECTED
            painter.setFont(font_title)
            painter.setPen(QColor(100, 116, 139))  # Muted slate
            painter.drawText(QRect(cx - 250, cy - 40, 500, 30), Qt.AlignCenter, "ROVER FRONT CAMERA")

            painter.setFont(font_sub)
            painter.setPen(QColor(71, 85, 105))
            painter.drawText(
                QRect(cx - 300, cy, 600, 30),
                Qt.AlignCenter,
                "STREAM OFFLINE • Click 'START STREAM' or connect rover to initialize player",
            )


class LiveVideoPlayerWidget(QFrame):
    """Full-featured YouTube-Live style video player for rover operations."""

    stream_start_requested = Signal()
    stream_stop_requested = Signal()
    fullscreen_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LiveVideoPlayer")
        self.setFrameShape(QFrame.StyledPanel)

        self._is_fullscreen = False
        self._stats = StreamStats()

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

        layout.addStretch()

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
        self.toggle_stream_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: 700; font-size: 11px; "
            "padding: 4px 10px; border-radius: 3px; border: none; } "
            "QPushButton:hover { background-color: #0369a1; }"
        )
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

    def handle_state_changed(self, state: StreamState) -> None:
        """Slot for stream state transitions."""
        self.state_label.setText(state.value)
        self.canvas.set_state(state, self._stats.error_message, self._stats.reconnect_count)

        if state == StreamState.LIVE:
            self.live_badge.setStyleSheet(
                "background-color: #dc2626; color: #ffffff; font-weight: 800; font-size: 11px; "
                "padding: 3px 8px; border-radius: 3px; border: 1px solid #ef4444;"
            )
            self.toggle_stream_btn.setText("STOP STREAM")
            self.toggle_stream_btn.setStyleSheet(
                "QPushButton { background-color: #991b1b; color: white; font-weight: 700; font-size: 11px; "
                "padding: 4px 10px; border-radius: 3px; border: none; } "
                "QPushButton:hover { background-color: #7f1d1d; }"
            )
        elif state == StreamState.CONNECTING:
            self.live_badge.setStyleSheet(
                "background-color: #78350f; color: #fbbf24; font-weight: 700; font-size: 11px; "
                "padding: 3px 8px; border-radius: 3px; border: 1px solid #b45309;"
            )
            self.toggle_stream_btn.setText("CONNECTING...")
        else:
            self.live_badge.setStyleSheet(
                "background-color: #1e2430; color: #64748b; font-weight: 700; font-size: 11px; "
                "padding: 3px 8px; border-radius: 3px; border: 1px solid #334155;"
            )
            self.toggle_stream_btn.setText("START STREAM")
            self.toggle_stream_btn.setStyleSheet(
                "QPushButton { background-color: #0284c7; color: white; font-weight: 700; font-size: 11px; "
                "padding: 4px 10px; border-radius: 3px; border: none; } "
                "QPushButton:hover { background-color: #0369a1; }"
            )
            self.fps_label.setText("-- FPS")
            self.latency_label.setText("~-- ms")

    def _on_toggle_stream(self) -> None:
        if self._stats.state == StreamState.LIVE or self._stats.state == StreamState.CONNECTING:
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
