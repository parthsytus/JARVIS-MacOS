"""
==========================================================
JARVIS — Transparent Overlay (The Hologram Protocol)
==========================================================

Provides visual feedback so the user knows what JARVIS is "looking at"
before it acts. Creates a borderless, click-through, transparent fullscreen
window that draws glowing neon rectangles around target UI elements.

Implementation: PyQt5 for hardware-accelerated transparency on macOS.

Dependencies:
  pip install PyQt5

Author: JARVIS-MacOS Phase 3
"""

import sys
import time
import logging
from typing import Optional, Tuple
from dataclasses import dataclass, field

from PyQt5.QtCore import (
    Qt, QTimer, QRect, QRectF, QPoint, QSize, QPropertyAnimation,
    QEasingCurve, QObject, pyqtSignal
)
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QPainterPath,
    QScreen, QGuiApplication
)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout
)

# ── Configuration ─────────────────────────────────────────────
HOLOGRAM_COLOR = QColor(0, 255, 136)      # Neon green (#00FF88)
HOLOGRAM_GLOW_COLOR = QColor(0, 255, 136, 60)  # Semi-transparent glow
HOLOGRAM_PEN_WIDTH = 3
HOLOGRAM_CORNER_RADIUS = 8
ANIMATION_DURATION_MS = 300
FADE_OUT_DELAY_MS = 2000  # How long to show before fading

logger = logging.getLogger("JARVIS.Hologram")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[HOLOGRAM] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class HologramTarget:
    """Represents a target to highlight."""
    x: int
    y: int
    width: int
    height: int
    label: str = ""
    color: QColor = field(default_factory=lambda: HOLOGRAM_COLOR)


class HologramOverlay(QWidget):
    """
    Borderless, transparent, click-through fullscreen overlay.
    Draws animated neon rectangles around target UI elements.
    """
    
    def __init__(self):
        super().__init__()
        self._init_window()
        self._targets = []
        self._animation = None
        self._opacity = 1.0
        
    def _init_window(self):
        """Configure window for transparent, click-through overlay."""
        # Window flags: frameless, stays on top, transparent for input
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.WindowTransparentForInput |
            Qt.Tool  # Keeps it off taskbar/dock
        )
        
        # Enable transparency
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        # NOTE: WA_PaintOnScreen is intentionally NOT set here.
        # It is incompatible with WA_TranslucentBackground on macOS
        # and causes QPainter::begin to fail (paintEngine == 0).
        
        # Fullscreen across all screens
        self._expand_to_all_screens()
        
        logger.info("Hologram overlay initialized")
    
    def _expand_to_all_screens(self):
        """Expand widget to cover all connected screens."""
        app = QGuiApplication.instance() or QApplication.instance()
        if not app:
            return
        
        # Calculate combined geometry of all screens
        combined_rect = QRect()
        for screen in app.screens():
            combined_rect = combined_rect.united(screen.geometry())
        
        self.setGeometry(combined_rect)
        logger.debug(f"Overlay geometry: {combined_rect.width()}x{combined_rect.height()}")
    
    def paintEvent(self, event):
        """Draw all hologram targets with glow effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        for target in self._targets:
            self._draw_target(painter, target)
    
    def _draw_target(self, painter: QPainter, target: HologramTarget):
        """Draw a single glowing neon rectangle."""
        # Use raw floats throughout to avoid QRect vs QRectF type conflicts
        tx = float(target.x)
        ty = float(target.y)
        tw = float(target.width)
        th = float(target.height)
        cr = float(HOLOGRAM_CORNER_RADIUS)
        
        # 1. Outer glow (larger, more transparent)
        glow_path = QPainterPath()
        glow_path.addRoundedRect(
            tx - 6.0, ty - 6.0,
            tw + 12.0, th + 12.0,
            cr + 6.0, cr + 6.0
        )
        
        glow_pen = QPen(target.color)
        glow_pen.setWidth(HOLOGRAM_PEN_WIDTH + 6)
        glow_pen.setColor(HOLOGRAM_GLOW_COLOR)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(glow_path)
        
        # 2. Main rectangle
        main_pen = QPen(target.color)
        main_pen.setWidth(HOLOGRAM_PEN_WIDTH)
        main_pen.setCapStyle(Qt.RoundCap)
        main_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(main_pen)
        painter.setBrush(Qt.NoBrush)
        
        painter.drawRoundedRect(QRectF(tx, ty, tw, th), cr, cr)
        
        # 3. Corner accents (neon bracket style)
        self._draw_corner_brackets(painter, target)
        
        # 4. Label if provided
        if target.label:
            self._draw_label(painter, target)
    
    def _draw_corner_brackets(self, painter: QPainter, target: HologramTarget):
        """Draw neon corner brackets for targeting aesthetic."""
        x, y, w, h = target.x, target.y, target.width, target.height
        bracket_len = min(24, w // 4, h // 4)
        pen = QPen(target.color)
        pen.setWidth(HOLOGRAM_PEN_WIDTH)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        
        # Top-left
        painter.drawLine(x, y + bracket_len, x, y)
        painter.drawLine(x, y, x + bracket_len, y)
        
        # Top-right
        painter.drawLine(x + w - bracket_len, y, x + w, y)
        painter.drawLine(x + w, y, x + w, y + bracket_len)
        
        # Bottom-left
        painter.drawLine(x, y + h - bracket_len, x, y + h)
        painter.drawLine(x, y + h, x + bracket_len, y + h)
        
        # Bottom-right
        painter.drawLine(x + w - bracket_len, y + h, x + w, y + h)
        painter.drawLine(x + w, y + h - bracket_len, x + w, y + h)
    
    def _draw_label(self, painter: QPainter, target: HologramTarget):
        """Draw label text above the target."""
        painter.setFont(QFont("SF Pro Display", 10, QFont.Medium))
        
        # Measure text
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(target.label)
        text_height = metrics.height()
        
        label_x = target.x + (target.width - text_width) // 2
        label_y = target.y - text_height - 8
        
        # Background pill (use float signature to avoid QRect/QRectF conflict)
        pill_path = QPainterPath()
        pill_path.addRoundedRect(
            float(label_x - 8), float(label_y - 2),
            float(text_width + 16), float(text_height + 4),
            12.0, 12.0
        )
        
        # Semi-transparent dark background
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(Qt.NoPen)
        painter.drawPath(pill_path)
        
        # Neon text
        painter.setPen(target.color)
        painter.drawText(label_x, label_y + text_height - 2, target.label)


class HologramController(QObject):
    """
    High-level controller for the hologram overlay.
    Manages target queue, animations, and cleanup.
    """
    
    target_drawn = pyqtSignal(str)  # Emitted when target appears
    target_cleared = pyqtSignal()   # Emitted when all targets cleared
    
    def __init__(self):
        super().__init__()
        self._app = None
        self._overlay = None
        self._fade_timer = QTimer()
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._start_fade_out)
        
    def _ensure_app(self):
        """Create QApplication if needed."""
        if QApplication.instance() is None:
            self._app = QApplication(sys.argv)
            self._app.setQuitOnLastWindowClosed(False)
        else:
            self._app = QApplication.instance()
    
    def _ensure_overlay(self):
        """Create overlay widget if needed."""
        if self._overlay is None:
            self._ensure_app()
            self._overlay = HologramOverlay()
            self._overlay.show()
    
    def draw_target(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str = "",
        color: Optional[QColor] = None,
        auto_clear: bool = True,
        delay_ms: int = FADE_OUT_DELAY_MS
    ):
        """
        Draw a hologram target at the specified screen coordinates.
        
        Args:
            x, y: Top-left corner (screen coordinates)
            width, height: Target dimensions
            label: Optional text label
            color: Custom color (defaults to neon green)
            auto_clear: If True, automatically fade out after delay_ms
            delay_ms: How long to show before fading
        """
        self._ensure_overlay()
        
        target = HologramTarget(
            x=x, y=y,
            width=width, height=height,
            label=label,
            color=color or HOLOGRAM_COLOR
        )
        
        self._overlay._targets.append(target)
        self._overlay.update()  # Trigger repaint
        
        logger.info(f"Hologram drawn at ({x}, {y}) size {width}x{height} label='{label}'")
        self.target_drawn.emit(label or f"target at {x},{y}")
        
        if auto_clear:
            self._fade_timer.start(delay_ms)
    
    def draw_target_element(self, element, label: str = None):
        """
        Draw hologram around a UIElement from system_operator.
        """
        elem_label = label or element.description
        self.draw_target(
            x=element.x - element.width // 2,
            y=element.y - element.height // 2,
            width=element.width,
            height=element.height,
            label=elem_label
        )
    
    def _start_fade_out(self):
        """Begin fade-out animation."""
        if not self._overlay:
            return
        
        self._animation = QPropertyAnimation(self._overlay, b"windowOpacity")
        self._animation.setDuration(ANIMATION_DURATION_MS)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.finished.connect(self.clear_all)
        self._animation.start()
    
    def clear_all(self):
        """Clear all targets immediately."""
        if self._overlay:
            self._overlay._targets.clear()
            self._overlay.update()
            self._overlay.setWindowOpacity(1.0)  # Reset for next use
        self.target_cleared.emit()
        logger.info("All hologram targets cleared")
    
    def hide(self):
        """Hide the overlay without clearing targets."""
        if self._overlay:
            self._overlay.hide()
    
    def show(self):
        """Show the overlay."""
        if self._overlay:
            self._overlay.show()
    
    def shutdown(self):
        """Clean shutdown."""
        self.clear_all()
        if self._overlay:
            self._overlay.close()
            self._overlay = None
        if self._app:
            self._app.quit()
            self._app = None


# ── Global Singleton Instance ─────────────────────────────────
_hologram_controller = None

def get_hologram_controller() -> HologramController:
    """Get or create the global hologram controller."""
    global _hologram_controller
    if _hologram_controller is None:
        _hologram_controller = HologramController()
    return _hologram_controller


def draw_hologram_target(
    x: int, y: int, width: int, height: int,
    label: str = "",
    color = None,
    auto_clear: bool = True,
    delay_ms: int = FADE_OUT_DELAY_MS
):
    """
    Convenience function to draw a hologram target.
    Creates controller if needed.
    
    Args:
        color: QColor, hex string (e.g. "#00ff88"), or None for default green.
    """
    # Convert string colors to QColor for the Qt rendering pipeline
    if isinstance(color, str):
        color = QColor(color)
    controller = get_hologram_controller()
    controller.draw_target(x, y, width, height, label, color, auto_clear, delay_ms)


def clear_hologram_targets():
    """Clear all hologram targets."""
    global _hologram_controller
    if _hologram_controller:
        _hologram_controller.clear_all()


def shutdown_hologram():
    """Shutdown the hologram system."""
    global _hologram_controller
    if _hologram_controller:
        _hologram_controller.shutdown()
        _hologram_controller = None


# ── Demo / Test ───────────────────────────────────────────────
if __name__ == "__main__":
    # Quick visual test
    controller = get_hologram_controller()
    
    # Draw a few test targets
    controller.draw_target(100, 100, 200, 50, "Search Field")
    controller.draw_target(800, 200, 120, 40, "Submit Button")
    controller.draw_target(400, 400, 300, 200, "Main Content Area")
    
    # Keep alive for demo
    print("Hologram demo running. Press Ctrl+C to exit.")
    try:
        sys.exit(controller._app.exec_())
    except KeyboardInterrupt:
        shutdown_hologram()
        print("\nDemo stopped.")