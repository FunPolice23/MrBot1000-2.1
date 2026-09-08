"""
Chat Tab — Human ↔ Small Brain chat.
Uses SmallBrainAdapter (Ollama).
Supports collapsible thinking sections with custom toggle buttons.
"""

import re
import os
import sys

from PySide6.QtWidgets import (
    QWidget, QTextEdit, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFrame, QToolButton,
    QGroupBox, QScrollArea
)
from PySide6.QtCore import Signal, QThread, Qt
from PySide6.QtGui import QFont


class ThinkingBox(QFrame):
    """Collapsible thinking box with toggle button."""
    
    def __init__(self, thinking_text: str, title: str = "🧠 Thinking", color: str = "#bb86fc", parent=None):
        super().__init__(parent)
        self.thinking_text = thinking_text
        self.is_expanded = False
        self.color = color
        self.setup_ui(title)
    
    def setup_ui(self, title: str):
        self.setStyleSheet(f"""
            QFrame {{
                background: #1a1a2e;
                border: 1px solid {self.color}44;
                border-radius: 6px;
                margin: 4px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # Header with toggle
        header = QHBoxLayout()
        
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("▶")
        self.toggle_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                color: {self.color};
                border: none;
                font-size: 12px;
                font-weight: bold;
            }}
        """)
        self.toggle_btn.clicked.connect(self.toggle)
        header.addWidget(self.toggle_btn)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title_label.setStyleSheet(f"color: {self.color};")
        header.addWidget(title_label)
        header.addStretch()
        
        layout.addLayout(header)
        
        # Thinking content (hidden by default)
        self.content = QTextEdit()
        self.content.setReadOnly(True)
        self.content.setPlainText(self.thinking_text)
        self.content.setMaximumHeight(150)
        self.content.setStyleSheet("""
            QTextEdit {
                background: #0a0a1a;
                color: #888;
                border: none;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        self.content.setVisible(False)
        layout.addWidget(self.content)
    
    def toggle(self):
        """Toggle thinking visibility."""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.toggle_btn.setText("▼" if self.is_expanded else "▶")


class ChatTab(QWidget):
    """Full conversation between human and Small Brain."""
    
    escalation_needed = Signal(str)
    # Emitted after a completed user->Small Brain exchange so an optional bridge
    # (e.g. the Dialogue tab) can continue the thread with a Big Brain follow-up.
    exchange_complete = Signal(str, str)  # user_msg, small_brain_reply
    
    def __init__(self, small_brain, big_brain, parent=None):
        super().__init__(parent)
        self.small_brain = small_brain
        self.big_brain = big_brain
        self.conversation_history = []
        self.show_thinking = True
        self.thinking_boxes = []  # Track thinking boxes for cleanup
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("💬 Chat with Alex Vega (1660 Super)")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #03dac6; padding: 10px;")
        layout.addWidget(header)
        
        # Thinking toggle button
        toggle_layout = QHBoxLayout()
        self.thinking_toggle_btn = QPushButton("🧠 Thinking: ON")
        self.thinking_toggle_btn.setCheckable(True)
        self.thinking_toggle_btn.setChecked(True)
        self.thinking_toggle_btn.setStyleSheet("""
            QPushButton {
                background: #bb86fc;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:checked { background: #bb86fc; }
            QPushButton:!checked { background: #555; color: #aaa; }
        """)
        self.thinking_toggle_btn.clicked.connect(self._toggle_thinking_global)
        toggle_layout.addWidget(self.thinking_toggle_btn)
        toggle_layout.addStretch()
        layout.addLayout(toggle_layout)
        
        # Chat display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background: #0a0a0a;
                color: #e0e0e0;
                border: 1px solid #03dac644;
                border-radius: 8px;
                font-size: 13px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.chat_display)
        
        # Input area
        input_layout = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type your message...")
        self.input.returnPressed.connect(self.on_send)
        self.input.setStyleSheet("""
            QLineEdit {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 10px;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #03dac6; }
        """)
        input_layout.addWidget(self.input)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedWidth(80)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #03dac6;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 10px;
            }
            QPushButton:hover { background: #03dac6cc; }
        """)
        self.send_btn.clicked.connect(self.on_send)
        input_layout.addWidget(self.send_btn)
        
        layout.addLayout(input_layout)
    
    def _toggle_thinking_global(self):
        """Toggle thinking display globally."""
        self.show_thinking = self.thinking_toggle_btn.isChecked()
        self.thinking_toggle_btn.setText(
            "🧠 Thinking: ON" if self.show_thinking else "🧠 Thinking: OFF"
        )
        # Show/hide existing thinking boxes
        for box in self.thinking_boxes:
            box.setVisible(self.show_thinking)
    
    def parse_thinking(self, response: str) -> tuple:
        """
        Parse thinking content from model response.
        Supports multiple thinking formats.
        Returns: (thinking_text, clean_response)
        """
        # Pattern 1: <thinking>...</thinking>
        thinking_pattern = re.compile(r'<thinking>(.*?)</thinking>', re.DOTALL)
        match = thinking_pattern.search(response)
        if match:
            thinking = match.group(1).strip()
            clean = thinking_pattern.sub('', response).strip()
            return thinking, clean
        
        # Pattern 2: Gemma 4 E4B format
        channel_pattern = re.compile(r'<\|channel>(thought.*?)<channel\|>', re.DOTALL | re.IGNORECASE)
        match = channel_pattern.search(response)
        if match:
            thinking = match.group(1).strip()
            clean = channel_pattern.sub('', response).strip()
            return thinking, clean
        
        # Pattern 3: <think>...</think>
        think_pattern = re.compile(r'<think>(.*?)</think>', re.DOTALL)
        match = think_pattern.search(response)
        if match:
            thinking = match.group(1).strip()
            clean = think_pattern.sub('', response).strip()
            return thinking, clean
        
        return None, response
    
    def on_send(self):
        """Handle send button."""
        msg = self.input.text().strip()
        if not msg:
            return
        
        self.append_message("You", msg, "#00b0ff")
        self.input.clear()
        self.send_btn.setEnabled(False)
        self.send_btn.setText("...")
        
        # Run inference in background thread
        self.worker = InferenceWorker(self.small_brain, msg, self.conversation_history)
        self.worker.finished.connect(self._on_small_brain_response)
        self.worker.start()
    
    def _on_small_brain_response(self, response: str):
        """Handle Small Brain response (runs in GUI thread)."""
        # Parse thinking from response
        thinking, clean_response = self.parse_thinking(response)
        
        # Display thinking if present and enabled
        if thinking and self.show_thinking:
            thinking_box = ThinkingBox(thinking, "🧠 Alex Vega Thinking")
            self.thinking_boxes.append(thinking_box)
            # Insert into chat display using HTML wrapper
            self.chat_display.append(
                f'<div style="background:#1a1a2e;border:1px solid #bb86fc44;'
                f'border-radius:6px;padding:8px;margin:4px;">'
                f'<span style="color:#bb86fc;font-weight:bold;">🧠 Thinking</span>'
                f'<div id="thinking_{len(self.thinking_boxes)}"></div></div>'
            )
        
        # Display clean response
        self.append_message("Alex Vega", clean_response, "#03dac6")
        
        # Update history
        self.conversation_history.append({"role": "user", "content": self.worker.user_msg})
        self.conversation_history.append({"role": "assistant", "content": clean_response})
        
        # Check escalation
        if self.small_brain.should_escalate(self.worker.user_msg):
            self.chat_display.append("<i style='color: #ffb300;'>[Consulting Marcus Rivera...]</i>")
            self._start_escalation(self.worker.user_msg)
        
        # Notify any bridge (e.g. Dialogue tab) of the completed exchange so it can
        # continue the thread with a Big Brain follow-up (v2.0.36z).
        try:
            self.exchange_complete.emit(self.worker.user_msg, clean_response)
        except Exception:
            pass
        
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Send")

    def _start_escalation(self, user_msg: str):
        """Run Big Brain escalation + re-summary on a background thread so the GUI
        thread never blocks on the (slow) 27B model (v2.0.36y)."""
        if self.big_brain is None:
            self.chat_display.append(
                "<i style='color: #ff5252;'>[Big Brain unavailable — not configured]</i>")
            return
        self.escalation_worker = EscalationWorker(
            self.small_brain, self.big_brain, user_msg, list(self.conversation_history))
        self.escalation_worker.big_done.connect(self._on_big_brain_answer)
        self.escalation_worker.small_summary.connect(self._on_escalation_summary)
        self.escalation_worker.failed.connect(self._on_escalation_failed)
        self.escalation_worker.start()

    def _on_big_brain_answer(self, bb_clean: str):
        """Show the Marcus Rivera answer once it returns (GUI thread)."""
        self.chat_display.append(
            f"<i style='color: #bb86fc;'>[Marcus Rivera: {bb_clean[:300]}...]</i>")

    def _on_escalation_summary(self, summary: str):
        """Append the Alex Vega re-summary (GUI thread)."""
        self.append_message("Alex Vega", summary, "#03dac6")

    def _on_escalation_failed(self, error: str):
        """Surface an escalation error without freezing (GUI thread)."""
        self.chat_display.append(f"<i style='color: #ff5252;'>[{error}]</i>")
    
    def append_message(self, sender, message, color):
        """Append a message to the chat display."""
        self.chat_display.append(f'<b style="color:{color};">{sender}:</b> {message}<br>')
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class InferenceWorker(QThread):
    """Background worker for running LLM inference without blocking GUI."""
    
    finished = Signal(str)  # Response text
    
    def __init__(self, small_brain, user_msg, history):
        super().__init__()
        self.small_brain = small_brain
        self.user_msg = user_msg
        self.history = history
        self.finished.connect(self.deleteLater)
    
    def run(self):
        """Run inference in background thread."""
        try:
            response = self.small_brain.chat(self.user_msg, self.history)
            self.finished.emit(response)
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")


class EscalationWorker(QThread):
    """Background worker for Big Brain escalation + re-summary.

    The escalation path (Small Brain decides a message needs the Big Brain, then
    asks Small Brain to summarise) involves TWO slow model calls. Previously these
    ran synchronously on the GUI thread inside _on_small_brain_response, freezing
    the whole UI for many seconds while the 27B Big Brain responded. Run them here
    and emit discrete signals so the GUI stays responsive (v2.0.36y fix)."""
    big_done = Signal(str)     # clean big-brain answer
    small_summary = Signal(str)  # final small-brain summary for the user
    failed = Signal(str)       # human-readable error

    def __init__(self, small_brain, big_brain, user_msg, history):
        super().__init__()
        self.small_brain = small_brain
        self.big_brain = big_brain
        self.user_msg = user_msg
        self.history = history
        self.big_done.connect(self.deleteLater)
        self.small_summary.connect(self.deleteLater)
        self.failed.connect(self.deleteLater)

    def run(self):
        try:
            big_response = self.big_brain.analyze(self.user_msg)
            # parse_thinking is a plain static; import here to avoid pulling UI
            # helpers across threads unnecessarily.
            bb_clean = big_response or ""
            bb_clean = bb_clean.strip()
            self.big_done.emit(bb_clean)
            summary = self.small_brain.chat(
                f"Summarize this for the user:\n{bb_clean}", self.history)
            self.small_summary.emit(summary)
        except Exception as e:
            msg = str(e)
            if "No models loaded" in msg or "400" in msg:
                self.failed.emit("Big Brain: No model loaded in the server")
            else:
                self.failed.emit(f"Big Brain unavailable: {msg[:200]}")

