"""
ui.py — Enhanced UI v4: separated thought windows, richer sprites,
        summarizer chat, simplified sprite-based agent display.

New in v4:
  • Removed 2D animated office scene (graphics_lib) for performance.
  • Agents displayed as animated sprites in the Agents tab.
  • Quick-action focus bug fixed: buttons have Qt.NoFocus so Enter
    key can't accidentally trigger them while typing.
"""
from __future__ import annotations

import math
import random
import re
from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QPlainTextEdit, QVBoxLayout, QHBoxLayout,
    QPushButton, QDialog, QLabel, QSplitter, QFrame,
    QScrollArea, QSizePolicy, QLineEdit, QProgressBar,
    QComboBox, QApplication, QGroupBox, QTextEdit, QSpinBox, QTabWidget,
    QListWidget, QListWidgetItem
)
from PySide6.QtGui import (
    QPainter, QBrush, QColor, QPen, QRadialGradient,
    QLinearGradient, QFont, QPainterPath, QPolygonF
)
from PySide6.QtCore import (


    QTimer, QPointF, QSizeF, Property, QObject, Qt, QRectF
)

# v2.0.27: theme color tokens for widget-level HTML/CSS styling (Phase E).
# main.apply_theme() calls set_ui_theme() so chat colors follow the active theme.
UI_THEME = {}
# Registry of (widget, restyle_fn) so a theme switch re-colors every widget
# whose inline stylesheet was built from TH() tokens. Without this, widgets
# styled once at creation keep their old colors when the theme changes.
UI_THEMEABLE = []


def ui_style(widget, restyle_fn):
    """Apply a TH()-token stylesheet AND register it for live re-styling.

    restyle_fn() must re-issue the widget's setStyleSheet(f"...{TH('x')}...")
    so that, when UI_THEME changes, replaying it picks up the new tokens.
    """
    try:
        restyle_fn()
        UI_THEMEABLE.append((widget, restyle_fn))
    except Exception:
        pass


def restyle_ui():
    """Re-apply every registered tokenized stylesheet (call on theme change)."""
    for widget, restyle_fn in UI_THEMEABLE:
        try:
            restyle_fn()
        except Exception:
            pass


def set_ui_theme(theme: dict):
    global UI_THEME
    UI_THEME = theme or {}
    # Re-color all previously-styled tokenized widgets live.
    restyle_ui()


# v2.0.34ap (H67): master switch for sprite/particle animations, driven by the
# Appearance > "Animations" toggle. When off, animated effects are skipped (the
# toggle now actually does something).
UI_ANIMATIONS = True


def set_effects(*, animations: bool = True):
    """Toggle whether ui.py draws particle/gear animations."""
    global UI_ANIMATIONS
    UI_ANIMATIONS = bool(animations)


def TH(key: str, fallback: str = "#888888") -> str:
    return str(UI_THEME.get(key, fallback))


# ─────────────────────────────────────────────────────────────────────────────
#  Color palette
# ─────────────────────────────────────────────────────────────────────────────
CHANNEL_COLORS = {
    "Manager":  {"header": "#bb86fc", "text": "#d4aaff", "bg": "#1a0033"},
    "Agent":    {"header": "#03dac6", "text": "#80ffe8", "bg": "#001a1a"},
    "Comms":    {"header": "#ffb300", "text": "#ffe082", "bg": "#1a1400"},
    "System":   {"header": "#ff7043", "text": "#ffccbc", "bg": "#1a0a00"},
    "Summary":  {"header": "#9c27b0", "text": "#e1bee7", "bg": "#1a0033"},
    "Chat":     {"header": "#00b0ff", "text": "#b3e5fc", "bg": "#001422"},
}
DEFAULT_CHANNEL = {"header": "#aaaaaa", "text": "#cccccc", "bg": "#111111"}


# ═══════════════════════════════════════════════════════════════════════════
#  Particle  — simple floating particle for sprite effects
# ═══════════════════════════════════════════════════════════════════════════
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life",
                 "size", "color", "alpha")

    def __init__(self, x, y, color: QColor):
        self.x = x
        self.y = y
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(0.4, 1.6)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - 0.5   # slight upward bias
        self.max_life = random.randint(20, 50)
        self.life = self.max_life
        self.size = random.uniform(2, 5)
        self.color = color
        self.alpha = 255

    def tick(self) -> bool:
        """Update position; return False when dead."""
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.04   # gravity
        self.life -= 1
        self.alpha = int(255 * (self.life / self.max_life))
        return self.life > 0


# ═══════════════════════════════════════════════════════════════════════════
#  AgentSprite  — rich animated states (v2: larger, more effects)
# ═══════════════════════════════════════════════════════════════════════════
class AgentSprite(QWidget):
    """
    Animated robot sprite — v2.

    New in v2:
      • Larger: 140×170
      • Floating particle cloud (idle/success/error)
      • Energy ring orbiting the head (communicating)
      • Data-stream lines scrolling down (researching)
      • Typing fingers animation (writing)
      • Heartbeat pulse ring (working)
      • Rainbow starfield (success)
      • Glitch offset lines (error)
      • Named label underneath + gradient name banner

    States
    ------
    idle          green    slow pulse, blink, floating particles
    thinking      blue     multi-dot bounce above head
    researching   cyan     data-stream lines + scan bar
    writing       lime     arm swing + finger dots
    communicating purple   energy ring orbit + radio waves
    working       orange   spinning gear + heartbeat pulse
    success       yellow   rainbow starfield + celebration bounce
    error         red      X eyes + glitch lines + shake
    """

    STATE_CFG: Dict[str, tuple] = {
        "idle":          ("#22c55e", "normal",  "blink"),
        "thinking":      ("#3b82f6", "dots",    "think_cloud"),
        "researching":   ("#06b6d4", "scan",    "data_stream"),
        "writing":       ("#84cc16", "normal",  "write_arm"),
        "communicating": ("#a855f7", "normal",  "energy_ring"),
        "working":       ("#f97316", "busy",    "heartbeat"),
        "success":       ("#facc15", "star",    "rainbow_burst"),
        "error":         ("#ef4444", "cross",   "glitch"),
    }

    W, H = 140, 170

    def __init__(self, parent=None, label: str = "Agent"):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.label      = label
        self.state      = "idle"
        self.frame      = 0

        # Animation counters
        self._scan_x    = 0
        self._gear_ang  = 0
        self._wave_r    = 0
        self._shake     = 0
        self._star_sc   = 1.0
        self._pulse     = 0.0
        self._pulse_dir = 1
        self._ring_ang  = 0.0
        self._hb_r      = 0.0
        self._data_y    = 0
        self._glitch_x  = 0
        self._bounce_y  = 0.0
        self._bounce_dir = 1

        # Particles
        self._particles: List[Particle] = []
        self._particle_timer = 0

        # PERF: 20fps is plenty smooth for small sprites; half the paint cost of 30fps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)   # ~20 fps

    def pause_animation(self):
        """Stop the animation timer when the sprite's tab is hidden."""
        if self._timer.isActive():
            self._timer.stop()

    def resume_animation(self):
        """Resume the animation timer when the sprite's tab becomes visible."""
        if not self._timer.isActive():
            self._timer.start()

    def set_state(self, state: str):
        if state != self.state:
            self.state = state if state in self.STATE_CFG else "idle"
            self._scan_x  = 0
            self._wave_r  = 0
            self._star_sc = 1.8
            self._shake   = (8 if state == "error" else 0)
            self._particles.clear()

    def _spawn_particles(self, cx: float, cy: float, color: QColor, n: int = 3):
        for _ in range(n):
            self._particles.append(Particle(cx, cy, color))

    def _tick(self):
        self.frame      = (self.frame + 1) % 3600
        self._scan_x    = (self._scan_x + 2) % 80
        self._gear_ang  = (self._gear_ang + 3) % 360
        self._wave_r    = (self._wave_r + 1.8) % 50
        self._ring_ang  = (self._ring_ang + 2.5) % 360
        self._data_y    = (self._data_y + 3) % 60
        self._glitch_x  = random.randint(-3, 3) if self.state == "error" else 0

        # Pulse
        self._pulse += 0.04 * self._pulse_dir
        if self._pulse >= 1.0:  self._pulse_dir = -1
        elif self._pulse <= 0.0: self._pulse_dir = 1

        # Success star
        if self._star_sc > 1.0:
            self._star_sc = max(1.0, self._star_sc - 0.015)

        # Shake dies
        if self._shake > 0:
            self._shake -= 1

        # Heartbeat ring
        if self.state == "working":
            self._hb_r = (self._hb_r + 1.5) % 55

        # Bounce (success)
        if self.state == "success":
            self._bounce_y += 0.3 * self._bounce_dir
            if self._bounce_y > 6: self._bounce_dir = -1
            elif self._bounce_y < 0: self._bounce_dir = 1

        # Particles — skip entirely if animations disabled
        if UI_ANIMATIONS:
            self._particle_timer += 1
            color_hex = self.STATE_CFG.get(self.state, self.STATE_CFG["idle"])[0]
            c = QColor(color_hex)
            cx, cy = self.W // 2, 75

            if self.state == "idle" and self._particle_timer % 12 == 0:
                self._spawn_particles(cx + random.randint(-20, 20),
                                      cy + random.randint(-10, 10), c, 1)
            elif self.state == "success" and self._particle_timer % 4 == 0:
                self._spawn_particles(cx, cy, c, 4)
            elif self.state == "error" and self._particle_timer % 8 == 0:
                self._spawn_particles(cx, cy, QColor("#ff4444"), 2)
            elif self.state == "communicating" and self._particle_timer % 10 == 0:
                self._spawn_particles(cx, cy - 30, c, 2)

        # PERF: cap particle count to avoid unbounded growth
        if self._particles:
            self._particles = [p for p in self._particles if p.tick()]
            if len(self._particles) > 40:
                self._particles = self._particles[-40:]
        self.update()

    def showEvent(self, event):
        """PERF: resume animation timer only when the widget is visible."""
        super().showEvent(event)
        self.resume_animation()

    def hideEvent(self, event):
        """PERF: pause animation timer when the widget is hidden."""
        super().hideEvent(event)
        self.pause_animation()

    # ─────────────────────────────────────────────────────────────────────
    #  Paint
    # ─────────────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cfg = self.STATE_CFG.get(self.state, self.STATE_CFG["idle"])
        color_hex, eye_style, fx = cfg
        base_color = QColor(color_hex)

        dx = self._glitch_x if self.state == "error" else 0
        cx  = self.W // 2 + dx
        cy  = 75 + (int(self._bounce_y) if self.state == "success" else 0)
        head_w, head_h = 70, 65

        # ── Particles ────────────────────────────────────────────────────
        for part in self._particles:
            pc = QColor(part.color)
            pc.setAlpha(part.alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(pc))
            p.drawEllipse(QRectF(part.x - part.size / 2,
                                 part.y - part.size / 2,
                                 part.size, part.size))

        # ── Background glow ───────────────────────────────────────────────
        glow_r = 55 + self._pulse * 15
        glow = QRadialGradient(cx, cy, glow_r)
        glow.setColorAt(0, QColor(base_color.red(), base_color.green(),
                                  base_color.blue(), 35))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r,
                             glow_r * 2, glow_r * 2))

        # ── Heartbeat ring (working) ──────────────────────────────────────
        if self.state == "working" and self._hb_r < 50:
            alpha = int(220 * (1 - self._hb_r / 50))
            hb_c = QColor(base_color.red(), base_color.green(),
                          base_color.blue(), alpha)
            p.setPen(QPen(hb_c, 2))
            p.setBrush(Qt.NoBrush)
            r = self._hb_r
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # ── Energy ring orbit (communicating) ────────────────────────────
        if self.state == "communicating":
            for i in range(3):
                wave_r = self._wave_r + i * 17
                if wave_r > 55: continue
                alpha = int(200 * (1 - wave_r / 55))
                wc = QColor(base_color.red(), base_color.green(),
                            base_color.blue(), alpha)
                p.setPen(QPen(wc, 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QRectF(cx - wave_r, cy - wave_r,
                                     wave_r * 2, wave_r * 2))
            # Orbiting dot
            ra = math.radians(self._ring_ang)
            ox = cx + math.cos(ra) * 45
            oy = cy + math.sin(ra) * 22
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(base_color.lighter(180)))
            p.drawEllipse(QRectF(ox - 5, oy - 5, 10, 10))

        # ── Data stream lines (researching) ──────────────────────────────
        if self.state == "researching":
            p.setPen(QPen(QColor(0, 230, 210, 80), 1))
            for i in range(5):
                x_pos = cx - 30 + i * 15
                y_start = cy - 40 + (self._data_y + i * 12) % 60
                p.drawLine(x_pos, y_start, x_pos, y_start + 8)

        # ── Rainbow burst (success) ───────────────────────────────────────
        if self.state == "success" and self._star_sc > 1.0:
            rainbow = ["#ff0000","#ff7700","#ffff00",
                       "#00ff00","#0000ff","#8b00ff"]
            for idx, col in enumerate(rainbow):
                angle = math.radians(idx * 60 + self.frame * 2)
                r_burst = 35 * self._star_sc
                p.setPen(QPen(QColor(col), 2))
                p.drawLine(
                    int(cx + math.cos(angle) * 10),
                    int(cy + math.sin(angle) * 10),
                    int(cx + math.cos(angle) * r_burst),
                    int(cy + math.sin(angle) * r_burst),
                )

        # ── Glitch lines (error) ──────────────────────────────────────────
        if self.state == "error" and self._shake > 0:
            for _ in range(3):
                gy = random.randint(cy - 30, cy + 30)
                gx_off = random.randint(-6, 6)
                p.setPen(QPen(QColor(255, 60, 60, 140), 1))
                p.drawLine(cx - 40 + gx_off, gy, cx + 40 + gx_off, gy)

        # ── Head body ─────────────────────────────────────────────────────
        face_grad = QLinearGradient(cx - head_w//2, cy - head_h//2,
                                    cx + head_w//2, cy + head_h//2)
        face_grad.setColorAt(0, base_color.lighter(145))
        face_grad.setColorAt(1, base_color.darker(110))
        p.setBrush(QBrush(face_grad))

        outline_pen_w = 3 if self.state == "error" else 2
        p.setPen(QPen(base_color.lighter(190), outline_pen_w))

        sc = self._star_sc if self.state == "success" else 1.0
        hw2 = head_w * sc / 2
        hh2 = head_h * sc / 2
        p.drawRoundedRect(QRectF(cx - hw2, cy - hh2, hw2*2, hh2*2), 12, 12)

        # ── Neck ──────────────────────────────────────────────────────────
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(base_color.red(), base_color.green(),
                          base_color.blue(), 160))
        p.drawRect(cx - 8, cy + int(hh2), 16, 13)

        # ── Body / torso ──────────────────────────────────────────────────
        body_top = cy + int(hh2) + 13
        body_grad = QLinearGradient(cx - 30, body_top, cx + 30, body_top + 35)
        body_grad.setColorAt(0, base_color.darker(120))
        body_grad.setColorAt(1, base_color.darker(160))
        p.setBrush(QBrush(body_grad))
        p.setPen(QPen(base_color.lighter(140), 1))
        p.drawRoundedRect(QRectF(cx - 28, body_top, 56, 35), 6, 6)

        # Body panel light
        p.setPen(Qt.NoPen)
        panel_c = base_color.lighter(200)
        panel_c.setAlpha(80)
        p.setBrush(QBrush(panel_c))
        p.drawRoundedRect(QRectF(cx - 12, body_top + 7, 24, 8), 3, 3)

        # ── Antenna ───────────────────────────────────────────────────────
        ant_color = base_color.lighter(220) if self.state == "thinking" \
            else QColor("#aaaaaa")
        p.setPen(QPen(ant_color, 2))
        p.drawLine(cx, cy - int(hh2), cx, cy - int(hh2) - 20)
        tip_r = 7 if self.state == "thinking" and (self.frame // 6) % 2 == 0 else 5
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(ant_color))
        p.drawEllipse(QRectF(cx - tip_r, cy - int(hh2) - 20 - tip_r,
                             tip_r * 2, tip_r * 2))

        # ── Gear on head (working) ────────────────────────────────────────
        if self.state == "working":
            p.save()
            p.translate(cx, cy - int(hh2))
            p.rotate(self._gear_ang)
            teeth = 9
            gear_c = QColor("#ffedd5")
            p.setPen(QPen(gear_c, 1))
            p.setBrush(QBrush(gear_c))
            path = QPainterPath()
            for i in range(teeth * 2):
                angle = math.radians(i * 180 / teeth)
                r_tooth = 10 if i % 2 == 0 else 6
                x_t = math.cos(angle) * r_tooth
                y_t = math.sin(angle) * r_tooth
                if i == 0:
                    path.moveTo(x_t, y_t)
                else:
                    path.lineTo(x_t, y_t)
            path.closeSubpath()
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#1a1a2e"))
            p.drawEllipse(QRectF(-4, -4, 8, 8))
            p.restore()

        # ── Thinking cloud ────────────────────────────────────────────────
        if self.state == "thinking":
            cloud_color = QColor(200, 220, 255, 100)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(cloud_color))
            for i, (ox, oy, r) in enumerate([
                (-12, -10, 12), (0, -16, 14), (12, -10, 12), (0, -8, 10)
            ]):
                p.drawEllipse(QRectF(cx + ox - r, cy - int(hh2) - 30 + oy - r,
                                     r*2, r*2))

        # ── Eyes ──────────────────────────────────────────────────────────
        p.setPen(Qt.NoPen)
        eye_l_x = cx - 16
        eye_r_x = cx + 6
        eye_y   = cy - 10

        if eye_style == "normal":
            blink = (self.frame // 25) % 12 == 0
            if blink:
                p.setBrush(Qt.white)
                p.drawRect(int(eye_l_x), int(eye_y) + 5, 12, 3)
                p.drawRect(int(eye_r_x), int(eye_y) + 5, 12, 3)
            else:
                p.setBrush(Qt.white)
                p.drawEllipse(QRectF(eye_l_x, eye_y, 12, 16))
                p.drawEllipse(QRectF(eye_r_x, eye_y, 12, 16))
                p.setBrush(QColor("#1a1a2e"))
                p.drawEllipse(QRectF(eye_l_x + 3, eye_y + 4, 6, 8))
                p.drawEllipse(QRectF(eye_r_x + 3, eye_y + 4, 6, 8))
                # Pupil highlight
                p.setBrush(Qt.white)
                p.drawEllipse(QRectF(eye_l_x + 7, eye_y + 4, 3, 3))
                p.drawEllipse(QRectF(eye_r_x + 7, eye_y + 4, 3, 3))

        elif eye_style == "scan":
            p.setBrush(QColor("#001a20"))
            p.drawRect(cx - 28, int(eye_y), 56, 8)
            p.setBrush(QColor("#e0f7fa"))
            p.drawRect(cx - 28, int(eye_y), 56, 2)
            scan_c = QColor(0, 255, 200, 200)
            p.setBrush(QBrush(scan_c))
            p.drawRect(cx - 28 + int(self._scan_x), int(eye_y) + 1, 8, 6)

        elif eye_style == "dots":
            for i, off in enumerate([-18, 0, 18]):
                phase = (self.frame + i * 10) % 30
                dot_y = eye_y - 8 - (6 if phase < 15 else 0)
                alpha = 255 if phase < 15 else 120
                p.setBrush(QColor(200, 220, 255, alpha))
                p.drawEllipse(QRectF(cx + off - 5, dot_y, 10, 10))

        elif eye_style == "busy":
            p.setBrush(Qt.white)
            p.drawEllipse(QRectF(eye_l_x, eye_y, 12, 16))
            p.drawEllipse(QRectF(eye_r_x, eye_y, 12, 16))
            p.setBrush(QColor("#f97316"))
            for ex, ey in [(eye_l_x, eye_y), (eye_r_x, eye_y)]:
                angle = math.radians(self._gear_ang)
                px = ex + 6 + math.cos(angle) * 3.5
                py = ey + 8 + math.sin(angle) * 3.5
                p.drawEllipse(QRectF(px - 3.5, py - 3.5, 7, 7))

        elif eye_style == "cross":
            p.setPen(QPen(QColor("#ff2222"), 3))
            for ex in [eye_l_x + 6, eye_r_x + 6]:
                eyc = eye_y + 8
                p.drawLine(int(ex)-5, int(eyc)-5, int(ex)+5, int(eyc)+5)
                p.drawLine(int(ex)+5, int(eyc)-5, int(ex)-5, int(eyc)+5)
            p.setPen(Qt.NoPen)

        elif eye_style == "star":
            p.setPen(QPen(QColor("#facc15"), 2))
            for angle in range(0, 360, 45):
                r = math.radians(angle + self.frame * 2)
                x1 = cx + math.cos(r) * 8
                y1 = cy + math.sin(r) * 8
                x2 = cx + math.cos(r) * 26
                y2 = cy + math.sin(r) * 26
                p.drawLine(int(x1), int(y1), int(x2), int(y2))
            p.setPen(Qt.NoPen)

        # ── Mouth ─────────────────────────────────────────────────────────
        mouth_y = cy + 18
        p.setPen(QPen(Qt.white, 2))
        p.setBrush(Qt.NoBrush)
        if self.state == "error":
            p.drawArc(QRectF(cx - 14, mouth_y, 28, 12), 0, -180 * 16)
        elif self.state == "success":
            p.drawArc(QRectF(cx - 18, mouth_y - 6, 36, 18), 0, -180 * 16)
        elif self.state == "thinking":
            p.drawArc(QRectF(cx - 8, mouth_y + 2, 16, 8), 0, -180 * 16)
        else:
            p.drawLine(cx - 12, int(mouth_y) + 6,
                       cx + 12, int(mouth_y) + 6)

        # ── Writing arm ───────────────────────────────────────────────────
        if self.state == "writing":
            arm_swing = int(math.sin(math.radians(self.frame * 7)) * 10)
            p.setPen(QPen(base_color.lighter(170), 3))
            p.drawLine(cx + 28, body_top + 10,
                       cx + 48, body_top + 25 + arm_swing)
            p.setBrush(QColor("#fffde7"))
            p.setPen(Qt.NoPen)
            p.drawRect(cx + 46, body_top + 23 + arm_swing, 8, 4)
            # Finger dots
            for fi in range(3):
                fdot_x = cx + 48 + fi * 3
                fdot_y = body_top + 29 + arm_swing + int(
                    math.sin(math.radians(self.frame * 10 + fi * 120)) * 2)
                p.setBrush(base_color.lighter(180))
                p.drawEllipse(QRectF(fdot_x, fdot_y, 3, 3))

        # ── State label banner ────────────────────────────────────────────
        banner_y = self.H - 22
        banner_grad = QLinearGradient(0, banner_y, self.W, banner_y + 18)
        banner_grad.setColorAt(0, QColor(base_color.red(), base_color.green(),
                                         base_color.blue(), 180))
        banner_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(banner_grad))
        p.setPen(Qt.NoPen)
        p.drawRect(0, banner_y, self.W, 18)

        # Label text
        p.setPen(QPen(base_color.lighter(200), 1))
        font = QFont("Consolas", 7, QFont.Bold)
        p.setFont(font)
        p.drawText(QRectF(0, banner_y + 1, self.W, 16),
                   Qt.AlignCenter,
                   f"{self.label} · {self.state.upper()}")


# ═══════════════════════════════════════════════════════════════════════════
#  ThoughtChannel  — single scrolling thought stream
# ═══════════════════════════════════════════════════════════════════════════
class ThoughtChannel(QWidget):
    """One scrollable column of thoughts."""

    def __init__(self, channel_name: str, parent=None):
        super().__init__(parent)
        self.channel_name = channel_name
        self._paused = False
        cfg = CHANNEL_COLORS.get(channel_name, DEFAULT_CHANNEL)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        header = QLabel(f"◈ {channel_name.upper()}")
        header.setStyleSheet(
            f"color:{cfg['header']};font-weight:bold;font-size:13px;"
            f"background:{cfg['bg']};padding:5px;border-radius:{TH('radius','6')}px;"
        )
        header.setAlignment(Qt.AlignCenter)
        lay.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setFixedWidth(34)
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)
        toolbar.addWidget(self.pause_btn)

        self.clear_btn = QPushButton("🗑")
        self.clear_btn.setFixedWidth(34)
        toolbar.addWidget(self.clear_btn)

        self.count_label = QLabel("0")
        self.count_label.setStyleSheet(
            f"color:{cfg['header']};font-size:10px;")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        lay.addLayout(toolbar)

        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        self._display.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._display.setStyleSheet(
            f"background:{cfg['bg']};color:{cfg['text']};"
            f"border:1px solid {cfg['header']}44;font-size:11px;"
        )
        lay.addWidget(self._display)

        self.clear_btn.clicked.connect(self._clear)
        self._entry_count = 0

    def _on_pause(self, checked: bool):
        self._paused = checked
        self.pause_btn.setText("▶" if checked else "⏸")

    def _clear(self):
        self._display.clear()
        self._entry_count = 0
        self.count_label.setText("0")

    def append(self, text: str, prefix: str = ""):
        if self._paused:
            return
        cfg = CHANNEL_COLORS.get(self.channel_name, DEFAULT_CHANNEL)
        ts = datetime.now().strftime("%H:%M:%S")
        safe = (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
        label = f"[{prefix}] " if prefix else ""
        html = (
            f'<span style="color:{cfg["header"]};font-size:10px;">[{ts}]</span> '
            f'<span style="color:{cfg["header"]}88;">{label}</span>'
            f'<span style="color:{cfg["text"]};">{safe}</span>'
        )
        self._display.appendHtml(html)
        sb = self._display.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._entry_count += 1
        self.count_label.setText(str(self._entry_count))


# ═══════════════════════════════════════════════════════════════════════════
#  Separated thought windows  — one per channel
# ═══════════════════════════════════════════════════════════════════════════
def _make_channel_window(channel_name: str, parent=None) -> QDialog:
    """
    Create a standalone floating window for a single thought channel.
    Returns (dialog, channel_widget).
    """
    cfg = CHANNEL_COLORS.get(channel_name, DEFAULT_CHANNEL)
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"◈ {channel_name} Thoughts")
    dlg.resize(680, 520)
    ui_style(dlg, lambda w=dlg: w.setStyleSheet(
        f"QDialog{{background:{cfg['bg']};color:{cfg['text']};}}"
        f"QPushButton{{background:{cfg['bg']};color:{cfg['header']};"
        f"border:1px solid {cfg['header']};padding:4px;border-radius:{TH('radius','6')}px;}}"
        f"QPushButton:hover{{background:{cfg['header']};color:#000;}}"
    ))
    lay = QVBoxLayout(dlg)

    # Global controls
    ctrl = QHBoxLayout()
    pause_all  = QPushButton("⏸ Pause")
    resume_all = QPushButton("▶ Resume")
    clear_all  = QPushButton("🗑 Clear")
    for btn in (pause_all, resume_all, clear_all):
        ctrl.addWidget(btn)
    ctrl.addStretch()
    lay.addLayout(ctrl)

    ch = ThoughtChannel(channel_name)
    lay.addWidget(ch)

    pause_all.clicked.connect(lambda: ch.pause_btn.setChecked(True))
    resume_all.clicked.connect(lambda: ch.pause_btn.setChecked(False))
    clear_all.clicked.connect(ch._clear)

    dlg._channel = ch  # attach for external access
    return dlg


class ManagerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        dlg = _make_channel_window("Manager", parent)
        # Copy the built window's layout — we ARE the window
        self.setWindowTitle(dlg.windowTitle())
        self.resize(680, 520)
        self._channel = ThoughtChannel("Manager")
        lay = QVBoxLayout(self)
        ctrl = QHBoxLayout()
        for label, slot in [("⏸ Pause",  lambda: self._channel.pause_btn.setChecked(True)),
                             ("▶ Resume", lambda: self._channel.pause_btn.setChecked(False)),
                             ("🗑 Clear",  self._channel._clear)]:
            b = QPushButton(label); b.clicked.connect(slot); ctrl.addWidget(b)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        lay.addWidget(self._channel)

    def append(self, text: str, prefix: str = ""):
        self._channel.append(text, prefix)


class AgentWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("◈ Agent Thoughts")
        self.resize(680, 520)
        self._channel = ThoughtChannel("Agent")
        lay = QVBoxLayout(self)
        ctrl = QHBoxLayout()
        for label, slot in [("⏸ Pause",  lambda: self._channel.pause_btn.setChecked(True)),
                             ("▶ Resume", lambda: self._channel.pause_btn.setChecked(False)),
                             ("🗑 Clear",  self._channel._clear)]:
            b = QPushButton(label); b.clicked.connect(slot); ctrl.addWidget(b)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        lay.addWidget(self._channel)

    def append(self, text: str, prefix: str = ""):
        self._channel.append(text, prefix)


class CommsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("◈ Comms Channel")
        self.resize(680, 520)
        self._channel = ThoughtChannel("Comms")
        lay = QVBoxLayout(self)
        ctrl = QHBoxLayout()
        for label, slot in [("⏸ Pause",  lambda: self._channel.pause_btn.setChecked(True)),
                             ("▶ Resume", lambda: self._channel.pause_btn.setChecked(False)),
                             ("🗑 Clear",  self._channel._clear)]:
            b = QPushButton(label); b.clicked.connect(slot); ctrl.addWidget(b)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        lay.addWidget(self._channel)

    def append(self, text: str, prefix: str = ""):
        self._channel.append(text, prefix)


# ═══════════════════════════════════════════════════════════════════════════
#  SummaryWindow  — dedicated summary channel window
# ═══════════════════════════════════════════════════════════════════════════
class SummaryWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("◈ Summaries")
        self.resize(720, 560)
        cfg = CHANNEL_COLORS["Summary"]
        self.setStyleSheet(
            f"QDialog{{background:{cfg['bg']};color:{cfg['text']};}}"
        )
        self._channel = ThoughtChannel("Summary")
        lay = QVBoxLayout(self)
        ctrl = QHBoxLayout()
        for label, slot in [("⏸ Pause",  lambda: self._channel.pause_btn.setChecked(True)),
                             ("▶ Resume", lambda: self._channel.pause_btn.setChecked(False)),
                             ("🗑 Clear",  self._channel._clear)]:
            b = QPushButton(label); b.clicked.connect(slot); ctrl.addWidget(b)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        lay.addWidget(self._channel)

    def append_summary(self, text: str):
        self._channel.append(text)


# ═══════════════════════════════════════════════════════════════════════════
#  QuadThoughtPanel — backward-compat wrapper + pop-out buttons
# ═══════════════════════════════════════════════════════════════════════════
class QuadThoughtPanel(QDialog):
    """
    Kept for backward compatibility.
    Now shows compact channel strips with a 'Pop Out' button for each.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thought Overview — All Channels")
        self.resize(1400, 640)

        # v2.0.34an: do NOT eagerly construct the four floating QDialog
        # sub-windows here. Building top-level QDialogs during MainWindow.__init__
        # (before window.show()) makes Windows/PySide6 briefly paint each one's
        # frame at launch — the "flashing pop-up windows" on startup. They are
        # created lazily on first use via _win() instead.
        self._windows = {}  # name -> QDialog

        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("◈ All channels — click 'Pop Out' to open each in its own window"))
        top.addStretch()
        for label, name in [
            ("Manager",  "Manager"),
            ("Agent",    "Agent"),
            ("Comms",    "Comms"),
            ("Summary",  "Summary"),
        ]:
            btn = QPushButton(f"🗗 {label}")
            btn.setFixedWidth(110)
            btn.clicked.connect(lambda *a, n=name: self._win(n).show())
            btn.clicked.connect(lambda *a, n=name: self._win(n).raise_())
            top.addWidget(btn)
        lay.addLayout(top)

        # Compact inline preview strips (splitter)
        splitter = QSplitter(Qt.Horizontal)
        for win, name in [
            (None, "Manager"),
            (None, "Agent"),
            (None, "Comms"),
            (None, "Summary"),
        ]:
            preview = ThoughtChannel(name)
            # Wire: when the win's channel gets a message, mirror to preview
            # (done via route() below)
            setattr(self, f"_preview_{name.lower()}", preview)
            splitter.addWidget(preview)
        splitter.setSizes([350, 350, 350, 350])
        lay.addWidget(splitter)

    def _win(self, name: str):
        """Lazily create (once) and return a floating channel window.

        Fixes the startup flash: the QDialogs are no longer built during
        MainWindow.__init__, only when the operator first opens one.
        """
        if name not in self._windows:
            cls = {"Manager": ManagerWindow, "Agent": AgentWindow,
                   "Comms": CommsWindow, "Summary": SummaryWindow}[name]
            self._windows[name] = cls(self.parent())
        return self._windows[name]

    # ── Routing ──────────────────────────────────────────────────────────────
    def route(self, channel: str, text: str, prefix: str = ""):
        """Route a message to the correct channel(s)."""
        channels_map = {
            "Manager":  [self._win("Manager"), self._preview_manager],
            "Agent":    [self._win("Agent"),   self._preview_agent],
            "Comms":    [self._win("Comms"),   self._preview_comms],
            "Summary":  [self._win("Summary"), self._preview_summary],
        }
        if channel == "System":
            for target in [self._win("Manager"), self._preview_manager,
                           self._win("Agent"),   self._preview_agent]:
                target.append(text, "SYS")
        elif channel in channels_map:
            for target in channels_map[channel]:
                target.append(text, prefix)
        else:
            self._win("Manager").append(text, channel)
            self._preview_manager.append(text, channel)

    def route_summary(self, text: str):
        self._win("Summary").append_summary(text)
        self._preview_summary.append(text)

    # Legacy alias helpers for main.py
    @property
    def manager_channel(self):  return self._preview_manager
    @property
    def agent_channel(self):    return self._preview_agent
    @property
    def comms_channel(self):    return self._preview_comms
    @property
    def summary_channel(self):  return self._preview_summary

    def _pause_all(self):
        for ch in (self._preview_manager, self._preview_agent,
                   self._preview_comms, self._preview_summary):
            ch.pause_btn.setChecked(True)

    def _resume_all(self):
        for ch in (self._preview_manager, self._preview_agent,
                   self._preview_comms, self._preview_summary):
            ch.pause_btn.setChecked(False)

    def _clear_all(self):
        for ch in (self._preview_manager, self._preview_agent,
                   self._preview_comms, self._preview_summary):
            ch._clear()


# ═══════════════════════════════════════════════════════════════════════════
#  AgentsTab — v4: chat + live info panel, no office scene
# ═══════════════════════════════════════════════════════════════════════════
class AgentsTab(QWidget):
    """
    Agents tab with animated sprites and roster controls.
    No 2D office scene — lightweight for earning-focused workflows.
    """

    def __init__(self, parent,
                 worker_sprite: "AgentSprite",
                 summarizer_sprite: "AgentSprite",
                 worker_status_signal,
                 summarizer_status_signal,
                 show_thoughts_cb,
                 show_chat_cb=None,
                 toggle_worker_pause_cb=None,
                 toggle_summarizer_pause_cb=None,
                 show_summarizer_window_cb=None,
                 heartbeat_interval=None,
                 on_send=None,
                 on_strategy_change=None,
                 show_manager_win_cb=None,
                 show_agent_win_cb=None,
                 show_comms_win_cb=None,
                 show_summary_win_cb=None,
                 show_summarizer_chat_cb=None):
        super().__init__(parent)

        self.worker_sprite    = worker_sprite
        self.summarizer_sprite = summarizer_sprite
        self.heartbeat_interval = heartbeat_interval

        self.show_thoughts_cb           = show_thoughts_cb
        self.show_chat_cb               = show_chat_cb or (lambda: None)
        self.toggle_worker_pause_cb     = toggle_worker_pause_cb or (lambda: None)
        self.toggle_summarizer_pause_cb = toggle_summarizer_pause_cb or (lambda: None)
        self.show_summarizer_window_cb  = show_summarizer_window_cb or (lambda: None)

        self._on_send = on_send
        self._on_strategy_change = on_strategy_change

        self._show_manager_win    = show_manager_win_cb    or (lambda: None)
        self._show_agent_win      = show_agent_win_cb      or (lambda: None)
        self._show_comms_win      = show_comms_win_cb      or (lambda: None)
        self._show_summary_win    = show_summary_win_cb    or (lambda: None)
        self._show_summarizer_chat = show_summarizer_chat_cb or (lambda: None)

        # Roster status labels  {role: QLabel}
        self._roster_labels: Dict[str, QLabel] = {}

        worker_status_signal.connect(self._on_worker_status)
        summarizer_status_signal.connect(self._on_summarizer_status)

        self._init_ui()

    # ── Build UI ──────────────────────────────────────────────────────

    def _init_ui(self):
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 8)
        vlay.setSpacing(8)

        # ── Top: embedded chat surface ───────────────────────────────
        chat_group = QGroupBox("Assistant Chat")
        ui_style(chat_group, lambda w=chat_group: w.setStyleSheet(
            f"QGroupBox{{border:1px solid {TH('accent')}44;border-radius:{TH('radius','6')}px;"
            f"margin-top:8px;padding-top:8px;color:{TH('accent')};}}"
        ))
        chat_lay = QVBoxLayout(chat_group)
        chat_lay.setContentsMargins(8, 8, 8, 8)
        chat_lay.setSpacing(6)

        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        ui_style(self._display, lambda w=self._display: w.setStyleSheet(
            f"background:{TH('surface')};color:{TH('fg')};font-size:12px;"
            f"border:1px solid {TH('border')};border-radius:{TH('radius','6')}px;"
        ))
        self._display.setPlaceholderText("Assistant output will appear here…")
        self._display.setCenterOnScroll(True)
        chat_lay.addWidget(self._display, stretch=1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Message the assistant… (Enter to send)")
        self._input.returnPressed.connect(self.send)
        self._char_lbl = QLabel("0")
        self._char_lbl.setFixedWidth(36)
        ui_style(self._char_lbl, lambda w=self._char_lbl: w.setStyleSheet(f"color:{TH('muted')};font-size:10px;"))
        self._input.textChanged.connect(
            lambda t: self._char_lbl.setText(str(len(t))))
        send_btn = QPushButton("Send ➤")
        send_btn.clicked.connect(self.send)
        input_row.addWidget(self._input)
        input_row.addWidget(self._char_lbl)
        input_row.addWidget(send_btn)
        chat_lay.addLayout(input_row)

        # ── Side panel: Collapsible notifications ─────────────────────
        self._notifications_toggle = QPushButton(" Notifications")
        self._notifications_toggle.setCheckable(True)
        self._notifications_toggle.setChecked(True)
        ui_style(self._notifications_toggle, lambda w=self._notifications_toggle: w.setStyleSheet(
            f"QPushButton{{border:1px solid {TH('accent')}44;border-radius:{TH('radius','6')}px;"
            f"padding:4px;font-size:10px;background:{TH('surface')};color:{TH('accent')};}}"
        ))
        self._notifications_toggle.clicked.connect(self._toggle_notifications)

        notifications_group = QGroupBox("Agent Notifications")
        ui_style(notifications_group, lambda w=notifications_group: w.setStyleSheet(
            f"QGroupBox{{border:1px solid {TH('accent')}44;border-radius:{TH('radius','6')}px;"
            f"margin-top:8px;padding-top:8px;color:{TH('accent')};}}"
        ))
        notifications_lay = QVBoxLayout(notifications_group)
        notifications_lay.setContentsMargins(4, 4, 4, 4)
        notifications_lay.setSpacing(4)
        notifications_lay.addWidget(self._notifications_toggle)

        self._notifications_list = QListWidget()
        ui_style(self._notifications_list, lambda w=self._notifications_list: w.setStyleSheet(
            f"font-family:Consolas,Monaco,monospace;font-size:10px;"
            f"background:{TH('surface')};color:{TH('fg')};"
            f"border:1px solid {TH('border')};border-radius:{TH('radius','6')}px;"
        ))
        self._notifications_list.setAlternatingRowColors(True)
        self._notifications_list.setSelectionMode(QListWidget.NoSelection)
        notifications_lay.addWidget(self._notifications_list)

        # Use splitter to separate chat from notifications (resizable)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(chat_group)
        main_splitter.addWidget(notifications_group)
        main_splitter.setStretchFactor(0, 3)  # Chat takes 3x space
        main_splitter.setStretchFactor(1, 1)  # Notifications smaller
        vlay.addWidget(main_splitter, stretch=2)

        # ── Bottom: live info + controls ─────────────────────────────
        bottom = QWidget()
        bottom_lay = QHBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 0, 0, 0)
        bottom_lay.setSpacing(8)

        # Agent roster with live status
        roster_grp = QGroupBox("🏢 Agent Roster")
        roster_grp.setMinimumWidth(220)
        roster_grp.setMaximumWidth(280)
        roster_inner = QVBoxLayout(roster_grp)
        roster_inner.setSpacing(4)
        for role in ("Manager", "JobSearch", "Analyst", "Coder", "Summarizer"):
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setFixedWidth(14)
            dot.setStyleSheet("color:#22c55e;font-size:11px;")
            lbl = QLabel(f"{role}: idle")
            lbl.setStyleSheet("font-size:11px;color:#aaaaaa;")
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()
            roster_inner.addLayout(row)
            self._roster_labels[role] = (dot, lbl)
        bottom_lay.addWidget(roster_grp, stretch=1)

        # Current actions panel
        actions_grp = QGroupBox("⚡ Current Actions")
        actions_grp.setMinimumWidth(260)
        actions_lay = QVBoxLayout(actions_grp)
        actions_lay.setSpacing(4)
        self._actions_list = QListWidget()
        self._actions_list.setStyleSheet(
            "font-family:Consolas,Monaco,monospace;font-size:11px;"
        )
        actions_lay.addWidget(self._actions_list)
        bottom_lay.addWidget(actions_grp, stretch=2)

        # Controls
        ctrl_grp = QGroupBox("⚙ Controls")
        ctrl_grp.setMinimumWidth(180)
        ctrl_lay = QVBoxLayout(ctrl_grp)
        ctrl_lay.setSpacing(6)

        self.last_heartbeat_label = QLabel("Last heartbeat: never")
        ui_style(self.last_heartbeat_label, lambda w=self.last_heartbeat_label: w.setStyleSheet(f"color:{TH('muted')};font-size:10px;"))
        self.last_heartbeat_label.setWordWrap(True)
        ctrl_lay.addWidget(self.last_heartbeat_label)

        self.heartbeat_label = QLabel(f"Heartbeat every {self.heartbeat_interval}s")
        ui_style(self.heartbeat_label, lambda w=self.heartbeat_label: w.setStyleSheet(f"color:{TH('muted')};font-size:10px;"))
        ctrl_lay.addWidget(self.heartbeat_label)

        self.worker_progress = QProgressBar()
        self.worker_progress.setRange(0, 0)
        self.worker_progress.setVisible(False)
        self.worker_progress.setMaximumHeight(8)
        ctrl_lay.addWidget(self.worker_progress)

        pause_row = QHBoxLayout()
        self.pause_btn = QPushButton("⏸ Pause Manager")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setFocusPolicy(Qt.NoFocus)
        self.pause_btn.toggled.connect(self.toggle_worker_pause_cb)
        pause_row.addWidget(self.pause_btn)

        self.summarizer_pause_btn = QPushButton("⏸ Pause Summarizer")
        self.summarizer_pause_btn.setCheckable(True)
        self.summarizer_pause_btn.setFocusPolicy(Qt.NoFocus)
        self.summarizer_pause_btn.toggled.connect(self.toggle_summarizer_pause_cb)
        pause_row.addWidget(self.summarizer_pause_btn)
        ctrl_lay.addLayout(pause_row)

        bottom_lay.addWidget(ctrl_grp, stretch=1)
        vlay.addWidget(bottom, stretch=1)

    # ── Signal handlers ───────────────────────────────────────────────

    def _on_worker_status(self, status: str, task: str):
        role = "Coder"
        state = "idle"
        if ":" in status:
            parts = status.split(":", 1)
            role  = parts[0].strip()
            state_str = parts[1].strip()
        else:
            state_str = status

        for key, mapped in self._STATUS_STATE_MAP.items():
            if key.lower() in state_str.lower():
                state = mapped
                break

        # Update roster/actions panels
        self._update_roster_label(role, state, task)
        self._append_action(f"{role}: {task or state}")

        # Progress bar visible when any worker is busy
        self.worker_progress.setVisible(
            state in ("working", "researching", "writing", "thinking"))

        # Update heartbeat label
        self.last_heartbeat_label.setText(
            f"Last action: {__import__('datetime').datetime.now().strftime('%H:%M:%S')}")

    def _on_summarizer_status(self, status: str, task: str):
        state_str = status.lower()
        state = "idle"
        for key, mapped in self._STATUS_STATE_MAP.items():
            if key.lower() in state_str:
                state = mapped
                break
        self._update_roster_label("Summarizer", state, task)
        self._append_action(f"Summarizer: {task or state}")

    # Keep the old status map for backward compat
    _STATUS_STATE_MAP = {
        "Working":     "working",
        "Thinking":    "thinking",
        "Researching": "researching",
        "Writing":     "writing",
        "Idle":        "idle",
        "Ready":       "idle",
        "Error":       "error",
        "Chatting":    "communicating",
    }

    def _update_roster_label(self, role: str, state: str, task: str = ""):
        if role not in self._roster_labels:
            return
        dot_lbl, text_lbl = self._roster_labels[role]
        color_map = {
            "working": "#f97316", "thinking": "#3b82f6",
            "researching": "#06b6d4", "writing": "#84cc16",
            "communicating": "#a855f7", "success": "#facc15",
            "error": "#ef4444", "idle": "#22c55e",
        }
        col = color_map.get(state, "#22c55e")
        dot_lbl.setStyleSheet(f"color:{col};font-size:10px;")
        task_short = f" — {task[:30]}" if task else ""
        text_lbl.setText(f"{role}: {state}{task_short}")

    def _append_action(self, text: str):
        ts = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"[{ts}] {text}")
        color_map = {
            "Manager": "#00ccff",
            "Summarizer": "#00b0ff",
            "JobSearch": "#f97316",
            "Analyst": "#06b6d4",
            "Coder": "#84cc16",
        }
        for role, color in color_map.items():
            if role in text:
                item.setForeground(QColor(color))
                break
        self._actions_list.addItem(item)
        if self._actions_list.count() > 200:
            self._actions_list.takeItem(0)

    # ── Embedded chat surface methods ───────────────────────────────

    def send(self):
        text = self._input.text().strip()
        if not text:
            return
        self.append_you(text)
        if self._on_send:
            self._on_send(text)
        self._input.clear()

    @staticmethod
    def _strip_think(text: str):
        """Split model output into (clean_text, think_text).

        Some reasoning models (e.g. qwen3/think-enabled) emit an inline
        `<think:6124c78e>...</think:6124c78e>` block before the answer. Left in the displayed
        text it shows verbatim as raw tags — strip it out and return the
        reasoning separately so the UI can render it in a collapsible block
        instead of leaking `<think>` into the chat bubble.
        """
        if not text:
            return "", ""
        # Greedy match of complete think blocks (handles multiple).
        parts = re.split(r"<\s*think\s*>.*?<\s*/\s*think\s*>", text, flags=re.DOTALL | re.IGNORECASE)
        think_blocks = re.findall(r"<\s*think\s*>.*?<\s*/\s*think\s*>", text, flags=re.DOTALL | re.IGNORECASE)
        clean = "".join(parts).strip()
        # Also handle an unterminated trailing think block (stream cut off).
        open_m = re.search(r"<\s*think\s*>[^<]*$", clean, flags=re.IGNORECASE)
        if open_m:
            clean = clean[: open_m.start()].strip()
            think_blocks.append(open_m.group(0))
        think = "\n\n".join(
            b.replace("\n", " ").strip().strip("`").strip()
            for b in think_blocks
        )
        # Fall back to any leading raw block if regex left debris.
        return clean, think

    def append_you(self, text: str, thinking: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        clean, stripped = self._strip_think(text)
        if stripped:
            thinking = (thinking + "\n\n" + stripped).strip()
        safe = clean.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        # v2.0.24: render model reasoning as a collapsible <details> block
        # (expandable/hideable) above the answer for Assistant/Answer replies.
        # Shown whenever reasoning exists (from the `thinking` arg OR stripped
        # out of the model's inline <think:6124c78e> block) — never as raw text.
        think_html = ""
        if thinking:
            _t = thinking.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            show = not getattr(self, "_show_think_chk", None) or self._show_think_chk.isChecked()
            if show:
                think_html = (
                    f'<details style="margin:2px 0 4px 0;">'
                    f'<summary style="cursor:pointer;color:{TH("accent")};font-size:11px;">'
                    f'🧠 Thinking (click to expand)</summary>'
                    f'<div style="color:{TH("muted")};font-size:11px;white-space:pre-wrap;'
                    f'max-height:240px;overflow:auto;padding:4px 6px;'
                    f'background:transparent;border-left:3px solid {TH("accent")}55;">{_t}</div>'
                    f'</details>'
                )
        self._display.appendHtml(
            f'<span style="color:{TH("muted")};">[{ts}]</span> '
            f'<span style="color:{TH("success")};font-weight:bold;">You:</span> '
            f'<span style="color:#e0f7fa;">{safe}</span>'
        )
        sb = self._display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append_reply(self, label: str, text: str, thinking: str = ""):
        """Append a message - notifications go to sidebar, chat stays clean."""
        ts = datetime.now().strftime("%H:%M:%S")
        clean, stripped = self._strip_think(text)
        if stripped:
            thinking = (thinking + "\n\n" + stripped).strip()
        safe = clean.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        # v2.0.24: render model reasoning as a collapsible <details> block
        # (expandable/hideable) above the answer. Shown whenever reasoning
        # exists (from the `thinking` arg OR stripped out of the model's
        # inline <think:6124c78e> block) — never as raw text in the bubble.
        think_html = ""
        if thinking:
            _t = thinking.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            show = not getattr(self, "_show_think_chk", None) or self._show_think_chk.isChecked()
            if show:
                think_html = (
                    f'<details style="margin:2px 0 4px 0;">'
                    f'<summary style="cursor:pointer;color:{TH("accent")};font-size:11px;">'
                    f'🧠 Thinking (click to expand)</summary>'
                    f'<div style="color:{TH("muted")};font-size:11px;white-space:pre-wrap;'
                    f'max-height:240px;overflow:auto;padding:4px 6px;'
                    f'background:transparent;border-left:3px solid {TH("accent")}55;">{_t}</div>'
                    f'</details>'
                )
        # Route notifications to sidebar, chat to main display
        # Check both label and text (text contains [Heartbeat] for Manager messages)
        is_notification = any(x in label or f"[{x}]" in text for x in ["Heartbeat", "Worker",
                          "Result", "JobSearch", "Analyst", "Coder", "Action", "Evaluator"])
        if "lifecycle" in text.lower() or ("opportunity" in text.lower() and "status" in text.lower()):
            self._display.appendHtml(
                f'<span style="color:{TH("muted")};">[{ts}]</span> '
                f'<span style="color:{TH("accent")};font-weight:bold;">📊 Opportunity Update:</span><br>'
                f'<span style="color:{TH("fg")};">{safe}</span><br>'
            )
            self._append_notification(label, ts, safe)
            self._maybe_autoscroll()
            return
        if is_notification:
            self._append_notification(label, ts, safe)
        elif "Manager" in label:
            self._display.appendHtml(
                f'<span style="color:{TH("muted")};">[{ts}]</span> '
                f'<span style="color:{TH("highlight")};font-weight:bold;">{label}:</span><br>'
                f'{think_html}'
                f'<span style="color:#d4aaff;">{safe}</span><br>'
            )
        elif "Summarizer" in label or "Answer" in label:
            self._display.appendHtml(
                f'<span style="color:{TH("muted")};">[{ts}]</span> '
                f'<span style="color:{TH("accent")};font-weight:bold;">🤖 Assistant:</span><br>'
                f'{think_html}'
                f'<span style="color:{TH("fg")};">{safe}</span><br>'
            )
        else:
            self._display.appendHtml(
                f'<span style="color:{TH("muted")};">[{ts}]</span> '
                f'<span style="color:{TH("success")};font-weight:bold;">{label}:</span><br>'
                f'{think_html}'
                f'<span style="color:#e0e0e0;">{safe}</span>'
            )
        self._maybe_autoscroll()


    def _maybe_autoscroll(self):
        """Scroll to bottom only if user is already at/near bottom.
        If they scrolled up to read, keep position (no yank on notifications)."""
        sb = self._display.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 24
        if at_bottom:
            sb.setValue(sb.maximum())

    def _append_notification(self, label: str, ts: str, text: str):
        """Append agent notifications to the collapsible sidebar panel.
        Always appends (no isVisible() gate) — the toggle only hides the
        list widget; dropping messages when hidden left the panel blank."""
        lst = getattr(self, '_notifications_list', None)
        if lst is None:
            return
        lst.addItem(f"[{ts}] {label}: {text}")
        sb = lst.verticalScrollBar()
        sb.setValue(sb.maximum())

    
    def _toggle_notifications(self):
        """Toggle the visibility of the notifications panel."""
        is_visible = self._notifications_list.isVisible()
        self._notifications_list.setVisible(not is_visible)
        self._notifications_toggle.setText(" Notifications" if is_visible else "Hide Notifications")
        self._notifications_toggle.setChecked(not is_visible)
# ── Layout editor callbacks (kept for compat but no-op without office) ──

    def set_layout_edit_allowed(self, allowed: bool):
        pass

    def set_layout_callbacks(self, save_cb=None, load_cb=None):
        pass

    # ── Compat methods ────────────────────────────────────────────────

    def set_heartbeat_interval(self, interval):
        self.heartbeat_interval = interval
        self.heartbeat_label.setText(f"Heartbeat every {interval}s")

    def set_pause_button_state(self, paused: bool):
        self.pause_btn.setChecked(paused)

    def set_summarizer_pause_button_state(self, paused: bool):
        self.summarizer_pause_btn.setChecked(paused)

    # Backward compat label attrs that main.py might reference
    @property
    def worker_status_label(self):
        _, lbl = self._roster_labels.get("Coder", (None, QLabel()))
        return lbl

    @property
    def worker_task_label(self):
        _, lbl = self._roster_labels.get("Manager", (None, QLabel()))
        return lbl

    @property
    def summarizer_status_label(self):
        _, lbl = self._roster_labels.get("Summarizer", (None, QLabel()))
        return lbl

    @property
    def summarizer_task_label(self):
        _, lbl = self._roster_labels.get("Summarizer", (None, QLabel()))
        return lbl