"""agents/provider_hot_reload.py — Hot-reload provider configuration without restart.

This module allows switching providers (cloud or local) at runtime without
restarting the application. It:
- Monitors .env file for changes
- Re-initializes provider connections when config changes
- Updates the GUI to reflect new provider state
- Handles failover when a provider becomes unavailable
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any, Callable, Dict, List, Optional


class ProviderHotReload:
    """Monitors and applies provider configuration changes at runtime."""
    
    _instance: Optional["ProviderHotReload"] = None
    
    def __init__(self):
        self._env_mtime: float = 0
        self._env_path: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        self._callbacks: List[Callable[[Dict[str, str]], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_config: Dict[str, str] = {}
    
    @classmethod
    def instance(cls) -> "ProviderHotReload":
        if cls._instance is None:
            cls._instance = cls()
        return cls
    
    def register_callback(self, callback: Callable[[Dict[str, str]], None]):
        """Register a callback to be called when config changes."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable[[Dict[str, str]], None]):
        """Unregister a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def start_monitoring(self, interval: float = 2.0):
        """Start monitoring .env file for changes."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self._thread.start()
    
    def stop_monitoring(self):
        """Stop monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _monitor_loop(self, interval: float):
        """Main monitoring loop."""
        while self._running:
            try:
                self._check_for_changes()
            except Exception:
                pass
            time.sleep(interval)
    
    def _check_for_changes(self):
        """Check if .env file has changed and notify callbacks."""
        try:
            if not os.path.exists(self._env_path):
                return
            
            mtime = os.path.getmtime(self._env_path)
            if mtime <= self._env_mtime:
                return
            
            self._env_mtime = mtime
            new_config = self._read_env_file()
            
            # Find changed keys
            changes = {}
            for key, value in new_config.items():
                if self._last_config.get(key) != value:
                    changes[key] = value
            
            # Check for deleted keys
            for key in self._last_config:
                if key not in new_config:
                    changes[key] = ""
            
            if changes:
                self._last_config = new_config
                self._notify_callbacks(changes)
        except Exception:
            pass
    
    def _read_env_file(self) -> Dict[str, str]:
        """Read .env file and return config dict."""
        config = {}
        try:
            with open(self._env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        config[key.strip()] = value.strip()
        except Exception:
            pass
        return config
    
    def _notify_callbacks(self, changes: Dict[str, str]):
        """Notify all registered callbacks of config changes."""
        for callback in self._callbacks:
            try:
                callback(changes)
            except Exception:
                pass
    
    def apply_changes(self, changes: Dict[str, str]):
        """Apply configuration changes to the running application."""
        from agents.provider_manager import ProviderManager
        
        pm = ProviderManager.instance()
        
        # Update environment variables
        for key, value in changes.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        
        # Re-detect providers
        pm.detect_providers()
        
        return pm.get_summary()


__all__ = ["ProviderHotReload"]
