# ═══════════════════════════════════════════════════════════════════════════
# LLAMA SERVER MANAGER — v2.1
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: GUI for managing multiple llama-server instances with GPU isolation.
#          Each instance can be assigned to a specific GPU with RAM overflow.
#
# TO REMOVE THIS FEATURE:
#   1. Delete this file (gui/llama_server_manager.py)
#   2. Remove create_llama_manager_tab() from gui/tab_builders.py
#   3. Remove ("Llama Manager", self.create_llama_manager_tab) from main.py tab_specs
# ═══════════════════════════════════════════════════════════════════════════

import os
import sys
import subprocess
import time
import json
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QTextEdit, QProgressBar, QSpinBox,
    QComboBox, QCheckBox, QGroupBox, QFrame, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QScrollArea, QSizePolicy, QTabWidget,
    QLineEdit, QDialog, QDialogButtonBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QSize
from PySide6.QtGui import QFont, QColor, QTextCursor


# ═══════════════════════════════════════════════════════════════════════════
# GPU INFO WORKER — polls nvidia-smi in background
# ═══════════════════════════════════════════════════════════════════════════
class GPUInfoWorker(QThread):
    """Background worker that polls GPU status."""
    info_updated = Signal(list)  # List of dicts with GPU info
    
    def __init__(self, interval_ms=2000):
        super().__init__()
        self.interval_ms = interval_ms
        self.running = True
    
    def run(self):
        """Poll GPU status every interval."""
        while self.running:
            try:
                gpus = self._get_gpu_info()
                self.info_updated.emit(gpus)
            except Exception:
                pass
            self.msleep(self.interval_ms)
    
    def _get_gpu_info(self):
        """Get GPU info via nvidia-smi."""
        gpus = []
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,"
                 "utilization.gpu,temperature.gpu,power.draw,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 8:
                        gpus.append({
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_used_mb": int(parts[2]),
                            "memory_total_mb": int(parts[3]),
                            "utilization": int(parts[4]),
                            "temperature": int(parts[5]),
                            "power_draw": float(parts[6]) if parts[6] != "[N/A]" else 0,
                            "driver": parts[7]
                        })
        except Exception:
            pass
        return gpus
    
    def stop(self):
        """Stop the polling loop."""
        self.running = False


# ═══════════════════════════════════════════════════════════════════════════
# SERVER INSTANCE WORKER — manages a single llama-server process
# ═══════════════════════════════════════════════════════════════════════════
class ServerInstance:
    """Manages a single llama-server instance."""
    
    def __init__(self, name, port, device, model_path, ctx_size=32768,
                 n_gpu_layers=999, split_mode="none", threads=4,
                 batch_size=2048, ubatch_size=512, flash_attn=True,
                 kv_cache_type="f16", n_predict=-1, temperature=0.8):
        self.name = name
        self.port = port
        self.device = device
        self.model_path = model_path
        self.ctx_size = ctx_size
        self.n_gpu_layers = n_gpu_layers
        self.split_mode = split_mode
        self.threads = threads
        self.batch_size = batch_size
        self.ubatch_size = ubatch_size
        self.flash_attn = flash_attn
        self.kv_cache_type = kv_cache_type
        self.n_predict = n_predict
        self.temperature = temperature
        self.process = None
        self.log_buffer = []
        self.is_running = False
        self.start_time = None
    
    def get_command(self):
        """Build the llama-server command."""
        cmd = ["llama.exe", "serve"]
        cmd.extend(["--host", "127.0.0.1"])
        cmd.extend(["--port", str(self.port)])
        cmd.extend(["--device", str(self.device)])
        cmd.extend(["--ctx-size", str(self.ctx_size)])
        cmd.extend(["--n-gpu-layers", str(self.n_gpu_layers)])
        cmd.extend(["--split-mode", self.split_mode])
        cmd.extend(["--threads", str(self.threads)])
        cmd.extend(["--batch-size", str(self.batch_size)])
        cmd.extend(["--ubatch-size", str(self.ubatch_size)])
        cmd.extend(["--model", self.model_path])
        
        if self.flash_attn:
            cmd.extend(["--flash-attn", "on"])
        
        cmd.extend(["--cache-type-k", self.kv_cache_type])
        cmd.extend(["--cache-type-v", self.kv_cache_type])
        
        if self.n_predict > 0:
            cmd.extend(["--predict", str(self.n_predict)])
        
        return cmd
    
    def start(self):
        """Start the llama-server instance."""
        if self.is_running:
            return False, "Already running"
        
        if not os.path.exists(self.model_path):
            return False, f"Model not found: {self.model_path}"
        
        try:
            cmd = self.get_command()
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True,
                bufsize=1
            )
            self.is_running = True
            self.start_time = datetime.now()
            return True, "Started successfully"
        except Exception as e:
            return False, f"Failed to start: {str(e)}"
    
    def stop(self):
        """Stop the llama-server instance."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None
        self.is_running = False
        self.start_time = None
        return True, "Stopped"
    
    def get_status(self):
        """Get current status."""
        if not self.is_running:
            return "Stopped"
        
        if self.process and self.process.poll() is not None:
            self.is_running = False
            return "Crashed"
        
        return "Running"
    
    def get_uptime(self):
        """Get uptime string."""
        if not self.start_time:
            return "—"
        delta = datetime.now() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def read_output(self):
        """Read available output from the process."""
        if not self.process or not self.process.stdout:
            return []
        
        lines = []
        import select
        if hasattr(select, 'select'):
            while select.select([self.process.stdout], [], [], 0)[0]:
                line = self.process.stdout.readline()
                if line:
                    lines.append(line.strip())
                else:
                    break
        return lines


# ═══════════════════════════════════════════════════════════════════════════
# LLAMA SERVER MANAGER — Main GUI Widget
# ═══════════════════════════════════════════════════════════════════════════
class LlamaServerManager(QWidget):
    """GUI for managing multiple llama-server instances with GPU isolation."""
    
    # Signals
    server_started = Signal(str, int)  # name, port
    server_stopped = Signal(str)  # name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Server instances
        self.servers = {}
        
        # GPU info worker
        self.gpu_worker = GPUInfoWorker(interval_ms=2000)
        self.gpu_worker.info_updated.connect(self._on_gpu_info_updated)
        
        # Build the UI
        self.setup_ui()
        
        # Start GPU monitoring
        self.gpu_worker.start()
        
        # Add default servers
        self._add_default_servers()
    
    def setup_ui(self):
        """Build the manager UI. Auto-starts llama-server instances unless disabled."""
        layout = QVBoxLayout(self)

        # ── Header ──────────────────────────────────────────────────────
        header = QLabel(" Llama Server Manager")
        header.setFont(QFont("Segoe UI", 16, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 8px; margin-bottom: 4px;")
        layout.addWidget(header)

        # ── GPU Status Panel ───────────────────────────────────────────
        gpu_group = QGroupBox("GPU Status")
        gpu_group.setStyleSheet("""
            QGroupBox {
                color: #03dac6;
                font-weight: bold;
                border: 2px solid #03dac6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        gpu_layout = QHBoxLayout(gpu_group)

        self.gpu_widgets = []
        for i in range(2):
            widget = self._create_gpu_widget(i)
            gpu_layout.addWidget(widget)
            self.gpu_widgets.append(widget)

        layout.addWidget(gpu_group)

        # ── Server Instances ───────────────────────────────────────────
        server_group = QGroupBox("Server Instances")
        server_group.setStyleSheet("""
            QGroupBox {
                color: #ffb300;
                font-weight: bold;
                border: 2px solid #ffb300;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        server_layout = QVBoxLayout(server_group)

        # Server table
        self.server_table = QTableWidget()
        self.server_table.setColumnCount(7)
        self.server_table.setHorizontalHeaderLabels([
            "Name", "Port", "GPU", "Model", "Status", "Uptime", "Actions"
        ])
        self.server_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.server_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.server_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.server_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.server_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.server_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.server_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.server_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.server_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.server_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        server_layout.addWidget(self.server_table)

        # ── Action Buttons ─────────────────────────────────────────────
        action_layout = QHBoxLayout()

        self.start_all_btn = QPushButton("Start All Brains")
        self.start_all_btn.setStyleSheet("""
            QPushButton {
                background: #2196f3;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #1976d2; }
            QPushButton:disabled { background: #555; color: #999; }
        """)
        self.start_all_btn.clicked.connect(self._on_start_all)
        action_layout.addWidget(self.start_all_btn)

        self.stop_all_btn = QPushButton("Stop All Brains")
        self.stop_all_btn.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #d32f2f; }
            QPushButton:disabled { background: #555; color: #999; }
        """)
        self.stop_all_btn.clicked.connect(self._on_stop_all)
        action_layout.addWidget(self.stop_all_btn)

        self.auto_start_check = QCheckBox("Auto-start llama-server on program launch")
        self.auto_start_check.setChecked(True)
        self.auto_start_check.setToolTip(
            "When checked, llama-server instances are started automatically when the app launches."
        )
        action_layout.addWidget(self.auto_start_check)

        action_layout.addStretch()
        server_layout.addLayout(action_layout)

        layout.addWidget(server_group)

        # ── Add Server Button ──────────────────────────────────────────
        btn_layout = QHBoxLayout()
        self.add_server_btn = QPushButton("Add Server")
        self.add_server_btn.setStyleSheet("""
            QPushButton {
                background: #4caf50;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
            }
            QPushButton:hover { background: #45a049; }
        """)
        self.add_server_btn.clicked.connect(self._on_add_server)
        btn_layout.addWidget(self.add_server_btn)

        self.start_all_btn2 = QPushButton("Start All")
        self.start_all_btn2.setStyleSheet("""
            QPushButton {
                background: #2196f3;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
            }
            QPushButton:hover { background: #1976d2; }
        """)
        self.start_all_btn2.clicked.connect(self._on_start_all)
        btn_layout.addWidget(self.start_all_btn2)

        self.stop_all_btn2 = QPushButton("Stop All")
        self.stop_all_btn2.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
            }
            QPushButton:hover { background: #da190b; }
        """)
        self.stop_all_btn2.clicked.connect(self._on_stop_all)
        btn_layout.addWidget(self.stop_all_btn2)

        btn_layout.addStretch()
        server_layout.addLayout(btn_layout)

        layout.addWidget(server_group)

        # ── Log Output ──────────────────────────────────────────────────
        log_group = QGroupBox("Server Logs")
        log_group.setStyleSheet("""
            QGroupBox {
                color: #aaaaaa;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        log_layout = QVBoxLayout(log_group)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(200)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 4px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self.log_display)

        clear_log_btn = QPushButton("Clear Logs")
        clear_log_btn.clicked.connect(self._clear_logs)
        bottom_log_layout = QHBoxLayout()
        bottom_log_layout.addWidget(clear_log_btn)
        bottom_log_layout.addStretch()
        log_layout.addLayout(bottom_log_layout)

        layout.addWidget(log_group)

        # ── Server Config Dialog Button ────────────────────────────────
        self.config_btn = QPushButton("Configure Selected Server")
        self.config_btn.setStyleSheet("""
            QPushButton {
                background: #9c27b0;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover { background: #7b1fa2; }
            QPushButton:disabled { background: #555; color: #999; }
        """)
        self.config_btn.clicked.connect(self._on_config)
        layout.addWidget(self.config_btn)

        # ── Status Bar ─────────────────────────────────────────────────
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.status_label)

        # ── Refresh Timer ──────────────────────────────────────────────
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_status)
        self.refresh_timer.start(3000)

        # ── Start GPU monitoring ───────────────────────────────────────
        self.gpu_worker.start()

        # ── Add default servers ────────────────────────────────────────
        self._add_default_servers()

    def _on_config(self):
        """Open config dialog for selected server."""
        selected = self.server_table.selectedItems()
        if not selected:
            self._log("Select a server row first")
            return
        row = selected[0].row()
        keys = list(self.servers.keys())
        if row < len(keys):
            self._on_edit_server(keys[row])

    def _clear_logs(self):
        """Clear the log display."""
        self.log_display.clear()
        self._log("Logs cleared")




    def _create_gpu_widget(self, index):
        """Create a GPU status display widget."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: #1a1a1a;
                border: 2px solid #bb86fc;
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        
        # GPU name
        name_label = QLabel(f"GPU {index}")
        name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        name_label.setStyleSheet("color: #bb86fc;")
        layout.addWidget(name_label)
        
        # Memory bar
        mem_bar = QProgressBar()
        mem_bar.setMaximum(100)
        mem_bar.setValue(0)
        mem_bar.setTextVisible(True)
        mem_bar.setFormat("%v% (%pm)")
        mem_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background: #bb86fc;
                border-radius: 4px;
            }
        """)
        layout.addWidget(mem_bar)
        
        # Details
        details_label = QLabel("—")
        details_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(details_label)
        
        # Store references
        frame.mem_bar = mem_bar
        frame.details_label = details_label
        frame.name_label = name_label
        
        return frame
    
    def _add_default_servers(self):
        """Add default server instances."""
        # Small Brain - 1660 Super
        small_model = self._find_model("Qwen3-4B") or self._find_model("gemma-4-e4b") or ""
        self.servers["small_brain"] = ServerInstance(
            name="Small Brain",
            port=1235,
            device=1,  # 1660 Super
            model_path=small_model,
            ctx_size=32768,
            n_gpu_layers=999,
            split_mode="none",
            threads=4
        )
        
        # Big Brain - 5060 Ti
        big_model = self._find_model("Qwen3.8-27B") or self._find_model("Qwen3-4B") or ""
        self.servers["big_brain"] = ServerInstance(
            name="Big Brain",
            port=1234,
            device=0,  # 5060 Ti
            model_path=big_model,
            ctx_size=32768,
            n_gpu_layers=999,
            split_mode="none",
            threads=8
        )
        
        self._update_server_table()
    
    def _find_model(self, keyword):
        """Find a model file by keyword."""
        model_dirs = [
            Path("D:/LMStudio/models"),
            Path.home() / ".ollama/models",
        ]
        
        for model_dir in model_dirs:
            if model_dir.exists():
                for gguf_file in model_dir.rglob("*.gguf"):
                    if keyword.lower() in gguf_file.name.lower():
                        return str(gguf_file)
        return ""
    
    def _update_server_table(self):
        """Update the server table display."""
        self.server_table.setRowCount(len(self.servers))
        
        for row, (key, server) in enumerate(self.servers.items()):
            # Name
            self.server_table.setItem(row, 0, QTableWidgetItem(server.name))
            
            # Port
            self.server_table.setItem(row, 1, QTableWidgetItem(str(server.port)))
            
            # GPU
            gpu_label = f"GPU {server.device}"
            self.server_table.setItem(row, 2, QTableWidgetItem(gpu_label))
            
            # Model
            model_name = os.path.basename(server.model_path) if server.model_path else "—"
            self.server_table.setItem(row, 3, QTableWidgetItem(model_name))
            
            # Status
            status = server.get_status()
            status_item = QTableWidgetItem(status)
            if status == "Running":
                status_item.setForeground(QColor("#4caf50"))
            elif status == "Crashed":
                status_item.setForeground(QColor("#ff5252"))
            else:
                status_item.setForeground(QColor("#ffb300"))
            self.server_table.setItem(row, 4, status_item)
            
            # Uptime
            self.server_table.setItem(row, 5, QTableWidgetItem(server.get_uptime()))
            
            # Actions
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            
            start_btn = QPushButton("▶")
            start_btn.setFixedSize(30, 25)
            start_btn.setStyleSheet("background: #4caf50; color: white; font-weight: bold; border: none; border-radius: 3px;")
            start_btn.clicked.connect(lambda checked, k=key: self._on_start_server(k))
            actions_layout.addWidget(start_btn)
            
            stop_btn = QPushButton("⏹")
            stop_btn.setFixedSize(30, 25)
            stop_btn.setStyleSheet("background: #f44336; color: white; font-weight: bold; border: none; border-radius: 3px;")
            stop_btn.clicked.connect(lambda checked, k=key: self._on_stop_server(k))
            actions_layout.addWidget(stop_btn)
            
            edit_btn = QPushButton("⚙")
            edit_btn.setFixedSize(30, 25)
            edit_btn.setStyleSheet("background: #2196f3; color: white; font-weight: bold; border: none; border-radius: 3px;")
            edit_btn.clicked.connect(lambda checked, k=key: self._on_edit_server(k))
            actions_layout.addWidget(edit_btn)
            
            actions_layout.addStretch()
            self.server_table.setCellWidget(row, 6, actions_widget)
    
    def _on_gpu_info_updated(self, gpus):
        """Handle GPU info update."""
        for i, gpu in enumerate(gpus):
            if i < len(self.gpu_widgets):
                widget = self.gpu_widgets[i]
                mem_pct = int((gpu["memory_used_mb"] / gpu["memory_total_mb"]) * 100)
                widget.mem_bar.setValue(mem_pct)
                widget.mem_bar.setFormat(
                    f"{mem_pct}% ({gpu['memory_used_mb']/1024:.1f}/{gpu['memory_total_mb']/1024:.1f} GB)"
                )
                widget.details_label.setText(
                    f"{gpu['name']}\n"
                    f"🌡 {gpu['temperature']}°C | ⚡ {gpu['power_draw']:.0f}W\n"
                    f"📊 {gpu['utilization']}% util"
                )
                widget.name_label.setText(f"GPU {gpu['index']}: {gpu['name']}")
    
    def _on_add_server(self):
        """Add a new server instance."""
        dialog = ServerConfigDialog(self)
        if dialog.exec() == QDialog.Accepted:
            config = dialog.get_config()
            key = f"server_{len(self.servers)}"
            self.servers[key] = ServerInstance(**config)
            self._update_server_table()
            self._log(f"Added server: {config['name']} on port {config['port']}")
    
    def _on_start_server(self, key):
        """Start a specific server."""
        if key in self.servers:
            server = self.servers[key]
            success, msg = server.start()
            if success:
                self._log(f"✅ {server.name} started on port {server.port} (GPU {server.device})")
                self.server_started.emit(server.name, server.port)
            else:
                self._log(f"❌ {server.name} failed: {msg}")
            self._update_server_table()
    
    def _on_stop_server(self, key):
        """Stop a specific server."""
        if key in self.servers:
            server = self.servers[key]
            success, msg = server.stop()
            self._log(f"⏹ {server.name} stopped")
            self.server_stopped.emit(server.name)
            self._update_server_table()
    
    def _on_edit_server(self, key):
        """Edit a server instance."""
        if key in self.servers:
            server = self.servers[key]
            dialog = ServerConfigDialog(self, server)
            if dialog.exec() == QDialog.Accepted:
                config = dialog.get_config()
                # Stop if running
                was_running = server.is_running
                if was_running:
                    server.stop()
                # Update config
                server.name = config["name"]
                server.port = config["port"]
                server.device = config["device"]
                server.model_path = config["model_path"]
                server.ctx_size = config["ctx_size"]
                server.n_gpu_layers = config["n_gpu_layers"]
                server.split_mode = config["split_mode"]
                server.threads = config["threads"]
                # Restart if was running
                if was_running:
                    server.start()
                self._update_server_table()
    
    def _on_start_all(self):
        """Start all servers."""
        for key in self.servers:
            self._on_start_server(key)
    
    def _on_stop_all(self):
        """Stop all servers."""
        for key in self.servers:
            self._on_stop_server(key)
    
    def _refresh_status(self):
        """Refresh server status display."""
        for row, (key, server) in enumerate(self.servers.items()):
            status = server.get_status()
            status_item = self.server_table.item(row, 4)
            if status_item:
                status_item.setText(status)
                if status == "Running":
                    status_item.setForeground(QColor("#4caf50"))
                elif status == "Crashed":
                    status_item.setForeground(QColor("#ff5252"))
                else:
                    status_item.setForeground(QColor("#ffb300"))
            
            uptime_item = self.server_table.item(row, 5)
            if uptime_item:
                uptime_item.setText(server.get_uptime())
    
    def _log(self, message):
        """Add a message to the log display."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{ts}] {message}")
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def cleanup(self):
        """Stop background threads and servers."""
        self.refresh_timer.stop()
        self.gpu_worker.stop()
        self.gpu_worker.wait(1000)
        for server in self.servers.values():
            if server.is_running:
                server.stop()


# ═══════════════════════════════════════════════════════════════════════════
# SERVER CONFIG DIALOG — for adding/editing server instances
# ═══════════════════════════════════════════════════════════════════════════
class ServerConfigDialog(QDialog):
    """Dialog for configuring a server instance."""
    
    def __init__(self, parent=None, server=None):
        super().__init__(parent)
        self.server = server
        self.setWindowTitle("Server Configuration")
        self.setMinimumWidth(500)
        self.setup_ui()
        
        if server:
            self.load_config(server)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        # Name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Small Brain")
        form.addRow("Name:", self.name_edit)
        
        # Port
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(1235)
        form.addRow("Port:", self.port_spin)
        
        # GPU Device
        self.device_combo = QComboBox()
        self.device_combo.addItems(["0 (5060 Ti)", "1 (1660 Super)"])
        form.addRow("GPU Device:", self.device_combo)
        
        # Model Path
        model_layout = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Path to .gguf file")
        model_layout.addWidget(self.model_edit)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_model)
        model_layout.addWidget(browse_btn)
        form.addRow("Model:", model_layout)
        
        # Context Size
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(1024, 131072)
        self.ctx_spin.setValue(32768)
        self.ctx_spin.setSingleStep(1024)
        form.addRow("Context Size:", self.ctx_spin)
        
        # GPU Layers
        self.gpu_layers_spin = QSpinBox()
        self.gpu_layers_spin.setRange(0, 999)
        self.gpu_layers_spin.setValue(999)
        form.addRow("GPU Layers:", self.gpu_layers_spin)
        
        # Split Mode
        self.split_combo = QComboBox()
        self.split_combo.addItems(["none", "layer", "row", "tensor"])
        form.addRow("Split Mode:", self.split_combo)
        
        # Threads
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 32)
        self.threads_spin.setValue(4)
        form.addRow("CPU Threads:", self.threads_spin)
        
        # Flash Attention
        self.flash_check = QCheckBox("Enable")
        self.flash_check.setChecked(True)
        form.addRow("Flash Attention:", self.flash_check)
        
        # KV Cache Type
        self.kv_cache_combo = QComboBox()
        self.kv_cache_combo.addItems(["f16", "f32", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl"])
        self.kv_cache_combo.setCurrentText("f16")
        form.addRow("KV Cache Type:", self.kv_cache_combo)
        
        layout.addLayout(form)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _browse_model(self):
        """Browse for a model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Model", "",
            "GGUF Files (*.gguf);;All Files (*)"
        )
        if file_path:
            self.model_edit.setText(file_path)
    
    def load_config(self, server):
        """Load existing server config."""
        self.name_edit.setText(server.name)
        self.port_spin.setValue(server.port)
        self.device_combo.setCurrentIndex(server.device)
        self.model_edit.setText(server.model_path)
        self.ctx_spin.setValue(server.ctx_size)
        self.gpu_layers_spin.setValue(server.n_gpu_layers)
        self.split_combo.setCurrentText(server.split_mode)
        self.threads_spin.setValue(server.threads)
        self.flash_check.setChecked(server.flash_attn)
        self.kv_cache_combo.setCurrentText(server.kv_cache_type)
    
    def get_config(self):
        """Get the configuration dict."""
        return {
            "name": self.name_edit.text(),
            "port": self.port_spin.value(),
            "device": self.device_combo.currentIndex(),
            "model_path": self.model_edit.text(),
            "ctx_size": self.ctx_spin.value(),
            "n_gpu_layers": self.gpu_layers_spin.value(),
            "split_mode": self.split_combo.currentText(),
            "threads": self.threads_spin.value(),
            "flash_attn": self.flash_check.isChecked(),
            "kv_cache_type": self.kv_cache_combo.currentText(),
        }

