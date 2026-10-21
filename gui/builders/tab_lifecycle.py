"""Reusable tab lifecycle and visibility-aware refresh behavior."""

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


class TabLifecycleMixin:
    def _scroll_wrap(self, widget):
        """v2.0.34ag (A1): ensure a tab's content is always scrollable so group
        boxes never clip on small windows. No-op if already a QScrollArea."""
        if isinstance(widget, QScrollArea):
            return widget
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(widget)
        sa.setFrameShape(QScrollArea.NoFrame)
        return sa


    def _ensure_tab_built(self, index: int):
        """v2.0.34ag (A5): build a tab's real content on first show, replacing the
        placeholder. Idempotent.

        v2.0.34ak fix (misclick): do the removeTab/insertTab swap SYNCHRONOUSLY and
        mark the entry built *before* swapping. We deliberately do NOT blockSignals
        around the swap — blocking it left QTabWidget's internal currentIndex stale
        vs the visual tab bar, so the next click hit the wrong tab and only a second
        click re-synced. Marking built first makes the re-entrant currentChanged a
        no-op, so the natural signal keeps the tab bar in sync. We also force a
        tabBar relayout so hit-rects are correct immediately.

        v2.0.34an fix (startup flash + unwanted tab jump): building a tab whose
        content is *not* the one the operator is looking at must NOT yank the
        visible tab away. We capture the previously-current index and restore it
        after the swap; we only re-point currentIndex at the rebuilt tab when the
        operator had that tab open (prev == index). This stops the app from
        auto-jumping to the Settings tab 1.5 s after launch (the deferred
        Settings build in main.py __init__).
        """
        if not hasattr(self, "_tab_builders"):
            return
        prev = self.tabs.currentIndex()
        for entry in self._tab_builders:
            idx, builder, built = entry
            if idx == index and not built:
                label = self.tabs.tabText(index)
                try:
                    widget = builder()
                except Exception as exc:
                    widget = QWidget()
                    error_layout = QVBoxLayout(widget)
                    error_layout.addWidget(QLabel(
                        f"Providers & GPU could not be initialized:\n{exc}"))
                    error_layout.addWidget(QLabel(
                        "Open Live Logs for the full startup error."))
                    try:
                        self.log_signal.emit(f"[GUI] Tab '{label}' build failed: {exc}")
                    except Exception:
                        pass
                sa = self._scroll_wrap(widget)
                entry[2] = True  # mark built FIRST so a re-entrant currentChanged is a no-op
                self.tabs.removeTab(index)
                self.tabs.insertTab(index, sa, label)
                # Re-sync the tab bar's notion of the current tab and recompute
                # hit-rects so the next click lands on the right tab. Only force
                # focus to the rebuilt tab if the operator was already on it;
                # otherwise leave their current view untouched.
                if prev == index:
                    self.tabs.setCurrentIndex(index)
                else:
                    self.tabs.setCurrentIndex(prev if prev != -1 else index)
                self.tabs.tabBar().updateGeometry()
                self.tabs.tabBar().update()
                return



    def _on_tab_changed(self, index: int):
        # v2.0.34ag (A5): build the tab lazily on first open.
        self._ensure_tab_built(index)
        # v2.1: pause background polling (GPU monitor, refresh timers) on the
        # previously-visible tab and resume on the newly-shown one, so hidden
        # tabs stop hammering nvidia-smi / rebuilding tables (GUI perf).
        self._sync_background_tabs(index)
        # ARCH-ENG-275 (AB-01): the silent Ollama model refresh that ran here
        # existed only to populate the hidden Settings combos. Those combos are
        # gone; ProviderConfigWidget has its own per-provider Refresh control.

    def _find_bg_aware(self, w):
        from PySide6.QtWidgets import QScrollArea
        if w is None:
            return None
        if hasattr(w, "pause_background") and hasattr(w, "resume_background"):
            return w
        if isinstance(w, QScrollArea) and w.widget() is not None:
            return self._find_bg_aware(w.widget())
        lay = w.layout() if hasattr(w, "layout") else None
        if lay is not None:
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item is not None and item.widget() is not None:
                    r = self._find_bg_aware(item.widget())
                    if r is not None:
                        return r
        return None

    def _sync_background_tabs(self, new_index: int):
        prev = getattr(self, "_last_active_tab", -1)
        self._last_active_tab = new_index
        if prev == new_index or prev == -1:
            w = self._find_bg_aware(self.tabs.widget(new_index))
            if w is not None and hasattr(w, "resume_background"):
                try:
                    w.resume_background()
                except Exception:
                    pass
            return
        old = self._find_bg_aware(self.tabs.widget(prev))
        if old is not None and hasattr(old, "pause_background"):
            try:
                old.pause_background()
            except Exception:
                pass
        new = self._find_bg_aware(self.tabs.widget(new_index))
        if new is not None and hasattr(new, "resume_background"):
            try:
                new.resume_background()
            except Exception:
                pass




__all__ = ["TabLifecycleMixin"]
