"""Hugging Face GGUF model browser and installer."""

from __future__ import annotations

import threading
import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agents.huggingface_models import (
    GGUFArtifact,
    HuggingFaceGGUFModel,
    HuggingFaceModelService,
    download_artifact,
    provider_install_targets,
)


def _format_rate(bytes_per_second: float) -> str:
    value = max(float(bytes_per_second), 0.0)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024 or unit == "GB/s":
            return f"{value:.1f} {unit}"
        value /= 1024


def _format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "calculating"
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


class ModelSearchWorker(QThread):
    results_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, query: str, page: int, limit: int, task: str = "", library: str = "", parent=None):
        super().__init__(parent)
        self.query, self.page, self.limit, self.task, self.library = query, page, limit, task, library

    def run(self):
        try:
            models = HuggingFaceModelService().search(self.query, self.page, self.limit, self.task, self.library)
            self.results_ready.emit(models)
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelDetailWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, repo_id: str, parent=None):
        super().__init__(parent)
        self.repo_id = repo_id

    def run(self):
        try:
            self.loaded.emit(HuggingFaceModelService().inspect(self.repo_id))
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelDownloadWorker(QThread):
    # Qt's `int` signal type is signed 32-bit; GGUF files commonly exceed 4 GB.
    # Python objects preserve the full 64-bit byte counters across the thread.
    progress = Signal(object, object, object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, artifact: GGUFArtifact, destination: Path, pause_event, cancel_event, parent=None):
        super().__init__(parent)
        self.artifact = artifact
        self.destination = destination
        self.pause_event = pause_event
        self.cancel_event = cancel_event

    def run(self):
        try:
            path = download_artifact(
                self.artifact,
                self.destination,
                self.pause_event,
                self.cancel_event,
                lambda done, total, speed=0.0: self.progress.emit(done, total, speed),
            )
            self.completed.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelLibraryTab(QWidget):
    """Search, inspect, filter, and install GGUF models without blocking Qt."""

    model_installed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.models: list[HuggingFaceGGUFModel] = []
        self.page = 0
        self.search_worker = None
        self.detail_worker = None
        self._detail_repo = ""
        self.download_worker = None
        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()
        self._build_ui()
        self._set_status("Search Hugging Face for GGUF repositories over HTTPS.")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        intro = QLabel("Model Library · Hugging Face GGUF")
        intro.setStyleSheet("font-size:18px; font-weight:bold; color:#4fc3f7;")
        root.addWidget(intro)
        root.addWidget(QLabel("Browse model cards and exact GGUF files, then install one into a local model directory."))

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search models, families, or tasks (for example: Qwen coder)")
        self.search_edit.returnPressed.connect(self._search)
        search_row.addWidget(self.search_edit, 1)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._search)
        search_row.addWidget(self.search_button)
        self.list_models_button = QPushButton("List models")
        self.list_models_button.setToolTip("Load models from Hugging Face using the selected filters")
        self.list_models_button.clicked.connect(self._list_models)
        search_row.addWidget(self.list_models_button)
        self.page_size = QComboBox()
        self.page_size.addItems(["100 per page", "50 per page", "250 per page", "1000 per page"])
        search_row.addWidget(self.page_size)
        self.task_filter = QComboBox()
        self.task_filter.addItem("All tasks", "")
        for label, value in (("Text generation", "text-generation"), ("Image-text-to-text", "image-text-to-text"), ("Text-to-image", "text-to-image"), ("Text-to-speech", "text-to-speech"), ("Feature extraction / embeddings", "feature-extraction"), ("Conversational", "conversational")):
            self.task_filter.addItem(label, value)
        search_row.addWidget(self.task_filter)
        self.library_filter = QComboBox()
        self.library_filter.addItem("GGUF repositories", "")
        self.library_filter.addItem("Any Hugging Face library", "any")
        self.library_filter.addItems(["Transformers", "llama.cpp", "llama-cpp-python"])
        search_row.addWidget(self.library_filter)
        root.addLayout(search_row)

        filter_row = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(["Any type", "Dense", "MoE", "Unknown type"])
        self.type_filter.currentTextChanged.connect(self._apply_filters)
        self.min_params = QSpinBox()
        self.min_params.setRange(0, 1000)
        self.min_params.setSuffix("B min")
        self.min_params.valueChanged.connect(self._apply_filters)
        self.max_params = QSpinBox()
        self.max_params.setRange(0, 1000)
        self.max_params.setValue(1000)
        self.max_params.setSuffix("B max")
        self.max_params.valueChanged.connect(self._apply_filters)
        self.quant_filter = QComboBox()
        self.quant_filter.addItems(["Any quantization", "Q2", "Q3", "Q4", "Q5", "Q6", "Q8", "F16", "BF16", "F32"])
        self.quant_filter.currentTextChanged.connect(self._apply_filters)
        self.category_filter = QComboBox()
        self.category_filter.addItems(["Chat/generative + vision", "All model types", "Chat/generative", "Vision", "Embeddings", "Other"])
        self.category_filter.currentTextChanged.connect(self._apply_filters)
        for label, widget in (("Type", self.type_filter), ("Category", self.category_filter), ("Parameters", self.min_params), ("", self.max_params), ("Quantization", self.quant_filter)):
            if label:
                filter_row.addWidget(QLabel(label))
            filter_row.addWidget(widget)
        filter_row.addStretch(1)
        root.addLayout(filter_row)

        content = QHBoxLayout()
        self.result_list = QListWidget()
        self.result_list.currentRowChanged.connect(self._show_model)
        content.addWidget(self.result_list, 2)

        detail_box = QGroupBox("Model details")
        detail_layout = QVBoxLayout(detail_box)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        detail_layout.addWidget(self.details, 1)
        artifact_row = QHBoxLayout()
        artifact_row.addWidget(QLabel("GGUF file"))
        self.artifact_combo = QComboBox()
        self.artifact_combo.currentIndexChanged.connect(self._update_artifact_status)
        artifact_row.addWidget(self.artifact_combo, 1)
        detail_layout.addLayout(artifact_row)
        content.addWidget(detail_box, 3)
        root.addLayout(content, 1)

        install_row = QHBoxLayout()
        install_row.addWidget(QLabel("Install for"))
        self.provider_target = QComboBox()
        self.provider_targets = provider_install_targets()
        for target in self.provider_targets:
            self.provider_target.addItem(target.label, target)
        active = os.getenv("ACTIVE_LOCAL_PROVIDER", "").strip().lower()
        for index, target in enumerate(self.provider_targets):
            if target.key == active or (active == "llama.cpp" and target.key == "llamacpp"):
                self.provider_target.setCurrentIndex(index)
                break
        self.provider_target.currentIndexChanged.connect(self._provider_target_changed)
        install_row.addWidget(self.provider_target)
        self.location_edit = QLineEdit(str(Path.home() / "MrBot1000" / "models"))
        self.location_edit.setPlaceholderText("Choose an install folder")
        install_row.addWidget(QLabel("Install location"))
        install_row.addWidget(self.location_edit, 1)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._choose_location)
        install_row.addWidget(browse)
        self.download_button = QPushButton("Download selected GGUF")
        self.download_button.clicked.connect(self._download)
        install_row.addWidget(self.download_button)
        root.addLayout(install_row)

        self.provider_note = QLabel()
        self.provider_note.setWordWrap(True)
        root.addWidget(self.provider_note)
        self._provider_target_changed(0)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        progress_row.addWidget(self.progress, 1)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.pause_button.setEnabled(False)
        progress_row.addWidget(self.pause_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel_download)
        self.cancel_button.setEnabled(False)
        progress_row.addWidget(self.cancel_button)
        root.addLayout(progress_row)

        page_row = QHBoxLayout()
        self.previous_button = QPushButton("Previous page")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        self.next_button = QPushButton("Next page")
        self.next_button.clicked.connect(lambda: self._change_page(1))
        page_row.addWidget(self.previous_button)
        page_row.addWidget(self.next_button)
        self.status = QLabel()
        page_row.addWidget(self.status, 1)
        root.addLayout(page_row)

    def _set_status(self, text: str):
        self.status.setText(text)

    def _search(self):
        if self.search_worker and self.search_worker.isRunning():
            return
        self.page = 0
        self._run_search()

    def _list_models(self):
        """Browse the Hugging Face catalog without requiring a text query."""
        self.search_edit.clear()
        self._search()

    def _run_search(self):
        limits = (100, 50, 250, 1000)
        limit = limits[self.page_size.currentIndex()]
        self.search_button.setEnabled(False)
        self._set_status("Searching Hugging Face catalog...")
        library = self.library_filter.currentText()
        library = "" if library in {"GGUF repositories", "Any Hugging Face library"} else library
        self.search_worker = ModelSearchWorker(self.search_edit.text().strip(), self.page, limit, self.task_filter.currentData() or "", library, self)
        self.search_worker.results_ready.connect(self._search_finished)
        self.search_worker.failed.connect(self._search_failed)
        self.search_worker.finished.connect(lambda: self.search_button.setEnabled(True))
        self.search_worker.start()

    def _search_finished(self, models):
        self.models = models
        self._apply_filters()
        self._set_status(f"Page {self.page + 1}: {len(models)} Hugging Face repositories loaded. Non-runnable GGUF companions are excluded.")

    def _search_failed(self, message: str):
        self._set_status(f"Search failed: {message}")

    def _apply_filters(self):
        selected_type = self.type_filter.currentText()
        selected_category = self.category_filter.currentText()
        quant = self.quant_filter.currentText()
        minimum, maximum = self.min_params.value(), self.max_params.value()
        visible = []
        for model in self.models:
            if selected_type != "Any type" and model.type_label != selected_type:
                continue
            if selected_category != "All model types":
                allowed = {"Chat/generative + vision": {"chat/generative", "vision"}, "Chat/generative": {"chat/generative"}, "Vision": {"vision"}, "Embeddings": {"embedding"}, "Other": {"other"}}[selected_category]
                if model.category not in allowed:
                    continue
            if model.params_billion is not None and not (minimum <= model.params_billion <= maximum):
                continue
            if quant != "Any quantization" and not any(a.quantization.startswith(quant) for a in model.artifacts):
                continue
            if model.artifacts:
                visible.append(model)
        self.result_list.clear()
        for model in visible:
            item = QListWidgetItem(f"{model.title} · {model.size_label} · {model.size_band} · {model.type_label} · {model.category} · {model.downloads:,} downloads")
            item.setData(Qt.UserRole, model)
            self.result_list.addItem(item)
        if visible:
            self.result_list.setCurrentRow(0)
        else:
            self.details.clear()
            self.artifact_combo.clear()

    def _show_model(self, row: int):
        self.artifact_combo.clear()
        if row < 0:
            self.details.clear()
            return
        model = self.result_list.item(row).data(Qt.UserRole)
        self._render_model(model)
        if not model.model_card:
            self._detail_repo = model.repo_id
            self.detail_worker = ModelDetailWorker(model.repo_id, self)
            self.detail_worker.loaded.connect(self._detail_loaded)
            self.detail_worker.failed.connect(lambda message: self._set_status(f"Metadata unavailable: {message}"))
            self.detail_worker.start()

    def _detail_loaded(self, model):
        if model.repo_id != self._detail_repo:
            return
        row = self.result_list.currentRow()
        if row >= 0:
            item = self.result_list.item(row)
            if item.data(Qt.UserRole).repo_id == model.repo_id:
                item.setData(Qt.UserRole, model)
        self._render_model(model)

    def _render_model(self, model):
        self.artifact_combo.clear()
        description = model.description.replace("<", "&lt;").replace(">", "&gt;")
        self.details.setHtml(
            f"<h3>{model.title}</h3><p><b>Repository:</b> <a href='{model.site_url}'>{model.repo_id}</a><br>"
            f"<b>Architecture:</b> {model.architecture} · <b>Type:</b> {model.type_label}<br>"
            f"<b>Category:</b> {model.category} · <b>Task:</b> {model.task}<br>"
            f"<b>Parameters:</b> {model.size_label} · <b>Band:</b> {model.size_band} · <b>License:</b> {model.license}<br>"
            f"<b>Downloads:</b> {model.downloads:,} · <b>Context:</b> {model.context or 'unknown'}<br>"
            f"<b>Capabilities:</b> {', '.join(model.capabilities) or 'unknown'}<br>"
            f"<b>Metadata:</b> {model.metadata_source}</p>"
            f"<p><b>Backend:</b> GGUF is directly compatible with llama.cpp, LM Studio, and KoboldCpp. "
            f"Ollama requires an import/Modelfile step; vLLM compatibility depends on its configured backend.</p>"
            f"<p>{description or 'No model description was supplied.'}</p>"
        )
        for artifact in model.artifacts:
            self.artifact_combo.addItem(f"{artifact.name} · {artifact.quantization} · {artifact.size_label}", artifact)

    def _update_artifact_status(self):
        artifact = self.artifact_combo.currentData()
        if artifact:
            self._set_status(f"Selected {artifact.name}; required disk space is approximately {artifact.size_label}.")

    def _choose_location(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose model install location", self.location_edit.text())
        if folder:
            self.location_edit.setText(folder)

    def _provider_target_changed(self, index: int):
        target = self.provider_target.itemData(index)
        if target is None:
            return
        self.location_edit.setText(str(target.directory))
        self.provider_note.setText(f"{target.note} Default detected location: {target.directory}")
        self.download_button.setText(
            "Download and prepare Ollama import" if target.mode == "ollama-import" else
            "Download GGUF" if target.mode != "unsupported-gguf" else "Download with compatibility warning"
        )

    def _download(self):
        artifact = self.artifact_combo.currentData()
        if not artifact:
            QMessageBox.warning(self, "No GGUF selected", "Select a model and a GGUF quantization first.")
            return
        destination = Path(self.location_edit.text()).expanduser()
        if not destination.is_absolute():
            QMessageBox.warning(self, "Invalid location", "Choose an absolute install location.")
            return
        target = self.provider_target.currentData()
        if target and target.mode == "unsupported-gguf":
            answer = QMessageBox.warning(
                self,
                "vLLM GGUF compatibility",
                target.note + " Continue downloading this GGUF anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.pause_event.clear()
        self.cancel_event.clear()
        self.progress.setValue(0)
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.download_button.setEnabled(False)
        self.download_worker = ModelDownloadWorker(artifact, destination, self.pause_event, self.cancel_event, self)
        self.download_worker.progress.connect(self._download_progress)
        self.download_worker.completed.connect(self._download_completed)
        self.download_worker.failed.connect(self._download_failed)
        self.download_worker.start()

    def _download_progress(self, completed: int, total: int, speed: float = 0.0):
        completed = max(int(completed), 0)
        total = max(int(total), 0)
        speed = max(float(speed), 0.0)
        # QProgressBar's range is also a signed 32-bit Qt int. Keep it as a
        # percentage and show exact large-file counters in the status label.
        percentage = int((completed * 100) / total) if total else 0
        self.progress.setRange(0, 100)
        self.progress.setValue(min(max(percentage, 0), 100))
        remaining = max(total - completed, 0)
        eta = remaining / speed if speed > 0 else 0
        self._set_status(
            f"Downloading: {completed:,} / {total:,} bytes · "
            f"{_format_rate(speed)} · ETA {_format_eta(eta)}"
        )

    def _toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.setText("Pause")
            self._set_status("Download resumed.")
        else:
            self.pause_event.set()
            self.pause_button.setText("Resume")
            self._set_status("Download paused; the partial file is retained.")

    def _cancel_download(self):
        self.cancel_event.set()
        self._set_status("Canceling download...")

    def _finish_download(self):
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.download_button.setEnabled(True)
        self.pause_button.setText("Pause")

    def _download_completed(self, path: str):
        self._finish_download()
        self.progress.setValue(self.progress.maximum())
        target = self.provider_target.currentData()
        suffix = " Ollama still requires a Modelfile/import step." if target and target.mode == "ollama-import" else ""
        self._set_status(f"Installed {Path(path).name}.{suffix} Local model lists will refresh.")
        self.model_installed.emit(path)

    def _download_failed(self, message: str):
        self._finish_download()
        self._set_status(f"Download stopped: {message}")

    def _change_page(self, delta: int):
        if self.page + delta < 0:
            return
        self.page += delta
        self._run_search()

    def closeEvent(self, event):
        self.cancel_event.set()
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.wait(2000)
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.wait(2000)
        super().closeEvent(event)
