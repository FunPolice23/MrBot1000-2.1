"""gui/provider_config_widget.py — Dynamic provider configuration widget.

Allows switching cloud/local providers at runtime without restart.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from PySide6.QtCore import Signal, QThread, Qt, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QComboBox, QPushButton, QFrame, QScrollArea, QTabWidget,
    QSlider, QSpinBox, QLineEdit, QCheckBox, QProgressBar, QSizePolicy,
)
from agents.personas import DRIVER, NAVIGATOR


class ProviderConfigWidget(QWidget):
    """Dynamic provider configuration widget with hot-reload support."""
    
    provider_changed = Signal(str, str)  # provider_name, action
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(3000)

    def pause_background(self):
        """Pause provider polling while the Settings tab is hidden."""
        self._refresh_timer.stop()

    def resume_background(self):
        """Resume provider polling and refresh once after the tab is shown."""
        if not self._refresh_timer.isActive():
            self.refresh()
            self._refresh_timer.start(3000)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header = QLabel("🔧 Provider Configuration")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 6px;")
        layout.addWidget(header)
        
        # Provider type tabs - make them wider and taller
        self.type_tabs = QTabWidget()
        self.type_tabs.setMinimumHeight(350)
        self.type_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Cloud tab with scroll
        cloud_scroll = QScrollArea()
        cloud_scroll.setWidgetResizable(True)
        cloud_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cloud_widget = QWidget(cloud_scroll)
        self.cloud_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.cloud_layout = QVBoxLayout(self.cloud_widget)
        self.cloud_layout.setSpacing(10)
        self.cloud_layout.setContentsMargins(10, 10, 10, 10)
        self._build_provider_list("cloud")
        cloud_scroll.setWidget(self.cloud_widget)
        self.type_tabs.addTab(cloud_scroll, "☁️ Cloud Providers")
        
        # Local tab with scroll
        local_scroll = QScrollArea()
        local_scroll.setWidgetResizable(True)
        local_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.local_widget = QWidget(local_scroll)
        self.local_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.local_layout = QVBoxLayout(self.local_widget)
        self.local_layout.setSpacing(10)
        self.local_layout.setContentsMargins(10, 10, 10, 10)
        self._build_provider_list("local")
        local_scroll.setWidget(self.local_widget)
        self.type_tabs.addTab(local_scroll, "💻 Local Providers")
        
        layout.addWidget(self.type_tabs)
        
        # Quick Settings
        settings_group = QGroupBox("Quick Settings")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setSpacing(12)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        
        # Active Cloud
        settings_layout.addWidget(QLabel("Active Cloud:"), 0, 0)
        self.active_cloud = QComboBox()
        self.active_cloud.setMinimumWidth(300)
        self.active_cloud.setMinimumHeight(30)
        self.active_cloud.addItems(["Auto", "OpenAI", "Anthropic", "OpenRouter", "Groq", "DeepSeek", "Mistral", "Together"])
        self.active_cloud.setCurrentText(os.getenv("ACTIVE_CLOUD_PROVIDER", "Auto"))
        self.active_cloud.currentTextChanged.connect(self._on_cloud_changed)
        settings_layout.addWidget(self.active_cloud, 0, 1)
        
        # Active Local
        settings_layout.addWidget(QLabel("Active Local:"), 1, 0)
        self.active_local = QComboBox()
        self.active_local.setMinimumWidth(300)
        self.active_local.setMinimumHeight(30)
        self.active_local.addItems(["Auto", "llama.cpp", "Ollama", "vLLM", "LM Studio", "KoboldCpp"])
        self.active_local.setCurrentText(os.getenv("ACTIVE_LOCAL_PROVIDER", "Auto"))
        self.active_local.currentTextChanged.connect(self._on_local_changed)
        settings_layout.addWidget(self.active_local, 1, 1)
        
        # Fallback
        settings_layout.addWidget(QLabel("Fallback:"), 2, 0)
        self.fallback_check = QCheckBox("Auto-failover to cloud when local fails")
        self.fallback_check.setChecked(True)
        settings_layout.addWidget(self.fallback_check, 2, 1)
        settings_layout.addWidget(QLabel("Big Brain name:"), 3, 0)
        self.big_brain_name = QLineEdit(os.getenv("BIG_BRAIN_NAME", "").strip())
        self.big_brain_name.setPlaceholderText(DRIVER.name)
        self.big_brain_name.setToolTip("Optional custom name; blank uses Edward Hurst")
        self.big_brain_name.editingFinished.connect(
            lambda: self._persist_brain_name("BIG_BRAIN_NAME", self.big_brain_name))
        settings_layout.addWidget(self.big_brain_name, 3, 1)

        settings_layout.addWidget(QLabel("Small Brain name:"), 4, 0)
        self.small_brain_name = QLineEdit(os.getenv("SMALL_BRAIN_NAME", "").strip())
        self.small_brain_name.setPlaceholderText(NAVIGATOR.name)
        self.small_brain_name.setToolTip("Optional custom name; blank uses Jacob Stanley")
        self.small_brain_name.editingFinished.connect(
            lambda: self._persist_brain_name("SMALL_BRAIN_NAME", self.small_brain_name))
        settings_layout.addWidget(self.small_brain_name, 4, 1)
        
        layout.addWidget(settings_group)
        
        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def _on_cloud_changed(self, text):
        """Handle cloud provider change."""
        self._persist_quick_selection("cloud", text)
        self.status_label.setText(f"Active cloud: {text}")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.provider_changed.emit("cloud", text)
    
    def _on_local_changed(self, text):
        """Handle local provider change."""
        self._persist_quick_selection("local", text)
        self.status_label.setText(f"Active local: {text}")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.provider_changed.emit("local", text)

    def _persist_quick_selection(self, kind: str, text: str):
        """Persist the quick route and refresh the process environment."""
        key = "ACTIVE_LOCAL_PROVIDER" if kind == "local" else "ACTIVE_CLOUD_PROVIDER"
        values = {key: text}
        if kind == "local":
            provider_map = {
                "llama.cpp": "llamacpp",
                "Ollama": "ollama",
                "vLLM": "vllm",
                "LM Studio": "lmstudio",
                "KoboldCpp": "koboldcpp",
            }
            selected = provider_map.get(text)
            if selected:
                values.update({
                    "BIG_BRAIN_PROVIDER": selected,
                    "SMALL_BRAIN_PROVIDER": selected,
                    "BIG_BRAIN_ENABLED": "true",
                    "SMALL_BRAIN_ENABLED": "true",
                })
                # The generic registry uses these switches for local OpenAI-
                # compatible providers; llama.cpp is registered by its role env.
                for name, prefix in (("ollama", "OLLAMA"), ("vllm", "VLLM"),
                                     ("lmstudio", "LM_STUDIO"), ("koboldcpp", "KOBOLDCPP")):
                    values[f"DISABLE_{prefix}"] = str(selected != name).lower()
                # Selecting a local provider enables that provider's route.
                # The llama.cpp control panel separately skips llama-server
                # startup when the selected provider is external.
                values["BIG_BRAIN_ENABLED"] = "true"
                values["SMALL_BRAIN_ENABLED"] = "true"
        os.environ.update(values)
        try:
            from main import set_env_values
            set_env_values(values)
        except Exception:
            pass
        try:
            from agents.base_worker import _active_worker
            if _active_worker is not None:
                _active_worker.invalidate_provider_registry()
        except Exception:
            pass

    def _persist_brain_name(self, key: str, widget: QLineEdit):
        """Persist a custom role name without altering the stable brain key."""
        value = widget.text().strip()
        if not value:
            widget.clear()
            os.environ.pop(key, None)
            values = {key: ""}
        else:
            os.environ[key] = value
            values = {key: value}
        try:
            from main import set_env_values
            set_env_values(values)
        except Exception:
            pass
        self.status_label.setText(f"Saved {key.replace('_', ' ').title()}")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.provider_changed.emit("persona", key)
    
    def _build_provider_list(self, provider_type: str):
        """Build provider list for cloud or local."""
        from agents.provider_manager import ProviderManager, ProviderStatus
        
        pm = ProviderManager.instance()
        providers = pm.get_providers()
        
        layout = self.cloud_layout if provider_type == "cloud" else self.local_layout
        
        # Clear existing widgets
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        for name, provider in providers.items():
            if provider_type == "cloud" and not provider.is_cloud:
                continue
            if provider_type == "local" and not provider.is_local:
                continue
            
            frame = QFrame()
            frame.setMinimumHeight(60)
            frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            frame.setStyleSheet("""
                QFrame {
                    background: #1a1a1a;
                    border: 1px solid #333;
                    border-radius: 6px;
                    padding: 8px;
                }
            """)
            row = QHBoxLayout(frame)
            row.setSpacing(8)
            row.setContentsMargins(8, 6, 8, 6)
            
            # Status indicator
            status_color = {
                ProviderStatus.RUNNING.value: "#4caf50",
                ProviderStatus.STOPPED.value: "#ff5252",
                ProviderStatus.UNAVAILABLE.value: "#ff9800",
                ProviderStatus.ERROR.value: "#f44336",
            }.get(provider.status, "#888")
            
            status = QLabel("●")
            status.setStyleSheet(f"color: {status_color}; font-size: 18px;")
            row.addWidget(status)
            
            # Provider name - wider with explicit color for readability
            name_label = QLabel(provider.name)
            name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
            name_label.setMinimumWidth(90)
            name_label.setMaximumWidth(180)
            name_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            name_label.setToolTip(provider.name)
            name_label.setStyleSheet("color: #ffffff;")  # Explicit white for contrast
            row.addWidget(name_label)
            
            # Model dropdown - wider with placeholder when empty
            model_combo = QComboBox()
            model_combo.setMinimumWidth(120)
            model_combo.setEditable(True)
            model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            model_combo.setMinimumContentsLength(12)
            model_combo.setToolTip("Select the active model")
            models = list(provider.models)
            if name == "llamacpp":
                models.extend([
                    os.getenv("BIG_BRAIN_MODEL", "").strip(),
                    os.getenv("SMALL_BRAIN_MODEL", "").strip(),
                ])
                models = list(dict.fromkeys(model for model in models if model))
            if models:
                for model in models:
                    try:
                        from provider_models import _price_for
                        _, output_price = _price_for(model)
                        suffix = f"  (${output_price:g}/1M out)" if output_price is not None else ""
                    except Exception:
                        suffix = ""
                    model_combo.addItem(f"{model}{suffix}", model)
                if provider.selected_model:
                    model_combo.setCurrentText(provider.selected_model)
            else:
                # Keep the field editable when the provider is stopped or its
                # model endpoint is unavailable. The selected name can still
                # be persisted and used when the provider starts.
                prefix = self._provider_prefix(name)
                configured = (
                    provider.selected_model
                    or (os.getenv(f"{prefix}_MODEL", "") if prefix else "")
                    or ""
                ).strip()
                if configured:
                    model_combo.addItem(configured, configured)
                    model_combo.setCurrentText(configured)
                else:
                    model_combo.setPlaceholderText("Enter model name")
                model_combo.setEnabled(True)
            model_combo.currentTextChanged.connect(lambda text, n=name, combo=model_combo: self._on_model_changed(n, combo.currentData() or text))
            row.addWidget(model_combo)

            refresh_btn = QPushButton("Refresh")
            refresh_btn.setMinimumHeight(35)
            refresh_btn.setToolTip("Fetch models currently available from this provider")
            refresh_btn.clicked.connect(
                lambda checked=False, n=name, combo=model_combo: self._refresh_provider_models(n, combo))
            row.addWidget(refresh_btn)
            
            # GPU (for local)
            if provider.is_local:
                gpu_combo = QComboBox()
                gpu_combo.setMinimumWidth(110)
                gpu_combo.setMinimumHeight(35)
                gpu_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                gpu_combo.addItem("Auto", -1)
                gpus = pm.get_gpus()
                for gpu in gpus:
                    gpu_combo.addItem(f"GPU {gpu.index}: {gpu.name}", gpu.index)
                gpu_combo.setCurrentIndex(provider.gpu_index + 1)
                gpu_combo.currentIndexChanged.connect(lambda idx, n=name: self._on_gpu_changed(n, idx - 1))
                row.addWidget(gpu_combo)
            
            # Action button
            btn = QPushButton("Enable" if provider.status != ProviderStatus.RUNNING.value else "Disable")
            btn.setMinimumWidth(82)
            btn.setMinimumHeight(35)
            btn.setStyleSheet("""
                QPushButton {
                    background: #4caf50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover { background: #45a049; }
            """)
            # Make sure the button is actually clickable
            btn.setAutoFillBackground(True)
            btn.clicked.connect(lambda checked, n=name: self._on_action_clicked(n))
            row.addWidget(btn)
            
            layout.addWidget(frame)

            # Keep credentials, endpoint, and role selection with the provider
            # card so the separate Settings provider list is not required.
            prefix = self._provider_prefix(name)
            if prefix:
                details = QFrame()
                details.setStyleSheet("QFrame { border: 0; padding: 0; }")
                details_row = QHBoxLayout(details)
                details_row.setContentsMargins(110, 0, 8, 6)
                details_row.addWidget(QLabel("API key:"))
                key_edit = QLineEdit(os.getenv(f"{prefix}_API_KEY", ""))
                key_edit.setEchoMode(QLineEdit.Password)
                key_edit.setPlaceholderText("optional for local providers")
                key_edit.textChanged.connect(lambda value, p=prefix: self._persist_provider_field(p, "API_KEY", value))
                details_row.addWidget(key_edit, 1)
                if prefix == "LLAMACPP":
                    details_row.addWidget(QLabel("Big Brain URL:"))
                    big_url = QLineEdit(os.getenv(
                        "BIG_BRAIN_URL", "http://127.0.0.1:1234/v1"))
                    big_url.setPlaceholderText("http://127.0.0.1:1234/v1")
                    big_url.textChanged.connect(
                        lambda value: self._persist_provider_field_value(
                            "BIG_BRAIN_URL", value))
                    details_row.addWidget(big_url, 1)
                    details_row.addWidget(QLabel("Small Brain URL:"))
                    small_url = QLineEdit(os.getenv(
                        "SMALL_BRAIN_URL", "http://127.0.0.1:1235/v1"))
                    small_url.setPlaceholderText("http://127.0.0.1:1235/v1")
                    small_url.textChanged.connect(
                        lambda value: self._persist_provider_field_value(
                            "SMALL_BRAIN_URL", value))
                    details_row.addWidget(small_url, 1)
                else:
                    details_row.addWidget(QLabel("Base URL:"))
                    base_edit = QLineEdit(os.getenv(f"{prefix}_BASE_URL", provider.base_url))
                    base_edit.setPlaceholderText("provider endpoint")
                    base_edit.textChanged.connect(lambda value, p=prefix: self._persist_provider_field(p, "BASE_URL", value))
                    details_row.addWidget(base_edit, 1)
                role_combo = QComboBox()
                role_combo.addItems(["Both", "Main only", "Chat only", "Disabled"])
                role_combo.setCurrentText(self._role_from_env(prefix))
                role_combo.currentTextChanged.connect(lambda value, p=prefix: self._persist_provider_role(p, value))
                details_row.addWidget(role_combo)
                layout.addWidget(details)
                if provider.is_local and name != "llamacpp":
                    role_models = QHBoxLayout()
                    role_models.setContentsMargins(110, 0, 8, 6)
                    role_models.addWidget(QLabel("Main model:"))
                    main_combo = self._role_model_combo(
                        provider, "BIG_BRAIN_MODEL", provider.models)
                    main_combo.currentTextChanged.connect(
                        lambda value, n=name: self._on_role_model_changed(
                            n, "BIG_BRAIN_MODEL", value))
                    role_models.addWidget(main_combo, 1)
                    role_models.addWidget(QLabel("Chat model:"))
                    chat_combo = self._role_model_combo(
                        provider, "SMALL_BRAIN_MODEL", provider.models)
                    chat_combo.currentTextChanged.connect(
                        lambda value, n=name: self._on_role_model_changed(
                            n, "SMALL_BRAIN_MODEL", value))
                    role_models.addWidget(chat_combo, 1)
                    layout.addLayout(role_models)
    
    def _on_model_changed(self, provider_name: str, model: str):
        """Handle model change."""
        from agents.provider_manager import ProviderManager
        pm = ProviderManager.instance()
        provider = pm.get_provider(provider_name)
        if provider and model != "(no models detected)":
            provider.selected_model = model
            prefix = self._provider_prefix(provider_name)
            role = self._role_from_env(prefix) if prefix else "Both"
            values = {}
            if role in ("Both", "Main only"):
                values["BIG_BRAIN_MODEL"] = model
            if role in ("Both", "Chat only"):
                values["SMALL_BRAIN_MODEL"] = model
            if prefix:
                values[f"{prefix}_MODEL"] = model
                # Ollama has separate role keys in the legacy worker path.
                # Keep both roles aligned when the shared provider-list model
                # selector is used.
                if prefix == "OLLAMA":
                    values["OLLAMA_MAIN_MODEL"] = model
                    values["OLLAMA_CHAT_MODEL"] = model
            os.environ.update(values)
            try:
                from main import set_env_values
                set_env_values(values)
            except Exception:
                pass
            try:
                from agents.base_worker import _active_worker
                if _active_worker is not None:
                    _active_worker.invalidate_provider_registry()
            except Exception:
                pass
            self.status_label.setText(f"Updated {provider_name} model to {model}")
            self.status_label.setStyleSheet("color: #4caf50;")
            if provider.is_local:
                self._load_selected_local_model(provider_name, provider, model, role)
            self.provider_changed.emit(provider_name, f"model:{model}")

    @staticmethod
    def _role_model_combo(provider, env_key: str, models):
        combo = QComboBox()
        combo.setEditable(True)
        combo.setMinimumWidth(160)
        values = list(dict.fromkeys(str(item) for item in (models or []) if item))
        configured = os.getenv(env_key, "").strip() or provider.selected_model
        if configured and configured not in values:
            values.insert(0, configured)
        combo.addItems(values)
        if configured:
            combo.setCurrentText(configured)
        return combo

    def _on_role_model_changed(self, provider_name: str, env_key: str, model: str):
        """Persist and load one brain role without changing the other role."""
        model = (model or "").strip()
        if not model or model == "(no models detected)":
            return
        from agents.provider_manager import ProviderManager
        provider = ProviderManager.instance().get_provider(provider_name)
        if not provider:
            return
        values = {env_key: model}
        os.environ.update(values)
        try:
            from main import set_env_values
            set_env_values(values)
        except Exception:
            pass
        try:
            from agents.base_worker import _active_worker
            if _active_worker is not None:
                _active_worker.invalidate_provider_registry()
        except Exception:
            pass
        role = env_key == "SMALL_BRAIN_MODEL"
        if provider.is_local:
            self._load_selected_local_model(
                provider_name, provider, model,
                "Chat only" if role else "Main only")
        self.status_label.setText(
            f"Updated {'Chat' if role else 'Main'} model for {provider_name} to {model}")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.provider_changed.emit(provider_name, f"model:{model}")

    @staticmethod
    def _load_selected_local_model(provider_name, provider, model, role):
        """Load a selected model through providers that expose lifecycle APIs."""
        from agents.provider_manager import ProviderManager
        runtime_name = ProviderManager.normalize_provider_name(provider_name)
        if runtime_name not in ("lmstudio", "ollama") or role == "Disabled":
            return
        try:
            from gui.dual_brain_control import ProviderStatusChecker
            endpoint = provider.base_url
            threading.Thread(
                target=ProviderConfigWidget._load_local_model_worker,
                args=(ProviderStatusChecker, runtime_name, endpoint, model),
                daemon=True,
            ).start()
        except Exception:
            pass

    @staticmethod
    def _load_local_model_worker(checker, provider, endpoint, model):
        checker.load_provider_model(provider, endpoint, model)
    
    def _on_gpu_changed(self, provider_name: str, gpu_index: int):
        """Handle GPU change."""
        from agents.provider_manager import ProviderManager
        pm = ProviderManager.instance()
        pm.assign_provider_to_gpu(provider_name, gpu_index)
        self.status_label.setText(f"Assigned {provider_name} to GPU {gpu_index}")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.provider_changed.emit(provider_name, f"gpu:{gpu_index}")

    @staticmethod
    def _provider_prefix(provider_name: str) -> str:
        return {
            "ollama": "OLLAMA", "openai": "OPENAI", "anthropic": "ANTHROPIC", "openrouter": "OPENROUTER",
            "groq": "GROQ", "deepseek": "DEEPSEEK", "mistral": "MISTRAL",
            "together": "TOGETHER", "vllm": "VLLM", "lm_studio": "LM_STUDIO",
            "koboldcpp": "KOBOLDCPP", "llamacpp": "LLAMACPP",
        }.get(provider_name, "")

    @staticmethod
    def _role_from_env(prefix: str) -> str:
        if os.getenv(f"DISABLE_{prefix}", "false").lower() == "true":
            return "Disabled"
        main = os.getenv(f"{prefix}_MAIN_ENABLED", "true").lower() != "false"
        chat = os.getenv(f"{prefix}_CHAT_ENABLED", "true").lower() != "false"
        return "Both" if main and chat else "Main only" if main else "Chat only" if chat else "Disabled"

    def _persist_provider_field(self, prefix: str, field: str, value: str):
        self._persist_provider_field_value(f"{prefix}_{field}", value)

    def _persist_provider_field_value(self, key: str, value: str):
        os.environ[key] = value
        try:
            from main import set_env_values
            set_env_values({key: value})
        except Exception:
            pass

    def _persist_provider_role(self, prefix: str, role: str):
        values = {
            f"DISABLE_{prefix}": str(role == "Disabled").lower(),
            f"{prefix}_MAIN_ENABLED": str(role in ("Both", "Main only")).lower(),
            f"{prefix}_CHAT_ENABLED": str(role in ("Both", "Chat only")).lower(),
        }
        local_role_providers = {
            "OLLAMA", "VLLM", "LM_STUDIO", "KOBOLDCPP", "LLAMACPP",
        }
        if prefix in local_role_providers:
            values.update({
                "BIG_BRAIN_ENABLED": str(role in ("Both", "Main only")).lower(),
                "SMALL_BRAIN_ENABLED": str(role in ("Both", "Chat only")).lower(),
            })
        os.environ.update(values)
        try:
            from main import set_env_values
            set_env_values(values)
        except Exception:
            pass
    
    def _on_action_clicked(self, provider_name: str):
        """Handle enable/disable action."""
        from agents.provider_manager import ProviderManager, ProviderStatus
        pm = ProviderManager.instance()
        provider = pm.get_provider(provider_name)
        if not provider:
            return
        
        if provider.status == ProviderStatus.RUNNING.value:
            # Disable
            provider.status = ProviderStatus.STOPPED.value
            self.status_label.setText(f"Disabled {provider_name}")
        else:
            # Enable
            provider.status = ProviderStatus.RUNNING.value
            self.status_label.setText(f"Enabled {provider_name}")

        prefix = self._provider_prefix(provider_name)
        runtime_name = ProviderManager.normalize_provider_name(provider_name)
        if prefix:
            self._persist_provider_role(
                prefix,
                "Both" if provider.status == ProviderStatus.RUNNING.value else "Disabled",
            )
        if provider.is_local and provider.status == ProviderStatus.RUNNING.value:
            local_provider_names = {
                "llamacpp": "llama.cpp",
                "ollama": "Ollama",
                "vllm": "vLLM",
                "lmstudio": "LM Studio",
                "koboldcpp": "KoboldCpp",
            }
            selected = runtime_name
            values = {
                "ACTIVE_LOCAL_PROVIDER": local_provider_names.get(selected, selected),
                "BIG_BRAIN_PROVIDER": selected,
                "SMALL_BRAIN_PROVIDER": selected,
                "BIG_BRAIN_ENABLED": "true",
                "SMALL_BRAIN_ENABLED": "true",
            }
            os.environ.update(values)
            try:
                from main import set_env_values
                set_env_values(values)
            except Exception:
                pass
            self.active_local.setCurrentText(local_provider_names.get(selected, selected))
        elif provider.is_local and provider.status != ProviderStatus.RUNNING.value:
            values = {}
            for role in ("BIG_BRAIN", "SMALL_BRAIN"):
                current = ProviderManager.normalize_provider_name(
                    os.getenv(f"{role}_PROVIDER", ""))
                if current == runtime_name:
                    values[f"{role}_ENABLED"] = "false"
            if values:
                values["ACTIVE_LOCAL_PROVIDER"] = "Auto"
                os.environ.update(values)
                try:
                    from main import set_env_values
                    set_env_values(values)
                except Exception:
                    pass
        
        self.status_label.setStyleSheet("color: #4caf50;")
        self.provider_changed.emit(provider_name, "toggle")
        self._build_provider_list("cloud" if self.type_tabs.currentIndex() == 0 else "local")
        if provider.is_local and provider.status == ProviderStatus.RUNNING.value:
            self._refresh_local_provider_card(provider_name)

    def _refresh_local_provider_card(self, provider_name: str):
        """Refresh a local card after rebuilding the provider list."""
        from agents.provider_manager import ProviderManager

        for combo in self.findChildren(QComboBox):
            if combo.toolTip() == "Select the active model":
                provider = ProviderManager.instance().get_provider(provider_name)
                if provider and provider.name == provider_name:
                    self._refresh_provider_models(provider_name, combo)
                    return

    def _refresh_provider_models(self, provider_name: str, combo: QComboBox):
        """Fetch current local models and update the provider card in place."""
        from agents.provider_manager import ProviderManager

        provider = ProviderManager.instance().get_provider(provider_name)
        if not provider or not provider.is_local:
            return
        selected = combo.currentData() or combo.currentText()
        models = ProviderManager.instance().refresh_provider_models(provider_name)
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(models)
            if selected and selected in models:
                combo.setCurrentText(selected)
            elif provider.selected_model and provider.selected_model in models:
                combo.setCurrentText(provider.selected_model)
        finally:
            combo.blockSignals(False)
        if models:
            self.status_label.setText(f"Found {len(models)} {provider.name} model(s)")
            self.status_label.setStyleSheet("color: #4caf50;")
        else:
            self.status_label.setText(f"No models found for {provider.name}; enter a model name manually")
            self.status_label.setStyleSheet("color: #ff9800;")
    
    def refresh(self):
        """Refresh the provider list."""
        # Rebuilding the cards destroys an open model popup. Let the user finish
        # choosing when a provider exposes a long model list.
        if any(
            combo.toolTip() == "Select the active model"
            and combo.view().isVisible()
            for combo in self.findChildren(QComboBox)
        ):
            return
        # Rebuild the current tab
        current_tab = self.type_tabs.currentIndex()
        if current_tab == 0:
            self._build_provider_list("cloud")
        else:
            self._build_provider_list("local")


class CloudProviderPanel(QWidget):
    """Cloud provider selection and configuration."""
    
    provider_changed = Signal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Provider selection
        select_group = QGroupBox("Select Cloud Provider")
        select_layout = QGridLayout(select_group)
        
        self.provider_combo = QComboBox()
        self.provider_combo.addItems([
            "OpenAI", "Anthropic", "OpenRouter", "Groq", 
            "DeepSeek", "Mistral", "Together"
        ])
        select_layout.addWidget(QLabel("Provider:"), 0, 0)
        select_layout.addWidget(self.provider_combo, 0, 1)
        
        # API key
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("Enter API key...")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        select_layout.addWidget(QLabel("API Key:"), 1, 0)
        select_layout.addWidget(self.api_key_edit, 1, 1)
        
        # Base URL (optional)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("Optional custom base URL...")
        select_layout.addWidget(QLabel("Base URL:"), 2, 0)
        select_layout.addWidget(self.base_url_edit, 2, 1)
        
        # Connect button
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self._on_connect)
        select_layout.addWidget(connect_btn, 3, 0, 1, 2)
        
        layout.addWidget(select_group)
        
        # Active providers table
        self.providers_table = QTableWidget()
        self.providers_table.setColumnCount(4)
        self.providers_table.setHorizontalHeaderLabels(["Provider", "Status", "Models", "Action"])
        self.providers_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.providers_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.providers_table)
        
        layout.addStretch()

    def _on_connect(self):
        """Handle connect button click."""
        provider = self.provider_combo.currentText()
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        
        if not api_key:
            QMessageBox.warning(self, "Error", "API key is required")
            return
        
        # Save to environment
        env_map = {
            "OpenAI": "OPENAI_API_KEY",
            "Anthropic": "ANTHROPIC_API_KEY",
            "OpenRouter": "OPENROUTER_API_KEY",
            "Groq": "GROQ_API_KEY",
            "DeepSeek": "DEEPSEEK_API_KEY",
            "Mistral": "MISTRAL_API_KEY",
            "Together": "TOGETHER_API_KEY",
        }
        
        env_var = env_map.get(provider, "")
        if env_var:
            os.environ[env_var] = api_key
            self.provider_changed.emit(provider, {"api_key": api_key, "base_url": base_url})


class LocalProviderPanel(QWidget):
    """Local provider management."""
    
    provider_changed = Signal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Provider tabs
        tabs = QTabWidget()
        
        # llama.cpp tab
        llama_tab = QWidget()
        llama_layout = QVBoxLayout(llama_tab)
        self._build_llama_config(llama_layout)
        tabs.addTab(llama_tab, "llama.cpp")
        
        # Ollama tab
        ollama_tab = QWidget()
        ollama_layout = QVBoxLayout(ollama_tab)
        self._build_ollama_config(ollama_layout)
        tabs.addTab(ollama_tab, "Ollama")
        
        # vLLM tab
        vllm_tab = QWidget()
        vllm_layout = QVBoxLayout(vllm_tab)
        self._build_vllm_config(vllm_layout)
        tabs.addTab(vllm_tab, "vLLM")
        
        layout.addWidget(tabs)
        layout.addStretch()
    
    def _build_llama_config(self, layout):
        """Build llama.cpp configuration."""
        layout.addWidget(QLabel("llama.cpp Configuration"))
        
        # Port
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port:"))
        self.llama_port = QSpinBox()
        self.llama_port.setRange(1024, 65535)
        self.llama_port.setValue(1234)
        port_layout.addWidget(self.llama_port)
        layout.addLayout(port_layout)
        
        # GPU
        gpu_layout = QHBoxLayout()
        gpu_layout.addWidget(QLabel("GPU:"))
        self.llama_gpu = QComboBox()
        self.llama_gpu.addItems(["CUDA0", "CUDA1", "CPU"])
        gpu_layout.addWidget(self.llama_gpu)
        layout.addLayout(gpu_layout)
        
        # Start button
        start_btn = QPushButton("Start llama.cpp")
        start_btn.clicked.connect(lambda: self.provider_changed.emit("llamacpp", {"action": "start"}))
        layout.addWidget(start_btn)
    
    def _build_ollama_config(self, layout):
        """Build Ollama configuration."""
        layout.addWidget(QLabel("Ollama Configuration"))
        
        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.ollama_url = QLineEdit("http://127.0.0.1:11434")
        url_layout.addWidget(self.ollama_url)
        layout.addLayout(url_layout)
        
        # Connect button
        connect_btn = QPushButton("Connect to Ollama")
        connect_btn.clicked.connect(lambda: self.provider_changed.emit("ollama", {"action": "connect", "url": self.ollama_url.text()}))
        layout.addWidget(connect_btn)
    
    def _build_vllm_config(self, layout):
        """Build vLLM configuration."""
        layout.addWidget(QLabel("vLLM Configuration"))
        
        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.vllm_url = QLineEdit("http://127.0.0.1:8000")
        url_layout.addWidget(self.vllm_url)
        layout.addLayout(url_layout)
        
        # Connect button
        connect_btn = QPushButton("Connect to vLLM")
        connect_btn.clicked.connect(lambda: self.provider_changed.emit("vllm", {"action": "connect", "url": self.vllm_url.text()}))
        layout.addWidget(connect_btn)


__all__ = [
    "ProviderConfigWidget",
    "CloudProviderPanel",
    "LocalProviderPanel",
]
