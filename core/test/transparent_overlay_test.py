import sys
from dataclasses import dataclass, field
from PyQt5.QtCore import Qt, QRect, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QPainterPath, QFont, QBrush
from PyQt5.QtWidgets import QWidget, QApplication

# ==========================================================
# CONFIGURATION CONSTANTS
# ==========================================================
HOLOGRAM_COLOR = QColor("#00ff88")
HOLOGRAM_GLOW_COLOR = QColor(0, 255, 136, 60)
HOLOGRAM_PEN_WIDTH = 3
HOLOGRAM_CORNER_RADIUS = 8
ANIMATION_DURATION_MS = 300
FADE_OUT_DELAY_MS = 2000

@dataclass
class HologramTarget:
    x: int
    y: int
    width: int
    height: int
    label: str = ""
    color: QColor = field(default_factory=lambda: HOLOGRAM_COLOR)

# ==========================================================
# HOLOGRAM OVERLAY WIDGET
# ==========================================================
class HologramOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.targets = []
        
        # macOS Transparency and Click-Through settings
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.WindowTransparentForInput | 
            Qt.Tool
        )
        
        # Maximize to cover the entire primary screen
        if QApplication.primaryScreen():
            screen_geo = QApplication.primaryScreen().geometry()
            self.setGeometry(screen_geo)
        
        # Auto-fade timer
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self.clear_targets)

    def add_target(self, target: HologramTarget):
        self.targets.append(target)
        self.update()
        self.fade_timer.start(FADE_OUT_DELAY_MS)

    def clear_targets(self):
        self.targets.clear()
        self.update()

    def paintEvent(self, event):
        if not self.targets:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        for target in self.targets:
            self._draw_target(painter, target)
            
        painter.end()

    def _draw_target(self, painter, target):
        # Extract raw coordinates to completely isolate the QRect vs QRectF conflict
        x = float(target.x)
        y = float(target.y)
        w = float(target.width)
        h = float(target.height)
        r = float(HOLOGRAM_CORNER_RADIUS)
        
        # 1. Draw Glow Background (Using 6-float raw value signature)
        glow_path = QPainterPath()
        glow_path.addRoundedRect(x, y, w, h, r, r)
        painter.fillPath(glow_path, QBrush(HOLOGRAM_GLOW_COLOR))
        
        # 2. Draw Main Border
        pen = QPen(target.color)
        pen.setWidth(HOLOGRAM_PEN_WIDTH)
        painter.setPen(pen)
        painter.drawPath(glow_path)
        
        # 3. Draw Corner Brackets (HUD style manual lines)
        bracket_len = 15
        painter.setPen(QPen(target.color, HOLOGRAM_PEN_WIDTH + 2))
        
        left, top, right, bottom = x, y, x + w, y + h
        
        # Top-left corner
        painter.drawLine(int(left), int(top), int(left + bracket_len), int(top))
        painter.drawLine(int(left), int(top), int(left), int(top + bracket_len))
        
        # Top-right corner
        painter.drawLine(int(right), int(top), int(right - bracket_len), int(top))
        painter.drawLine(int(right), int(top), int(right), int(top + bracket_len))
        
        # Bottom-left corner
        painter.drawLine(int(left), int(bottom), int(left + bracket_len), int(bottom))
        painter.drawLine(int(left), int(bottom), int(left), int(bottom - bracket_len))
        
        # Bottom-right corner
        painter.drawLine(int(right), int(bottom), int(right - bracket_len), int(bottom))
        painter.drawLine(int(right), int(bottom), int(right), int(bottom - bracket_len))

        # 4. Draw Label Pill Header
        if target.label:
            font = QFont("Courier", 12, QFont.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            text_rect = fm.boundingRect(target.label)
            
            pill_w = float(text_rect.width() + 16)
            pill_h = float(text_rect.height() + 10)
            pill_x = float(left)
            pill_y = float(top - pill_h)
            
            pill_path = QPainterPath()
            pill_path.addRoundedRect(pill_x, pill_y, pill_w, pill_h, 4.0, 4.0)
            painter.fillPath(pill_path, QBrush(target.color))
            
            painter.setPen(QPen(QColor("#000000")))
            painter.drawText(QRect(int(pill_x), int(pill_y), int(pill_w), int(pill_h)), Qt.AlignCenter, target.label)


# ==========================================================
# GLOBAL API EXPORTS
# ==========================================================
_hologram_controller = None

def get_hologram_controller():
    global _hologram_controller
    if _hologram_controller is None:
        if not QApplication.instance():
            QApplication(sys.argv)
        _hologram_controller = HologramOverlay()
        _hologram_controller.show()
    return _hologram_controller

def draw_hologram_target(x, y, width, height, label="", color="#00ff88"):
    controller = get_hologram_controller()
    qcolor = QColor(color) if isinstance(color, str) else color
    target = HologramTarget(x=x, y=y, width=width, height=height, label=label, color=qcolor)
    controller.add_target(target)

def clear_hologram_targets():
    controller = get_hologram_controller()
    controller.clear_targets()

def shutdown_hologram():
    global _hologram_controller
    if _hologram_controller is not None:
        _hologram_controller.close()
        _hologram_controller = None