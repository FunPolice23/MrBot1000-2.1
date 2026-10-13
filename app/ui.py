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

