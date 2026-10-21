"""Qt workers for provider probing and stop operations."""

from PySide6.QtCore import QThread, Signal


class ProviderProbeWorker(QThread):
    """Check one provider endpoint without blocking the GUI thread."""

    probe_finished = Signal(bool, object)

    def __init__(self, checker, target, endpoint=False, provider="", model=""):
        super().__init__()
        self.checker = checker
        self.target = target
        self.endpoint = endpoint
        self.provider = provider
        self.model = model

    def run(self):
        try:
            if self.endpoint:
                if self.provider in ("lmstudio", "ollama"):
                    available, models = self.checker.check_loaded_provider(
                        self.provider, self.target, timeout=2)
                    wanted = (self.model or "").strip().lower()
                    loaded = {str(item).strip().lower() for item in models}
                    running = available and bool(wanted and wanted in loaded)
                else:
                    # Pass the provider so a CLOUD probe carries its Bearer
                    # token — without it a valid cloud brain probes 401 and the
                    # Providers & GPU row shows "Stopped" forever.
                    running, models = self.checker.check_endpoint(
                        self.target, timeout=2, provider=self.provider)
            else:
                running, models = self.checker.check_llama_server(
                    self.target, timeout=2)
        except Exception:
            running, models = False, []
        self.probe_finished.emit(running, models)


class ProviderStopWorker(QThread):
    """Stop one provider process without blocking the GUI thread."""

    stop_finished = Signal()

    def __init__(self, control, small: bool):
        super().__init__()
        self.control = control
        self.small = small

    def run(self):
        self.control._force_stop_brain(self.small)
        self.stop_finished.emit()


__all__ = ["ProviderProbeWorker", "ProviderStopWorker"]
