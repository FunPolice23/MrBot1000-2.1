"""Visual effects engine (v2.0.26).

Toggleable effects so the UI can trade beauty for performance:
  - antialiasing : high-DPI + render hints on custom-painted widgets
  - soft_shadows : QGraphicsDropShadowEffect on buttons/cards
  - hover_glow   : accent glow on button hover (QSS)
  - transitions  : smooth hover/checked state changes (QSS)
  - animations   : keep ui.py particle/gear animations alive
  - quality_mode  : "Quality" enables all heavy effects; "Performance"
                    flattens (no shadows/animations) for low-end machines.

All effects degrade gracefully if a Qt class is unavailable, and never raise.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict


@dataclass
class EffectSettings:
    antialiasing: bool = True
    soft_shadows: bool = True
    hover_glow: bool = True
    transitions: bool = True
    animations: bool = True
    quality_mode: str = "Quality"  # "Quality" | "Performance"
    render_quality: str = "High"   # "Low" | "Medium" | "High" | "Ultra"
    compact_density: bool = False
    rounded_corners: bool = True
    button_style: str = "2.5D (beveled)"  # "2.5D (beveled)" | "2D (flat)"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "EffectSettings":
        env = os.environ if env is None else env
        def b(name, default):
            v = env.get(f"MRBOT_FX_{name.upper()}")
            if v is None:
                return default
            return v.strip().lower() in ("1", "true", "yes", "on")
        def s(name, default):
            v = env.get(f"MRBOT_FX_{name.upper()}")
            return v if v else default
        q = env.get("MRBOT_FX_QUALITY", "Quality")
        return cls(
            antialiasing=b("antialiasing", True),
            soft_shadows=b("soft_shadows", True),
            hover_glow=b("hover_glow", True),
            transitions=b("transitions", True),
            animations=b("animations", True),
            quality_mode="Performance" if q.lower().startswith("p") else q,
            render_quality=s("render_quality", "High"),
            compact_density=b("compact_density", False),
            rounded_corners=b("rounded_corners", True),
            button_style=s("button_style", "2.5D (beveled)"),
        )

    def effective(self) -> "EffectSettings":
        """Apply the quality-mode master switch: Performance flattens everything."""
        if self.quality_mode == "Performance":
            return EffectSettings(
                antialiasing=self.antialiasing,  # cheap, keep
                soft_shadows=False,
                hover_glow=False,
                transitions=False,
                animations=False,
                quality_mode="Performance",
                render_quality="Low",
                compact_density=self.compact_density,
                rounded_corners=self.rounded_corners,
                button_style="2D (flat)",
            )
        return self

    def to_env_dict(self) -> dict:
        d = asdict(self)
        out = {}
        for k, v in d.items():
            if k == "quality_mode":
                out["MRBOT_FX_QUALITY"] = v
            elif k == "render_quality":
                out["MRBOT_FX_RENDER_QUALITY"] = v
            else:
                out[f"MRBOT_FX_{k.upper()}"] = "true" if v else "false"
        return out


def style_hints_qss(fx: EffectSettings, theme: dict) -> str:
    """QSS fragment for effects that Qt's stylesheet engine actually supports.

    NOTE: Qt QSS is NOT CSS. `transition:` and `box-shadow:` are web-CSS
    properties that Qt silently rejects with "Unknown property" console spam —
    so we do NOT emit them here. Instead:
      - hover_glow  -> border emphasis on QPushButton:hover (real, supported).
      - transitions  -> a subtle background shift on :hover is native; we add a
         visible hover background tint so the state change is perceptible.
      - animations   -> particle/gear animations in ui.py (toggled via set_effects).
      - render_quality-> drives shadow blur/radius + widget radius scale.
      - compact_density -> tighter padding/radius for dense layouts.
      - rounded_corners-> on/off corner radius.
    The soft shadow itself is drawn by QGraphicsDropShadowEffect (apply_shadow),
    not box-shadow.
    """
    parts = []
    if fx.hover_glow:
        parts.append(
            f"QPushButton:hover{{border:1px solid {theme['accent']};"
            f"background:{theme['highlight']};}}")
    if fx.transitions:
        # perceptible hover state (native repaint, no CSS transition needed)
        parts.append(
            f"QPushButton:checked{{background:{theme['highlight']};}}")
    # rounded corners on/off
    radius = theme.get("radius", "6") if fx.rounded_corners else "2"
    parts.append(
        f"QPushButton,QGroupBox,QTextEdit,QLineEdit,QComboBox,QSpinBox{{"
        f"border-radius:{radius}px;}}")
    # compact density: tighter padding
    pad = "3px" if fx.compact_density else "6px"
    parts.append(f"QPushButton{{padding:{pad};}}")
    # render quality scales shadow strength (consumed by apply_shadow) and
    # widget radius slightly.
    # Button visual style: 2.5D bevel (gradient + accent bottom edge) vs 2D flat.
    _radius = theme.get("radius", "6")
    if fx.button_style and fx.button_style.startswith("2.5D"):
        _surf = theme.get("surface", "#2b3034")
        _surf2 = theme.get("surface2", "#1a1a1f")
        parts.append(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {_surf},stop:1 {_surf2});"
            f"border:1px solid {theme['border']};border-bottom:2px solid {theme['accent']};"
            f"border-radius:{_radius}px;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {theme['accent']},stop:1 {theme['highlight']});color:{theme['bg']};}}")
    else:
        parts.append(
            f"QPushButton{{background:{theme['surface']};"
            f"border:1px solid {theme['border']};border-radius:{_radius}px;}}")
    return "\n".join(parts)


# Render-quality -> (shadow_radius, shadow_blur) mapping for apply_shadow.
RENDER_QUALITY_SHADOW = {
    "Low": (0, 0),
    "Medium": (8, 10),
    "High": (12, 18),
    "Ultra": (18, 28),
}
RENDER_QUALITY_PARTICLES = {
    "Low": 0,
    "Medium": 2,
    "High": 3,
    "Ultra": 6,
}


def apply_shadow(widget, theme: dict, fx: EffectSettings, radius: int = 12, blur: int = 18):
    """Attach a soft drop shadow to a widget (button/card). No-op if disabled.

    v2.0.34ap: shadow radius/blur now scale with the Render-quality preset
    (Low=off, Ultra=strong) so the preset has a visible effect.
    """
    if not (fx.soft_shadows and widget is not None):
        try:
            from PySide6.QtWidgets import QGraphicsEffect
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        return
    try:
        import re
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from PySide6.QtGui import QColor
        sr, sb = RENDER_QUALITY_SHADOW.get(fx.render_quality, (radius, blur))
        if sr == 0 and sb == 0:
            widget.setGraphicsEffect(None)
            return
        sh = QGraphicsDropShadowEffect()
        sh.setBlurRadius(sb)
        sh.setOffset(0, 2)
        shadow_str = theme.get("shadow", "rgba(0,0,0,0.45)")
        m = re.match(r"rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\\s]+([\d.]+))?\)",
                     shadow_str or "")
        if m:
            r, g, b = int(float(m.group(1))), int(float(m.group(2))), int(float(m.group(3)))
            a = int(float(m.group(4) if m.group(4) is not None else 1) * 255)
            sh.setColor(QColor(r, g, b, a))
        else:
            sh.setColor(QColor(0, 0, 0, 120))
        widget.setGraphicsEffect(sh)
    except Exception:
        pass


def apply_antialiasing(app) -> None:
    """Enable high-DPI + antialiasing hints on the QApplication (cheap, safe)."""
    try:
        from PySide6.QtCore import Qt, QCoreApplication
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    except Exception:
        pass
