"""Worker roster and ownership state for the manager."""

from __future__ import annotations

from typing import Callable, Dict, Optional


class ManagerWorkerRegistry:
    """Track registered workers without depending on Qt or worker classes."""

    def __init__(
        self,
        default_worker=None,
        *,
        on_registered: Optional[Callable[[str, str], None]] = None,
        on_busy: Optional[Callable[[str, str], None]] = None,
        on_free: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.roster: Dict[str, dict] = {
            "Coder": {
                "worker": default_worker,
                "busy": False,
                "current_task": "",
            }
        }
        self._on_registered = on_registered
        self._on_busy = on_busy
        self._on_free = on_free

    def register(self, name: str, worker_obj, specialty: str = "") -> None:
        self.roster[name] = {
            "worker": worker_obj,
            "busy": False,
            "current_task": "",
            "specialty": specialty,
        }
        if self._on_registered is not None:
            self._on_registered(name, specialty)

    def free_worker(self, preferred: Optional[str] = None) -> Optional[str]:
        if preferred and preferred in self.roster:
            if not self.roster[preferred]["busy"]:
                return preferred
        for name, info in self.roster.items():
            if not info["busy"]:
                return name
        return None

    def set_busy(self, name: str, task: str) -> None:
        if name in self.roster:
            self.roster[name]["busy"] = True
            self.roster[name]["current_task"] = task
            if self._on_busy is not None:
                self._on_busy(name, task)

    def set_free(self, name: str) -> None:
        if name in self.roster:
            self.roster[name]["busy"] = False
            self.roster[name]["current_task"] = ""
            if self._on_free is not None:
                self._on_free(name)


__all__ = ["ManagerWorkerRegistry"]
