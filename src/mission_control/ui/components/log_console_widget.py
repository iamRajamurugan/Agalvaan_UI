"""Compact collapsible terminal showing application log messages.

Collapsed by default to a single thin strip carrying the most recent message, so
it costs the camera almost no screen space until the operator opens it.
"""

import time
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mission_control.telemetry.state import Severity
from mission_control.ui.components.telemetry_primitives import apply_severity

COLLAPSED_TEXT = "▸  TERMINAL"
EXPANDED_TEXT = "▾  TERMINAL"
EXPANDED_HEIGHT = 120

_LEVEL_SEVERITY = {
    "WARNING": Severity.WARNING,
    "ERROR": Severity.ERROR,
    "CRITICAL": Severity.ERROR,
}


class LogConsoleWidget(QFrame):
    """Thin log strip that expands into a small read-only terminal."""

    expanded_changed = Signal(bool)

    def __init__(self, max_lines: int = 500, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LogConsole")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        strip = QHBoxLayout()
        strip.setContentsMargins(8, 2, 8, 2)
        strip.setSpacing(10)

        self.toggle_btn = QPushButton(COLLAPSED_TEXT)
        self.toggle_btn.setObjectName("LogToggleButton")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.toggled.connect(self.set_expanded)
        strip.addWidget(self.toggle_btn)

        self.last_message_label = QLabel("")
        self.last_message_label.setObjectName("LogLastMessage")
        # Long messages are clipped by the strip instead of widening the window.
        self.last_message_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        strip.addWidget(self.last_message_label, stretch=1)

        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setObjectName("LogToggleButton")
        self.clear_btn.clicked.connect(self.clear)
        self.clear_btn.hide()
        strip.addWidget(self.clear_btn)

        layout.addLayout(strip)

        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(max(1, max_lines))
        self.view.setFixedHeight(EXPANDED_HEIGHT)
        self.view.hide()
        layout.addWidget(self.view)

        apply_severity(self.last_message_label, Severity.NO_DATA)

    @property
    def is_expanded(self) -> bool:
        return not self.view.isHidden()

    def set_expanded(self, expanded: bool) -> None:
        """Shows or hides the terminal body; the strip itself always stays visible."""
        if expanded == self.is_expanded:
            return
        self.view.setVisible(expanded)
        self.clear_btn.setVisible(expanded)
        self.toggle_btn.setText(EXPANDED_TEXT if expanded else COLLAPSED_TEXT)
        if self.toggle_btn.isChecked() != expanded:
            self.toggle_btn.setChecked(expanded)
        self.expanded_changed.emit(expanded)

    def append_message(self, level: str, message: str) -> None:
        """Appends one log line and mirrors it on the collapsed strip."""
        level = str(level).upper()
        line = f"{time.strftime('%H:%M:%S')}  {level:<7}  {message}"
        self.view.appendPlainText(line)
        self.last_message_label.setText(line)
        apply_severity(self.last_message_label, _LEVEL_SEVERITY.get(level, Severity.NORMAL))

    def clear(self) -> None:
        self.view.clear()
        self.last_message_label.setText("")
        apply_severity(self.last_message_label, Severity.NO_DATA)

    def line_count(self) -> int:
        return 0 if not self.view.toPlainText() else self.view.blockCount()
