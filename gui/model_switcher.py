# ═══════════════════════════════════════════════════════════════════════════
# DUAL BRAIN MODEL SWITCHER — v2.5 (llama.cpp both brains)
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: Switch between downloaded models for both brains.
#          Both brains use llama-server (llama.cpp).
#          Small Brain on port 1235, Big Brain on port 1234.
#
# TO REMOVE THIS FEATURE:
#   1. Delete this file (gui/model_switcher.py)
#   2. Remove ModelSwitcher from gui/dual_brain_control.py
# ═══════════════════════════════════════════════════════════════════════════

import os
import sys
import urllib.request
import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QFrame
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont


class ModelSwitcher(QWidget):
    """Widget for switching models in both brains."""
    
    small_brain_model_changed = Signal(str)  # model_name
    big_brain_model_changed = Signal(str)    # model_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        # Defer initial model refresh to avoid blocking startup with HTTP calls
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_models)
        self._refresh_timer.start(2000)  # 2s after widget shown
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # ── Model Switcher Group ───────────────────────────────────────
        group = QGroupBox("🔄 Model Switcher (llama-server)")
        group.setStyleSheet("""
            QGroupBox {
                color: #ffb300;
                font-weight: bold;
                border: 2px solid #ffb300;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                sub-control-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        grid = QGridLayout(group)
        
        # Small Brain Model Selector
        sb_label = QLabel("🤖 Small Brain (1660 Super)")
        sb_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        sb_label.setStyleSheet("color: #03dac6;")
        grid.addWidget(sb_label, 0, 0)
        
        self.sb_model_combo = QComboBox()
        self.sb_model_combo.setMinimumWidth(300)
        self.sb_model_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 8px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #e0e0e0;
                selection-background-color: #03dac6;
            }
        """)
        self.sb_model_combo.currentTextChanged.connect(self._on_small_brain_model_changed)
        grid.addWidget(self.sb_model_combo, 0, 1)
        
        self.sb_refresh_btn = QPushButton("🔄 Refresh")
        self.sb_refresh_btn.setStyleSheet("""
            QPushButton {
                background: #03dac6;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #03dac6cc; }
        """)
        self.sb_refresh_btn.clicked.connect(self.refresh_models)
        grid.addWidget(self.sb_refresh_btn, 0, 2)
        
        # Big Brain Model Selector
        bb_label = QLabel("🧠 Big Brain (5060 Ti)")
        bb_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        bb_label.setStyleSheet("color: #bb86fc;")
        grid.addWidget(bb_label, 1, 0)
        
        self.bb_model_combo = QComboBox()
        self.bb_model_combo.setMinimumWidth(300)
        self.bb_model_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 8px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #e0e0e0;
                selection-background-color: #bb86fc;
            }
        """)
        self.bb_model_combo.currentTextChanged.connect(self._on_big_brain_model_changed)
        grid.addWidget(self.bb_model_combo, 1, 1)
        
        self.bb_refresh_btn = QPushButton("🔄 Refresh")
        self.bb_refresh_btn.setStyleSheet("""
            QPushButton {
                background: #bb86fc;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #bb86fc88; }
        """)
        self.bb_refresh_btn.clicked.connect(self.refresh_models)
        grid.addWidget(self.bb_refresh_btn, 1, 2)
        
        layout.addWidget(group)
        
        # Initial refresh
        self.refresh_models()
    
    def refresh_models(self):
        """Refresh list of available models from llama-server."""
        # Get models from both servers
        sb_models = self._get_llama_models(1235)
        bb_models = self._get_llama_models(1234)
        
        # Block signals to prevent auto-selecting first item
        self.sb_model_combo.blockSignals(True)
        self.bb_model_combo.blockSignals(True)
        
        self.sb_model_combo.clear()
        self.bb_model_combo.clear()
        
        if sb_models:
            self.sb_model_combo.addItems(sb_models)
        else:
            self.sb_model_combo.addItem("No models found")
        
        if bb_models:
            self.bb_model_combo.addItems(bb_models)
        else:
            self.bb_model_combo.addItem("No models found")
        
        self.sb_model_combo.blockSignals(False)
        self.bb_model_combo.blockSignals(False)
        
        # Emit current selection
        sb_current = self.sb_model_combo.currentText()
        bb_current = self.bb_model_combo.currentText()
        if sb_current and sb_current != "No models found":
            self._on_small_brain_model_changed(sb_current)
        if bb_current and bb_current != "No models found":
            self._on_big_brain_model_changed(bb_current)
    
    def _get_llama_models(self, port: int) -> list:
        """Get list of models from llama-server."""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                return [m.get("id", "unknown") for m in data.get("data", [])]
        except Exception:
            return []
    
    def _on_small_brain_model_changed(self, text: str):
        """Handle Small Brain model change."""
        if text and text != "No models found":
            self.small_brain_model_changed.emit(text)
    
    def _on_big_brain_model_changed(self, text: str):
        """Handle Big Brain model change."""
        if text and text != "No models found":
            self.big_brain_model_changed.emit(text)
