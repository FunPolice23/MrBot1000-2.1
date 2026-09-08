"""
gui/help_dialog.py — In-app feature help (v2.1).

A searchable "?" / Help dialog listing the program's features with a short
description and a concrete example for each. The data comes from the static
agents.help_catalog module (grounded in the real code); this widget only renders
it, so adding/editing features never requires touching UI code.

Opened from:
- the Dialogue tab's ❓ Help button
- (optionally) any surface that calls show_help_dialog(parent, keyword)
"""

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QTextBrowser, QVBoxLayout,
)


class HelpDialog(QDialog):
    def __init__(self, parent=None, keyword: str = ""):
        super().__init__(parent)
        self.setWindowTitle("❓ Feature Help")
        self.resize(760, 540)
        self._entries = self._load_entries()
        self._setup_ui()
        if keyword:
            self.search_input.setText(keyword)
        self._refresh()

    # ── data ────────────────────────────────────────────────────────────
    def _load_entries(self):
        try:
            from agents.help_catalog import FEATURES
            return list(FEATURES or [])
        except Exception as e:
            return [{
                "feature": "Help catalog unavailable",
                "category": "system",
                "description": f"Could not load agents/help_catalog: {e}",
                "example": "Check that agents/help_catalog.py exists and imports.",
            }]

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Feature Help — click a feature to see its description and example")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffb300;")
        layout.addWidget(title)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("type a keyword (e.g. dialogue, model, vram, persona)...")
        self.search_input.textChanged.connect(self._refresh)
        search_row.addWidget(self.search_input, stretch=1)
        layout.addLayout(search_row)

        body = QHBoxLayout()

        self.feature_list = QListWidget()
        self.feature_list.currentItemChanged.connect(self._on_select)
        body.addWidget(self.feature_list, stretch=3)

        self.detail = QTextBrowser()
        body.addWidget(self.detail, stretch=5)
        layout.addLayout(body)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ── refresh / render ────────────────────────────────────────────────
    def _filtered(self):
        q = self.search_input.text().strip().lower()
        if not q:
            return self._entries
        out = []
        for e in self._entries:
            hay = f"{e.get('feature','')} {e.get('category','')} {e.get('description','')}".lower()
            if q in hay:
                out.append(e)
        return out

    def _refresh(self):
        self.feature_list.clear()
        for e in self._filtered():
            item = QListWidgetItem(f"{e.get('feature','?')}  ·  {e.get('category','')}")
            item.setData(32, e)  # store entry on the item
            self.feature_list.addItem(item)
        if self.feature_list.count():
            self.feature_list.setCurrentRow(0)

    def _on_select(self, cur, _prev):
        if cur is None:
            self.detail.setPlainText("")
            return
        e = cur.data(32) or {}
        html = (
            f"<h3 style='color:#ffb300;'>{e.get('feature','?')}</h3>"
            f"<p><b>Category:</b> {e.get('category','')}</p>"
            f"<p><b>What it does:</b><br>{e.get('description','')}</p>"
            f"<p style='margin-top:10px'><b>Example:</b><br>"
            f"<span style='color:#9e9e9e;'>{e.get('example','')}</span></p>"
        )
        self.detail.setHtml(html)


def show_help_dialog(parent=None, keyword: str = ""):
    """Open a modal help dialog. Safe to call from anywhere (never raises)."""
    try:
        dlg = HelpDialog(parent=parent, keyword=keyword)
        dlg.exec()
    except Exception:
        pass


__all__ = ["HelpDialog", "show_help_dialog"]
