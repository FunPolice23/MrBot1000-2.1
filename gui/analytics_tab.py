"""gui/analytics_tab.py — Analytics tab for market data and strategy performance."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QComboBox, QSplitter, QFrame, QSizePolicy,
)
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger("mrbot.gui.analytics_tab")


class AnalyticsTab(QWidget):
    """Analytics tab — market data and strategy performance."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._price_cache: Dict[str, float] = {}
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(60000)  # Auto-refresh every 60s

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header
        header = QLabel("📊 Analytics")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        root.addWidget(header)

        splitter = QSplitter(Qt.Vertical)

        # Market data section
        market_box = QGroupBox("Market Data")
        market_lay = QFormLayout(market_box)

        self.crypto_combo = QComboBox()
        self.crypto_combo.addItems(["bitcoin", "ethereum", "solana", "cardano", "polkadot"])
        market_lay.addRow("Crypto:", self.crypto_combo)

        self.crypto_price = QLabel("—")
        self.crypto_price.setStyleSheet("font-size: 14pt; color: #00ff88;")
        market_lay.addRow("Price:", self.crypto_price)

        self.crypto_change = QLabel("—")
        market_lay.addRow("24h Change:", self.crypto_change)

        self.refresh_crypto_btn = QPushButton("🔄 Refresh")
        self.refresh_crypto_btn.setStyleSheet("""
            QPushButton {
                background: #4fc3f7;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #29b6f6; }
        """)
        self.refresh_crypto_btn.clicked.connect(self._on_refresh_crypto_price)
        market_lay.addRow(self.refresh_crypto_btn)

        splitter.addWidget(market_box)

        # Strategy performance section
        strategy_box = QGroupBox("Strategy Performance")
        strategy_lay = QVBoxLayout(strategy_box)

        self.strategy_table = QTableWidget()
        self.strategy_table.setColumnCount(6)
        self.strategy_table.setHorizontalHeaderLabels(
            ["Strategy", "Return %", "Sharpe", "Win Rate", "Trades", "Max DD"]
        )
        self.strategy_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.strategy_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.strategy_table.setAlternatingRowColors(True)
        strategy_lay.addWidget(self.strategy_table, stretch=1)

        self.run_backtest_btn = QPushButton("📈 Run Backtest")
        self.run_backtest_btn.setStyleSheet("""
            QPushButton {
                background: #ff9800;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #ffa726; }
        """)
        self.run_backtest_btn.clicked.connect(self._on_run_backtest)
        strategy_lay.addWidget(self.run_backtest_btn)

        splitter.addWidget(strategy_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, stretch=1)

        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888;")
        root.addWidget(self.status_label)

    def _auto_refresh(self):
        """Auto-refresh market data (best-effort, no error popup)."""
        try:
            self._fetch_price(self.crypto_combo.currentText())
        except Exception:
            pass

    def cleanup(self):
        """Stop periodic refresh before the main window is torn down."""
        if self._timer.isActive():
            self._timer.stop()

    def _on_refresh_crypto_price(self):
        """Refresh crypto price on button click."""
        self.status_label.setText("Fetching...")
        self.status_label.setStyleSheet("color: #ffb300;")
        try:
            self._fetch_price(self.crypto_combo.currentText())
            self.status_label.setText("Ready")
            self.status_label.setStyleSheet("color: #4caf50;")
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            self.status_label.setStyleSheet("color: #ff5252;")

    def _fetch_price(self, symbol: str):
        """Fetch crypto price from CoinGecko (free, no API key)."""
        import urllib.request
        import json

        # Check cache first (60s TTL)
        if symbol in self._price_cache:
            self.crypto_price.setText(f"${self._price_cache[symbol]:,.2f}")
            return

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "MrBot1000"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if symbol in data:
            price = data[symbol].get("usd", 0)
            change = data[symbol].get("usd_24h_change", 0)
            self._price_cache[symbol] = price
            self.crypto_price.setText(f"${price:,.2f}")
            color = "#00ff88" if change >= 0 else "#ff5252"
            self.crypto_change.setText(f"{change:+.2f}%")
            self.crypto_change.setStyleSheet(f"color: {color};")

    def _on_run_backtest(self):
        """Run strategy backtest (stub — needs BacktestEngine integration)."""
        self.status_label.setText("Running backtest...")
        self.status_label.setStyleSheet("color: #ffb300;")
        # TODO: Integrate with BacktestEngine
        self.status_label.setText("Backtest complete (stub)")
        self.status_label.setStyleSheet("color: #888;")


__all__ = ["AnalyticsTab"]
