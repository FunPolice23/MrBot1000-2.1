# MrBot1000/gui/tab_builders.py — GUI tab builders (extracted from main.py,
# v2.0.34ah, Section E part B). Mixed into MainWindow as TabBuildersMixin so the
# ~2k lines of tab-construction UI live in their own module while still being
# MainWindow instance methods (so `self.*` access is unchanged).
import os
import queue
import re
import threading
import time
from datetime import datetime

from PySide6.QtCore import QTimer, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileSystemModel,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView

from gui.builders.tab_lifecycle import TabLifecycleMixin


from gui.builders.tab_workers import DataExplorerWorker, LivePortfolioWorker, SocialDiscoveryWorker
from gui.builders.tab_feature_builders import FeatureTabBuildersMixin


class TabBuildersMixin(TabLifecycleMixin, FeatureTabBuildersMixin):
    """Compose tab lifecycle and feature-specific builders."""

    pass
