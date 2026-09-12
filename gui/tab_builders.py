# MrBot1000/gui/tab_builders.py — GUI tab builders (extracted from main.py,
# v2.0.34ah, Section E part B). Mixed into MainWindow as TabBuildersMixin so the
# ~2k lines of tab-construction UI live in their own module while still being
# MainWindow instance methods (so `self.*` access is unchanged).
import os

from PySide6.QtCore import QTimer, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from ui import (  # GUI sprite + Agents tab widget used by create_agents_tab
    AgentSprite,
    AgentsTab,
)


class DataExplorerWorker(QThread):
    """Run web scraping away from the GUI thread."""

    finished = Signal(dict)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            from agents.web_scraper import WebScraper
            result = WebScraper().scrape(self.url, extract_tables=True)
        except Exception as exc:
            result = {"ok": False, "url": self.url, "error": str(exc)}
        self.finished.emit(result)


class TabBuildersMixin:
    """Provides all create_*_tab methods + tab machinery for MainWindow."""


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
        # Auto-populate the Ollama model dropdowns (silent) the first time the
        # Settings tab is shown (v2.0.20h / v2.0.34al). Avoids requiring a manual
        # Refresh click and avoids re-querying Ollama on every tab switch.
        if self._ollama_autorefresh_done:
            return
        if index == self._settings_tab_index:
            self._ollama_autorefresh_done = True
            self.populate_ollama_model_combos()

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


    def create_agents_tab(self):
        # v2.1 fix: main.py's "Agents" tab spec points here, which was only the
        # sprite setup stub and returned None -> the Agents tab rendered empty.
        # Delegate to the full builder so the real AgentsTab (chat + roster) shows.
        return self.create_agents_tab_original()

    def create_chat_tab(self):
        """Create the Chat tab (Human ↔ Small Brain)."""
        from agents.big_brain import BigBrainAdapter
        from agents.small_brain import SmallBrainAdapter
        from gui.chat_tab import ChatTab

        # Initialize brain adapters if not already done
        if not hasattr(self, 'big_brain') or self.big_brain is None:
            self.big_brain = BigBrainAdapter()
        if not hasattr(self, 'small_brain') or self.small_brain is None:
            self.small_brain = SmallBrainAdapter()

        self.chat_tab = ChatTab(
            small_brain=self.small_brain,
            big_brain=self.big_brain,
            parent=self
        )
        # Bridge: when a Chat exchange completes, forward it to the Dialogue tab
        # so the two brains continue the thread (option A). The handler ensures the
        # Dialogue tab exists (lazily builds it) and calls ingest_exchange.
        try:
            self.chat_tab.exchange_complete.connect(self._bridge_chat_to_dialogue)
        except Exception:
            pass
        return self.chat_tab

    def _bridge_chat_to_dialogue(self, user_msg: str, small_reply: str):
        """Route a completed Chat-tab exchange into the Dialogue tab so it continues
        with a Big Brain follow-up (v2.0.36z). Only forwards when the Dialogue tab has
        already been opened (built) — never forces a heavy background brain to spin up
        just because the user chatted. If it isn't built yet, the Chat tab still shows
        the exchange."""
        try:
            dialogue = getattr(self, "dialogue_tab", None)
            if dialogue is not None and hasattr(dialogue, "ingest_exchange"):
                dialogue.ingest_exchange(user_msg, small_reply)
        except Exception:
            pass

    def create_dialogue_tab(self):
        """Create the Dialogue tab (Big Brain ↔ Small Brain)."""
        from agents.big_brain import BigBrainAdapter
        from agents.small_brain import SmallBrainAdapter
        from gui.dialogue_tab import DialogueTab

        # Initialize brain adapters if not already done
        if not hasattr(self, 'big_brain') or self.big_brain is None:
            self.big_brain = BigBrainAdapter()
        if not hasattr(self, 'small_brain') or self.small_brain is None:
            self.small_brain = SmallBrainAdapter()

        self.dialogue_tab = DialogueTab(
            small_brain=self.small_brain,
            big_brain=self.big_brain,
            parent=self
        )
        # Mirror a goal typed into the Dialogue tab over to the Collaboration tab
        # (if it exists yet) so both surfaces share the active objective.
        try:
            self.dialogue_tab.goal_changed.connect(self._bridge_goal_to_collaboration)
        except Exception:
            pass
        try:
            providers = getattr(self, "providers_gpu_tab", None)
            if providers is not None:
                providers.small_brain_model_changed.connect(
                    lambda model: self.dialogue_tab.on_model_changed("small"))
                providers.big_brain_model_changed.connect(
                    lambda model: self.dialogue_tab.on_model_changed("big"))
        except Exception:
            pass
        return self.dialogue_tab

    def _bridge_goal_to_collaboration(self, goal: str):
        """Mirror the Dialogue tab's goal into the Collaboration tab's goal box."""
        try:
            collab = getattr(self, "collaboration_tab", None)
            if collab is not None and hasattr(collab, "goal_input"):
                collab.goal_input.setText(goal)
        except Exception:
            pass

    def _bridge_goal_to_dialogue(self, goal: str):
        """Mirror the Collaboration tab's goal into the Dialogue tab."""
        try:
            dialogue = getattr(self, "dialogue_tab", None)
            if dialogue is not None and hasattr(dialogue, "set_goal"):
                dialogue.set_goal(goal)
        except Exception:
            pass

    def create_providers_gpu_tab(self):
        """Create the unified Providers & GPU tab — single DualBrainControl interface
        with llama.cpp settings (model dropdowns, ctx-size, threads, n-gpu-layers).
        Replaces the old LlamaManager + DualBrainControl splitter."""
        from PySide6.QtWidgets import QVBoxLayout

        from agents.big_brain import BigBrainAdapter
        from agents.small_brain import SmallBrainAdapter
        from agents.dual_brain_runtime import DualBrainRuntime
        from gui.dual_brain_control import DualBrainControl

        # Initialize brain adapters if not already done
        if not hasattr(self, 'big_brain') or self.big_brain is None:
            self.big_brain = BigBrainAdapter()
        if not hasattr(self, 'small_brain') or self.small_brain is None:
            self.small_brain = SmallBrainAdapter()

        # v2.1 Phase 5: share ONE canonical runtime across all tabs so the
        # Providers & GPU panel observes the same endpoint/model/device contract
        # as the Collaboration monitor and the adapters.
        if not hasattr(self, "dual_brain_runtime") or self.dual_brain_runtime is None:
            self.dual_brain_runtime = DualBrainRuntime.from_env()

        # Single unified widget — DualBrainControl is the better-looking interface
        # and now includes llama.cpp settings + model dropdowns
        self.providers_gpu_tab = DualBrainControl(parent=self,
                                                  runtime=self.dual_brain_runtime)
        self.providers_gpu_tab.big_brain = self.big_brain
        self.providers_gpu_tab.small_brain = self.small_brain
        dialogue = getattr(self, "dialogue_tab", None)
        if dialogue is not None:
            self.providers_gpu_tab.small_brain_model_changed.connect(
                lambda model: dialogue.on_model_changed("small"))
            self.providers_gpu_tab.big_brain_model_changed.connect(
                lambda model: dialogue.on_model_changed("big"))
        
        # Sync adapter models from GUI selection
        self.providers_gpu_tab._sync_adapter_model(False)
        self.providers_gpu_tab._sync_adapter_model(True)

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(self.providers_gpu_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setStretchFactor(self.providers_gpu_tab, 1)
        # Ensure the wrapper requests enough space so it doesn't collapse
        # when wrapped in the _scroll_wrap QScrollArea.
        wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        wrapper.setMinimumHeight(450)
        return wrapper

    def create_model_library_tab(self):
        """Create the HTTPS Hugging Face GGUF browser and installer."""
        from gui.model_library_tab import ModelLibraryTab

        self.model_library_tab = ModelLibraryTab(parent=self)
        self.model_library_tab.model_installed.connect(self._refresh_installed_models)
        return self.model_library_tab

    def _refresh_installed_models(self, _path: str = ""):
        """Refresh both local model selectors after a library download."""
        control = getattr(self, "providers_gpu_tab", None)
        if control is None:
            return
        try:
            if _path:
                # Keep custom/provider-selected install folders discoverable for
                # this session without replacing the user's existing GGUF path.
                import os
                import pathlib
                current = os.getenv("MODEL_LIBRARY_DIR", "").strip()
                parent = str(pathlib.Path(_path).parent)
                if parent not in current.split(os.pathsep):
                    os.environ["MODEL_LIBRARY_DIR"] = os.pathsep.join(filter(None, (current, parent)))
            control._repopulate_model_combo(True)
            control._repopulate_model_combo(False)
        except Exception as exc:
            try:
                self.log_signal.emit(f"[GUI] Installed model refresh failed: {exc}")
            except Exception:
                pass

    def create_safety_tools_tab(self):
        """Create the Safety & Tools tab."""
        from gui.safety_tools_tab import SafetyTab
        self.safety_tools_tab = SafetyTab(parent=self)
        return self.safety_tools_tab

    def create_collaboration_tab(self):
        """Create the Collaboration / Run Monitor tab.

        Owns the shared DualBrainCoordinator (backed by the canonical runtime)
        so Chat/Dialogue/monitor all observe the same collaboration ledger. The
        injected model_fn routes inference to the Big/Small brain adapters; a
        down server degrades to a FAILED run (never blocks or crashes).
        """
        from agents.comms_log import MessageLog
        from agents.dual_brain_coordinator import DualBrainCoordinator
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        from gui.collaboration_tab import CollaborationTab

        # Shared canonical runtime (cheap: no network at construction).
        if not hasattr(self, "dual_brain_runtime") or self.dual_brain_runtime is None:
            self.dual_brain_runtime = DualBrainRuntime.from_env()

        def _model_fn(role, _stage, prompt):
            if role == BrainRole.BIG:
                from agents.big_brain import BigBrainAdapter
                return BigBrainAdapter().analyze_with_tools(prompt)
            from agents.small_brain import SmallBrainAdapter
            return SmallBrainAdapter().chat(prompt)

        if not hasattr(self, "dual_brain_coordinator") or self.dual_brain_coordinator is None:
            msg_log_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "dual_brain_messages.db")
            self.dual_brain_coordinator = DualBrainCoordinator(
                runtime=self.dual_brain_runtime,
                model_fn=_model_fn,
                log=MessageLog(msg_log_path),
            )

        self.collaboration_tab = CollaborationTab(
            coordinator=self.dual_brain_coordinator, parent=self)
        # Mirror a goal submitted here over to the Dialogue tab.
        try:
            self.collaboration_tab.goal_changed.connect(self._bridge_goal_to_dialogue)
        except Exception:
            pass
        return self.collaboration_tab

    def create_agents_tab_original(self):
        # Create sprites
        self.agent_sprite = AgentSprite(label="Worker")
        self.summarizer_sprite = AgentSprite(label="Summarizer")
        self.summarizer_sprite.set_state("idle")

        # Connect summarizer signals to main window methods
        self.summarizer.status_changed.connect(self._on_summarizer_status)
        self.summarizer.paused_changed.connect(self._on_summarizer_paused)

        # Create the tab widget with all new window callbacks
        tab = AgentsTab(
            self,
            worker_sprite=self.agent_sprite,
            summarizer_sprite=self.summarizer_sprite,
            worker_status_signal=self.manager.agent_status,
            summarizer_status_signal=self.summarizer.status_changed,
            show_thoughts_cb=self._show_thoughts,
            toggle_worker_pause_cb=self._toggle_pause,
            toggle_summarizer_pause_cb=self._toggle_summarizer_pause,
            heartbeat_interval=self.manager.HEARTBEAT_INTERVAL,
            on_send=self._human_send,
            on_strategy_change=self._on_strategy_change,
            show_manager_win_cb=self._show_manager_win,
            show_agent_win_cb=self._show_agent_win,
            show_comms_win_cb=self._show_comms_win,
            show_summary_win_cb=self._show_summary_win,
        )
        self.agents_tab = tab

        # Wire pipeline to summarizer for spelling assist
        if hasattr(self, "pipeline"):
            self.pipeline.set_summarizer(self.summarizer.worker)

        return tab


    def create_management_tab(self):
        """Management Control Center — administrative-only edition.
        
        Brain start/stop/restart and model selection live exclusively in
        Providers & GPU. This tab handles earnings, research, proposals,
        payouts, and system actions only.
        """
        from gui.management_tab import ManagementTab
        self.management_tab = ManagementTab(parent=self)
        
        # Connect signals to main window methods
        self.management_tab.request_run_cycle.connect(self._run_earning_cycle)
        self.management_tab.request_force_improve.connect(self.force_safe_improve)
        self.management_tab.request_force_rescan.connect(self.force_research_rescan)
        self.management_tab.request_select_research_folder.connect(self.select_research_folder)
        self.management_tab.request_review_proposal.connect(self._on_management_review_proposal)
        self.management_tab.request_submit_proposal.connect(self._on_management_submit_proposal)
        self.management_tab.request_verify_paid.connect(self._on_management_verify_paid)
        self._attach_memory_stream_panel(self.management_tab)
        
        return self.management_tab

    def _attach_memory_stream_panel(self, management_tab):
        """Keep useful legacy telemetry in Management without a separate tab."""
        stream_group = QGroupBox("Stream Health")
        stream_layout = QVBoxLayout(stream_group)
        self.stream_health_label = QLabel("Starting...")
        self.stream_health_label.setWordWrap(True)
        stream_layout.addWidget(self.stream_health_label)

        memory_group = QGroupBox("Memory (chat + CEO / long-term)")
        memory_layout = QVBoxLayout(memory_group)
        self.memory_view = QTextEdit()
        self.memory_view.setReadOnly(True)
        self.memory_view.setMinimumHeight(120)
        memory_layout.addWidget(self.memory_view)
        buttons = QHBoxLayout()
        self.memory_chat_clear_btn = QPushButton("Clear Chat memory")
        self.memory_main_clear_btn = QPushButton("Clear CEO memory")
        self.memory_notes_clear_btn = QPushButton("Clear long-term notes")
        self.memory_refresh_btn = QPushButton("Refresh")
        self.memory_chat_clear_btn.clicked.connect(lambda: self._clear_memory("chat"))
        self.memory_main_clear_btn.clicked.connect(lambda: self._clear_memory("main"))
        self.memory_notes_clear_btn.clicked.connect(lambda: self._clear_memory("notes"))
        self.memory_refresh_btn.clicked.connect(self._refresh_memory_panel)
        for button in (self.memory_chat_clear_btn, self.memory_main_clear_btn,
                       self.memory_notes_clear_btn, self.memory_refresh_btn):
            buttons.addWidget(button)
        memory_layout.addLayout(buttons)

        layout = management_tab.layout()
        insert_at = max(0, layout.count() - 1)
        layout.insertWidget(insert_at, stream_group)
        layout.insertWidget(insert_at + 1, memory_group)
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(5000)
        self._stream_timer.timeout.connect(self._refresh_stream_health)
        self._stream_timer.start()
        self._memory_timer = QTimer(self)
        self._memory_timer.setInterval(10000)
        self._memory_timer.timeout.connect(self._refresh_memory_panel)
        self._memory_timer.start()
        QTimer.singleShot(50, self._refresh_stream_health)
        QTimer.singleShot(50, self._refresh_memory_panel)

    def _on_management_review_proposal(self, job_id: str, job_desc: str, draft: str):
        """Handle review proposal request from Management tab."""
        self.proposal_job_id.setText(job_id)
        self.proposal_job_desc.setPlainText(job_desc)
        self.proposal_draft.setPlainText(draft)
        self._review_proposal_draft()

    def _on_management_submit_proposal(self, job_id: str, job_desc: str, draft: str):
        """Handle submit proposal request from Management tab."""
        self.proposal_job_id.setText(job_id)
        self.proposal_job_desc.setPlainText(job_desc)
        self.proposal_draft.setPlainText(draft)
        self._submit_proposal_gui()

    def _on_management_verify_paid(self, opp_id: str, amount: str, wallet: str, ref: str):
        """Handle verify paid request from Management tab."""
        self.pay_opp_id.setText(opp_id)
        self.pay_amount.setText(amount)
        self.pay_wallet.setText(wallet)
        self.pay_ref.setText(ref)
        self._verify_and_mark_paid()


    def create_memory_stream_tab(self):
        """v2.0.34ag (A3): 'Memory & Stream' tab — relocated from Management so the
        Management tab's core controls get room. Contains the Stream Health (G5) panel
        + the per-role Memory panel (F7). Widget names and timers are kept identical
        (self.stream_health_label, self.memory_view, self._stream_timer,
        self._memory_timer) so _refresh_stream_health / _refresh_memory_panel /
        _clear_memory keep working unmodified."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)
        title = QLabel("Memory & Stream")
        title.setStyleSheet(f"font-size:20px;font-weight:bold;color:{self._t('accent')};")
        self._themeable.append((title, "accent", "font-size:20px;font-weight:bold;"))
        lay.addWidget(title)

        # Stream Health (G5)
        streamg = QGroupBox("Stream Health")
        streaml = QFormLayout(streamg)
        streaml.setContentsMargins(12, 12, 12, 12)
        streaml.setVerticalSpacing(6)
        self.stream_health_label = QLabel("Starting…")
        self.stream_health_label.setStyleSheet(f"font-size:11px;color:{self._t('muted')};")
        self._themeable.append((self.stream_health_label, "muted", "font-size:11px;"))
        streaml.addRow(self.stream_health_label)
        lay.addWidget(streamg)
        self._stream_timer = QTimer(self)
        # PERF: 5s interval (was 2s) — stream health changes slowly, no need for 2s
        self._stream_timer.setInterval(5000)
        self._stream_timer.timeout.connect(self._refresh_stream_health)
        self._stream_timer.start()

        # Memory panel (F7)
        memg = QGroupBox("Memory (chat + CEO / long-term)")
        meml = QVBoxLayout(memg)
        meml.setContentsMargins(12, 12, 12, 12)
        meml.setSpacing(6)
        self.memory_view = QTextEdit()
        self.memory_view.setReadOnly(True)
        self.memory_view.setMinimumHeight(120)
        meml.addWidget(self.memory_view, stretch=1)
        mem_btn_row = QHBoxLayout()
        self.memory_chat_clear_btn = QPushButton("Clear Chat memory")
        self.memory_main_clear_btn = QPushButton("Clear CEO memory")
        self.memory_notes_clear_btn = QPushButton("Clear long-term notes")
        self.memory_refresh_btn = QPushButton("Refresh")
        self.memory_chat_clear_btn.clicked.connect(lambda: self._clear_memory("chat"))
        self.memory_main_clear_btn.clicked.connect(lambda: self._clear_memory("main"))
        self.memory_notes_clear_btn.clicked.connect(lambda: self._clear_memory("notes"))
        self.memory_refresh_btn.clicked.connect(self._refresh_memory_panel)
        for b in (self.memory_chat_clear_btn, self.memory_main_clear_btn,
                  self.memory_notes_clear_btn, self.memory_refresh_btn):
            mem_btn_row.addWidget(b)
        meml.addLayout(mem_btn_row)
        lay.addWidget(memg)
        self._memory_timer = QTimer(self)
        # PERF: 10s interval (was 5s) — memory panel is not time-critical
        self._memory_timer.setInterval(10000)
        self._memory_timer.timeout.connect(self._refresh_memory_panel)
        self._memory_timer.start()

        # v2.0.34ao: no trailing addStretch() — the memory panel (stretch=1) now
        # fills the available height so the tab isn't ~60% empty dead space.
        # v2.0.34ak: populate shortly after build (deferred so tab paints first)
        QTimer.singleShot(50, self._refresh_stream_health)
        QTimer.singleShot(50, self._refresh_memory_panel)
        return w


    def create_file_browser_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(f"Root (sandboxed): {self.root_folder}"))
        model = QFileSystemModel()
        model.setRootPath(self.root_folder)
        tree = QTreeView()
        tree.setModel(model)
        tree.setRootIndex(model.index(self.root_folder))
        lay.addWidget(tree)
        return w


    def create_payments_tab(self):
        """Create the Payments tab — wallet management, transactions, and payouts."""
        # Import the full PaymentsTab implementation
        try:
            from gui.payments_tab import PaymentsTab
            tab = PaymentsTab()
            # Expose wallet manager reference for main window integration
            self._payments_tab = tab
            return tab
        except Exception as e:
            # Fallback to simple stub if import fails
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel(f"Wallet: {os.getenv('ATOMIC_SOLANA_ADDRESS', 'Not set')}"))
            self.balance_label = QLabel("Balance: —")
            lay.addWidget(self.balance_label)
            row = QHBoxLayout()
            self.amount_input = QLineEdit("50")
            wb = QPushButton("Withdraw")
            wb.clicked.connect(self.manual_payout)
            row.addWidget(self.amount_input)
            row.addWidget(wb)
            lay.addLayout(row)
            self.history_list = QListWidget()
            lay.addWidget(QLabel("Payout History"))
            lay.addWidget(self.history_list)
            return w


    def create_earnings_tab(self):
        """Earnings dashboard + unified earning center (Paths 1-4)."""
        try:
            from gui.earning_tab import EarningTab
            tab = EarningTab(parent=self)
            self._earning_tab = tab
            return tab
        except Exception as e:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel(f"Earning center unavailable: {e}"))
            return w

    def create_insights_tab(self):
        """Earning Insights dashboard panel (Phase 6)."""
        try:
            from gui.earning_insights import TabAwareInsightsPanel
            from agents.event_logger import StructuredEventLogger
            from agents.approval_queue import HumanApprovalQueue
            from agents.workspace_context import register_component

            panel = TabAwareInsightsPanel(
                parent=self,
                earning_tab=getattr(self, "_earning_tab", None),
                approval_queue=HumanApprovalQueue.instance(),
                event_logger=StructuredEventLogger.instance(),
            )
            self._insights_panel = panel
            register_component("insights", panel)
            return panel
        except Exception as e:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel(f"Insights unavailable: {e}"))
            return w

    def create_approval_tab(self):
        """Human-approval queue panel (Phase 6)."""
        try:
            from gui.approval_panel import ApprovalPanel
            from agents.approval_queue import HumanApprovalQueue

            panel = ApprovalPanel(
                parent=self,
                approval_queue=HumanApprovalQueue.instance(),
            )
            self._approval_panel = panel
            return panel
        except Exception as e:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel(f"Approval queue unavailable: {e}"))
            return w

    def create_logs_tab(self):
        """Live Logs tab with full information display including tokens/sec."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Filter row with severity combo and category filter
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Filter:"))
        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText("Type to filter…")
        self.log_filter.textChanged.connect(self._apply_log_filter)
        frow.addWidget(self.log_filter)

        frow.addWidget(QLabel("Severity:"))
        self.log_severity_combo = QComboBox()
        self.log_severity_combo.addItems(["All", "SUCCESS", "INFO", "WARNING", "ERROR", "BLOCKED"])
        self.log_severity_combo.currentTextChanged.connect(self._apply_log_filter)
        frow.addWidget(self.log_severity_combo)

        frow.addWidget(QLabel("Category:"))
        self.log_category_combo = QComboBox()
        self.log_category_combo.addItems(["All", "System", "LLM", "GPU", "Earning", "Safety", "Provider"])
        self.log_category_combo.currentTextChanged.connect(self._apply_log_filter)
        frow.addWidget(self.log_category_combo)

        auto_scroll_cb = QCheckBox("Auto-scroll")
        auto_scroll_cb.setChecked(True)
        auto_scroll_cb.toggled.connect(self._set_log_auto_scroll)
        self.auto_scroll_logs = auto_scroll_cb
        frow.addWidget(auto_scroll_cb)

        cb = QPushButton("Clear")
        cb.clicked.connect(self._clear_log)
        frow.addWidget(cb)
        lay.addLayout(frow)

        # Table widget for structured log display
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(["Time", "Severity", "Source", "Message", "Tokens/s"])
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setStyleSheet(
            "font-family:Consolas,Monaco,monospace;font-size:11px;"
            "background:#0a0a0f;color:#d4d4d4;"
            "QHeaderView::section { background:#1a1a1f; color:#e0e0e0; }"
        )
        lay.addWidget(self.log_table)
        
        # Replay buffered logs
        self._replay_log_buffer()
        return w


    def create_db_stats_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        title = QLabel("📊 Database & Agent Stats")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #bb86fc; padding: 10px;")
        lay.addWidget(title)

        # Stats grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(8)

        self.db_stat_calls = self._stat_cell("LLM Calls", "0", "#4caf50")
        self.db_stat_errors = self._stat_cell("Errors", "0", "#ff5252")
        self.db_stat_avg_latency = self._stat_cell("Avg Latency", "— ms", "#ff9800")
        self.db_stat_chars = self._stat_cell("Total Chars", "0", "#2196f3")
        self.db_stat_cost = self._stat_cell("Total Cost", "$0.00", "#9c27b0")
        self.db_stat_tokens_sec = self._stat_cell("Avg Tokens/s", "0", "#00bcd4")
        self.db_stat_uptime = self._stat_cell("Uptime", "0h", "#607d8b")
        self.db_stat_db_size = self._stat_cell("DB Size", "0 MB", "#795548")

        stats_grid.addWidget(self.db_stat_calls, 0, 0)
        stats_grid.addWidget(self.db_stat_errors, 0, 1)
        stats_grid.addWidget(self.db_stat_avg_latency, 0, 2)
        stats_grid.addWidget(self.db_stat_chars, 0, 3)
        stats_grid.addWidget(self.db_stat_cost, 1, 0)
        stats_grid.addWidget(self.db_stat_tokens_sec, 1, 1)
        stats_grid.addWidget(self.db_stat_uptime, 1, 2)
        stats_grid.addWidget(self.db_stat_db_size, 1, 3)

        stats_widget = QWidget()
        stats_widget.setLayout(stats_grid)
        lay.addWidget(stats_widget)

        # Provider breakdown
        provider_group = QGroupBox("Provider Breakdown")
        provider_layout = QVBoxLayout(provider_group)
        self.provider_table = QTableWidget()
        self.provider_table.setColumnCount(5)
        self.provider_table.setHorizontalHeaderLabels(["Provider", "Calls", "Errors", "Avg ms", "Tokens/s"])
        self.provider_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.provider_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.provider_table.setMaximumHeight(150)
        provider_layout.addWidget(self.provider_table)
        lay.addWidget(provider_group)

        # Model breakdown
        model_group = QGroupBox("Model Breakdown")
        model_layout = QVBoxLayout(model_group)
        self.model_table = QTableWidget()
        self.model_table.setColumnCount(5)
        self.model_table.setHorizontalHeaderLabels(["Model", "Calls", "Tokens In", "Tokens Out", "Avg Tokens/s"])
        self.model_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.model_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model_table.setMaximumHeight(150)
        model_layout.addWidget(self.model_table)
        lay.addWidget(model_group)

        # Recent LLM calls
        calls_group = QGroupBox("Recent LLM Calls")
        calls_layout = QVBoxLayout(calls_group)
        self.db_calls_table = QTableWidget()
        self.db_calls_table.setColumnCount(7)
        self.db_calls_table.setHorizontalHeaderLabels(["Time", "Provider", "Model", "Tokens In", "Tokens Out", "Cost", "Tokens/s"])
        self.db_calls_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.db_calls_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        calls_layout.addWidget(self.db_calls_table, stretch=1)
        lay.addWidget(calls_group, stretch=1)

        # Event log
        event_group = QGroupBox("Event Log (last 100)")
        event_layout = QVBoxLayout(event_group)
        self.event_table = QTableWidget()
        self.event_table.setColumnCount(4)
        self.event_table.setHorizontalHeaderLabels(["Time", "Type", "Source", "Message"])
        self.event_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.event_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        event_layout.addWidget(self.event_table)
        lay.addWidget(event_group, stretch=1)

        # Refresh button
        btn_row = QHBoxLayout()
        db_refresh_btn = QPushButton("🔄 Refresh Stats")
        db_refresh_btn.clicked.connect(self.refresh_db_stats)
        btn_row.addWidget(db_refresh_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # Keep new calls and events visible without requiring a manual refresh.
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(5000)
        self._stats_timer.timeout.connect(self.refresh_db_stats)
        self._stats_timer.start()
        QTimer.singleShot(0, self.refresh_db_stats)

        return w

    def _stat_cell(self, label: str, value: str, color: str) -> QFrame:
        """Build a bordered KPI card (QFrame) with a label and a value label.

        Returns the frame; callers that need to update the value later can read
        ``frame.value_label`` (set below) and call ``.setText(...)`` on it.
        """
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: #1a1a1a;
                border: 2px solid {color};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setSpacing(2)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888; font-size: 10px; border: none;")
        layout.addWidget(lbl)
        val = QLabel(value)
        val.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold; border: none;")
        val.setAlignment(Qt.AlignCenter)
        layout.addWidget(val)
        # Store reference to value label for updates
        frame.value_label = val
        return frame

    def create_settings_tab(self):
        # v2.0.33: per-provider main/chat role control. Defined up-front so both
        # the LLM Providers group (OpenAI/Anthropic) and the _prov_row helper can
        # use them without a forward-reference error.
        from gui.provider_config_widget import ProviderConfigWidget, CloudProviderPanel, LocalProviderPanel
        
        ROLE_ITEMS = ["Both", "Main only", "Chat only", "Disabled"]

        def _role_from_env(env_prefix):
            if os.getenv(f"DISABLE_{env_prefix}", "false").lower() == "true":
                return "Disabled"
            main_on = os.getenv(f"{env_prefix}_MAIN_ENABLED", "").lower()
            chat_on = os.getenv(f"{env_prefix}_CHAT_ENABLED", "").lower()
            if main_on == "" and chat_on == "":
                return "Both"
            if main_on != "false" and chat_on != "false":
                return "Both"
            if main_on != "false" and chat_on == "false":
                return "Main only"
            if main_on == "false" and chat_on != "false":
                return "Chat only"
            return "Disabled"

        def _env_bool(name, default=False):
            v = os.getenv(name, "").strip().lower()
            if v in ("1", "true", "yes", "on"):
                return True
            if v in ("0", "false", "no", "off"):
                return False
            return default

        def _seed_fx(name, cb):
            cb.blockSignals(True)
            cb.setChecked(_env_bool(f"MRBOT_FX_{name}", True))
            cb.blockSignals(False)

        scroll  = QScrollArea()
        scroll.setWidgetResizable(True)
        inner   = QWidget()
        scroll.setWidget(inner)
        lay     = QVBoxLayout(inner)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        # Provider Configuration (hot-reload, no restart needed)
        # Parent immediately so the provider surface cannot become a separate
        # top-level Qt window while the Settings tab is being assembled.
        provider_config = ProviderConfigWidget(inner)
        provider_config.provider_changed.connect(self._on_provider_widget_changed)
        lay.addWidget(provider_config)

        # Registration
        rg = QGroupBox("Agent Registration")
        rl = QFormLayout(rg)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setVerticalSpacing(8)
        self.name_edit   = QLineEdit(os.getenv("AGENT_NAME", "CodeSelfLearnBot"))
        self.user_edit   = QLineEdit(os.getenv("AGENT_USERNAME", "codeselflearn-2026"))
        self.wallet_edit = QLineEdit(os.getenv("ATOMIC_SOLANA_ADDRESS", ""))
        self.cashapp_edit = QLineEdit(os.getenv("CASHAPP_TAG", ""))
        rl.addRow("Agent Name:",    self.name_edit)
        rl.addRow("Username:",      self.user_edit)
        rl.addRow("Wallet:",        self.wallet_edit)
        rl.addRow("Cash App Tag:",  self.cashapp_edit)
        rb = QPushButton("Register")
        rb.clicked.connect(self.register_autonomous)
        rl.addRow(rb)
        # v2.0.34ag (A5): reuse the top-level status_label (created in __init__).
        if not hasattr(self, "status_label") or self.status_label is None:
            self.status_label = QLabel("Agent status: Not registered")
        self.status_label.setText("Agent status: Not registered")
        rl.addRow(self.status_label)
        lay.addWidget(rg)

        # v2.0.26: providers grouped into CLOUD and LOCAL for clarity.
        # v2.0.32: model field is now a QComboBox (editable) + Fetch button that
        # pulls the provider's models w/ pricing from provider_models.py.
        # v2.0.33: per-provider main/chat role control — a "Role" dropdown
        # (Both / Main only / Chat only / Disabled) replaces the single Disable
        # checkbox, plus a separate "Chat Model:" combo. Fetch populates both.
        # (ROLE_ITEMS / _role_from_env are defined at the top of this method.)
        # v2.0.34an: each provider gets its OWN outlined, collapsible box. The
        # "Hide when disabled" checkbox collapses the box automatically when the
        # provider's Role is "Disabled" (frees screen space for unused providers),
        # and toggles back if you want the API Key + fields visible again. The box
        # itself is object-named "prov-section" so the theme gives it a distinct
        # accent outline (see QSS). Returned self.* attribute names are unchanged
        # so save_settings() keeps working.
        def _prov_row(layout, env_prefix, label, default_base="", default_model="",
                      default_disable="false"):
            """Collapsible provider box. The header (title + "Hide when disabled" +
            collapse button) is ALWAYS visible, so collapsing a disabled provider
            never traps its controls - only the body collapses, the header stays."""
            from PySide6.QtWidgets import (QCheckBox as _CBx, QComboBox as _CB,
                                           QGroupBox as _GB, QHBoxLayout as _HL,
                                           QLabel as _QL, QLineEdit as _LE,
                                           QPushButton as _PB, QVBoxLayout as _VL,
                                           QFormLayout as _FL, QWidget as _W)
            box = _GB(label)
            box.setObjectName("prov-section")
            vbox = _VL(box)
            vbox.setContentsMargins(10, 4, 10, 10)
            vbox.setSpacing(6)

            # ── Always-visible header ────────────────────────────────────────
            header = _W()
            hrow = _HL(header)
            hrow.setContentsMargins(0, 0, 0, 0)
            hrow.setSpacing(8)
            htitle = _QL(label)
            htitle.setStyleSheet(f"font-weight:bold;color:{self._t('accent')};font-size:12px;")
            hrow.addWidget(htitle)
            hrow.addStretch(1)
            hide_cb = _CBx("Hide when disabled")
            hide_cb.setChecked(_env_bool(f"{env_prefix}_HIDE", False))
            hrow.addWidget(hide_cb)
            coll_btn = _PB("\u25be")
            coll_btn.setFixedWidth(26)
            coll_btn.setCheckable(True)
            coll_btn.setChecked(True)
            coll_btn.setToolTip("Collapse / expand provider")
            hrow.addWidget(coll_btn)
            vbox.addWidget(header)

            # ── Collapsible body ────────────────────────────────────────────
            body = _W()
            body_layout = _FL(body)
            body_layout.setContentsMargins(4, 2, 4, 4)
            body_layout.setVerticalSpacing(6)

            key = _LE(os.getenv(f"{env_prefix}_API_KEY", ""))
            key.setEchoMode(_LE.Password)
            base = _LE(os.getenv(f"{env_prefix}_BASE_URL", default_base))
            model_combo = _CB()
            model_combo.setEditable(True)
            model_combo.setMinimumWidth(180)
            if default_model:
                model_combo.addItem(default_model)
            model_combo.setCurrentText(os.getenv(f"{env_prefix}_MODEL", default_model))
            chat_combo = _CB()
            chat_combo.setEditable(True)
            chat_combo.setMinimumWidth(180)
            chat_default = os.getenv(f"{env_prefix}_CHAT_MODEL", "")
            if chat_default:
                chat_combo.addItem(chat_default)
            chat_combo.setCurrentText(chat_default)
            fetch_btn = _PB("Fetch")
            model_row = _W()
            mrow = _HL(model_row)
            mrow.setContentsMargins(0, 0, 0, 0)
            mrow.addWidget(model_combo, stretch=1)
            mrow.addWidget(fetch_btn)
            role_combo = _CB()
            role_combo.addItems(ROLE_ITEMS)
            role_combo.setCurrentText(_role_from_env(env_prefix))

            body_layout.addRow("API Key:", key)
            body_layout.addRow("Base URL:", base)
            body_layout.addRow("Model (main):", model_row)
            body_layout.addRow("Chat Model:", chat_combo)
            body_layout.addRow("Role:", role_combo)
            vbox.addWidget(body)

            layout.addWidget(box)

            fetch_btn.clicked.connect(
                lambda _, p=env_prefix: self._fetch_provider_models(
                    p, [model_combo, chat_combo], key, base))

            def _refresh():
                auto = hide_cb.isChecked() and role_combo.currentText() == "Disabled"
                expanded = (not auto) and coll_btn.isChecked()
                body.setVisible(expanded)
                coll_btn.setText("\u25be" if expanded else "\u25b8")
                box.setVisible(True)
            hide_cb.toggled.connect(lambda *_: _refresh())
            role_combo.currentTextChanged.connect(lambda *_: _refresh())
            coll_btn.toggled.connect(lambda *_: _refresh())
            _refresh()

            return key, base, model_combo, chat_combo, role_combo, fetch_btn, hide_cb
        # ── Cloud Providers ───────────────────────────────────────────────
        cloudg = QGroupBox("Cloud Providers")
        cloudg.setObjectName("prov-section")
        cloudl = QVBoxLayout(cloudg)
        cloudl.setContentsMargins(12, 12, 12, 12)
        cloudl.setSpacing(8)
        # v2.0.34ap (H69) + v2.1: OpenAI / Anthropic are cloud providers, so they
        # live here with the other cloud providers. They now use the SAME
        # collapsible provider-box pattern (_prov_row) as the rest, so they can be
        # hidden/collapsed. self.* attribute names are unchanged so save_settings
        # / test_api_connection keep working.

        # OpenAI
        self.openai_key_edit, self.openai_base_edit, self.openai_model_combo, self.openai_chat_combo, self.openai_role, self.openai_fetch, self.openai_hide = \
            _prov_row(cloudl, "OPENAI", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini")
        openai_note = QLabel("Use for: GPT-4o/4o-mini. Best for general reasoning. Cost: paid per token. Free tier: $10 credit on signup (one-time). Click Fetch to list models + pricing.")
        openai_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((openai_note, "caption", "font-size:10px;padding-top:3px;"))
        openai_note.setWordWrap(True)
        cloudl.addWidget(openai_note)

        # Anthropic
        self.anthropic_key_edit, self.anthropic_base_edit, self.anthropic_model_combo, self.anthropic_chat_combo, self.anthropic_role, self.anthropic_fetch, self.anthropic_hide = \
            _prov_row(cloudl, "ANTHROPIC", "Anthropic", "https://api.anthropic.com/v1", "claude-3-5-sonnet-20241022")
        anthropic_note = QLabel("Use for: Claude Sonnet/Opus. Best for long-context analysis. Cost: paid per token. Free tier: none (paid only). (Anthropic has no models API — Fetch shows a curated list w/ pricing.)")
        anthropic_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((anthropic_note, "caption", "font-size:10px;padding-top:3px;"))
        anthropic_note.setWordWrap(True)
        cloudl.addWidget(anthropic_note)

        # OpenRouter
        self.openrouter_key, self.openrouter_base, self.openrouter_model, self.openrouter_chat, self.openrouter_role, self.openrouter_fetch, self.openrouter_hide = \
            _prov_row(cloudl, "OPENROUTER", "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini")
        self.openrouter_note = QLabel("One key → many models (OpenAI, Anthropic, Google, Meta, Mistral, DeepSeek…). Real per-token pricing. Free tier: $10 signup credit.")
        self.openrouter_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.openrouter_note, "caption", "font-size:10px;padding-top:3px;"))
        self.openrouter_note.setWordWrap(True)
        cloudl.addWidget(self.openrouter_note)

        # Gemini
        self.gemini_key, self.gemini_base, self.gemini_model, self.gemini_chat, self.gemini_role, self.gemini_fetch, self.gemini_hide = \
            _prov_row(cloudl, "GEMINI", "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-1.5-pro")
        self.gemini_note = QLabel("Use for: Gemini 1.5 Pro/Flash. Large context window. Cost: paid per token. Free tier: limited (generous free quota on Google AI Studio).")
        self.gemini_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.gemini_note, "caption", "font-size:10px;padding-top:3px;"))
        self.gemini_note.setWordWrap(True)
        cloudl.addWidget(self.gemini_note)

        # Groq
        self.groq_key, self.groq_base, self.groq_model, self.groq_chat, self.groq_role, self.groq_fetch, self.groq_hide = \
            _prov_row(cloudl, "GROQ", "Groq", "https://api.groq.com/openai/v1", "")
        self.groq_note = QLabel("Use for: Fast inference on open models (Llama, Mixtral, Gemma). Cost: paid per token. Free tier: generous free tier with rate limits.")
        self.groq_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.groq_note, "caption", "font-size:10px;padding-top:3px;"))
        self.groq_note.setWordWrap(True)
        cloudl.addWidget(self.groq_note)

        # DeepSeek
        self.deepseek_key, self.deepseek_base, self.deepseek_model, self.deepseek_chat, self.deepseek_role, self.deepseek_fetch, self.deepseek_hide = \
            _prov_row(cloudl, "DEEPSEEK", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat")
        self.deepseek_note = QLabel("Use for: DeepSeek-Chat/Reasoner. Competitive pricing, good reasoning. Cost: paid per token. Free tier: limited daily quota.")
        self.deepseek_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.deepseek_note, "caption", "font-size:10px;padding-top:3px;"))
        self.deepseek_note.setWordWrap(True)
        cloudl.addWidget(self.deepseek_note)

        # Mistral
        self.mistral_key, self.mistral_base, self.mistral_model, self.mistral_chat, self.mistral_role, self.mistral_fetch, self.mistral_hide = \
            _prov_row(cloudl, "MISTRAL", "Mistral", "https://api.mistral.ai/v1", "")
        self.mistral_note = QLabel("Use for: Mistral Large/Small. Cost: paid per token. Free tier: limited (La Plateforme has free tier with rate limits).")
        self.mistral_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.mistral_note, "caption", "font-size:10px;padding-top:3px;"))
        self.mistral_note.setWordWrap(True)
        cloudl.addWidget(self.mistral_note)

        # Together
        self.together_key, self.together_base, self.together_model, self.together_chat, self.together_role, self.together_fetch, self.together_hide = \
            _prov_row(cloudl, "TOGETHER", "Together", "https://api.together.xyz/v1", "")
        self.together_note = QLabel("Use for: Many open models (Llama, DeepSeek, Mistral, Falcon…). Cost: paid per token. Free tier: $100 credit on signup.")
        self.together_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.together_note, "caption", "font-size:10px;padding-top:3px;"))
        self.together_note.setWordWrap(True)
        cloudl.addWidget(self.together_note)

        # NVIDIA NIM
        self.nvidia_key, self.nvidia_base, self.nvidia_model, self.nvidia_chat, self.nvidia_role, self.nvidia_fetch, self.nvidia_hide = \
            _prov_row(cloudl, "NVIDIA", "NVIDIA (NIM)", "https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3.5-lightning-30b-a3b")
        self.nvidia_note = QLabel("Use for: NVIDIA NIM models (Nemotron, Llama, Qwen, DeepSeek…). Cost: FREE on build.nvidia.com (rate-limited). No API key needed for free tier.")
        self.nvidia_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.nvidia_note, "caption", "font-size:10px;padding-top:3px;"))
        self.nvidia_note.setWordWrap(True)
        cloudl.addWidget(self.nvidia_note)
        # ProviderConfigWidget above is the single visible provider surface.
        # Keep these controls constructed for existing save/fetch code, but do
        # not render a second copy of the provider list.

        # ── Local Providers (OpenAI-compatible local servers) ──────────────
        localg = QGroupBox("Local Providers")
        localg.setObjectName("prov-section")
        locall = QVBoxLayout(localg)
        locall.setContentsMargins(12, 12, 12, 12)
        locall.setSpacing(8)
        self.vllm_key, self.vllm_base, self.vllm_model, self.vllm_chat, self.vllm_role, self.vllm_fetch, self.vllm_hide = \
            _prov_row(locall, "VLLM", "vLLM", "", "")
        self.lmstudio_key, self.lmstudio_base, self.lmstudio_model, self.lmstudio_chat, self.lmstudio_role, self.lmstudio_fetch, self.lmstudio_hide = \
            _prov_row(locall, "LM_STUDIO", "LM Studio", "", "")
        self.koboldcpp_key, self.koboldcpp_base, self.koboldcpp_model, self.koboldcpp_chat, self.koboldcpp_role, self.koboldcpp_fetch, self.koboldcpp_hide = \
            _prov_row(locall, "KOBOLDCPP", "KoboldCpp", "", "")

        # llama.cpp is a local provider too, but its two role-specific servers
        # are controlled by the Providers & GPU tab rather than generic rows.
        llamacppg = QGroupBox("llama.cpp (local dual-brain)")
        llamacppl = QFormLayout(llamacppg)
        llamacppl.setContentsMargins(12, 12, 12, 12)
        self.llamacpp_big_enabled = QCheckBox("Enabled")
        self.llamacpp_big_enabled.setChecked(_env_bool("BIG_BRAIN_ENABLED", True))
        llamacppl.addRow("Edward / Big Brain:", self.llamacpp_big_enabled)
        self.llamacpp_small_enabled = QCheckBox("Enabled")
        self.llamacpp_small_enabled.setChecked(_env_bool("SMALL_BRAIN_ENABLED", True))
        llamacppl.addRow("Jacob / Small Brain:", self.llamacpp_small_enabled)
        llamacpp_note = QLabel(
            "Uses the llama-server processes configured in Providers & GPU. "
            "Enable at least one role, then start that brain there. Other local "
            "and cloud providers remain available through their role settings.")
        llamacpp_note.setWordWrap(True)
        llamacpp_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((llamacpp_note, "caption", "font-size:10px;padding-top:3px;"))
        llamacppl.addRow(llamacpp_note)

        # Ollama Local (foundational local provider) — wrapped in its own outlined
        # prov-section box inside "LLM Providers", with a "Hide when disabled" toggle
        # like the other providers (v2.0.34an).
        ollama_box = QGroupBox("Ollama (local)")
        ollama_box.setObjectName("prov-section")
        ollama_vbox = QVBoxLayout(ollama_box)
        ollama_vbox.setContentsMargins(10, 4, 10, 10)
        ollama_vbox.setSpacing(6)
        ollama_header = QWidget()
        ollama_header_lay = QHBoxLayout(ollama_header)
        ollama_header_lay.setContentsMargins(0, 0, 0, 0)
        ollama_header_lay.setSpacing(8)
        ollama_htitle = QLabel("Ollama (local)")
        ollama_htitle.setStyleSheet(f"font-weight:bold;color:{self._t('accent')};font-size:12px;")
        ollama_header_lay.addWidget(ollama_htitle)
        ollama_header_lay.addStretch(1)
        self.ollama_hide = QCheckBox("Hide when disabled")
        self.ollama_hide.setChecked(_env_bool("OLLAMA_HIDE", False))
        ollama_header_lay.addWidget(self.ollama_hide)
        ollama_coll = QPushButton("\u25be")
        ollama_coll.setFixedWidth(26)
        ollama_coll.setCheckable(True)
        ollama_coll.setChecked(True)
        ollama_coll.setToolTip("Collapse / expand provider")
        ollama_header_lay.addWidget(ollama_coll)
        ollama_vbox.addWidget(ollama_header)
        ollama_body = QWidget()
        ollama_box_layout = QFormLayout(ollama_body)
        ollama_box_layout.setContentsMargins(4, 2, 4, 4)
        ollama_box_layout.setVerticalSpacing(6)
        ollama_row = QWidget()
        ollama_layout = QHBoxLayout(ollama_row)
        ollama_layout.setContentsMargins(0, 0, 0, 0)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        # Populate from live Ollama on first build so the dropdown reflects
        # what's actually installed, not a hardcoded guess. Use a set to avoid
        # duplicates: we add live names, fallback defaults, AND worker names
        # (which may overlap with the live names above).
        seen = set()
        def _add_unique(combo, names):
            for nm in names:
                if nm and nm not in seen:
                    seen.add(nm)
                    combo.addItem(nm)
        try:
            from agents.base_worker import WorkerAgent
            names = WorkerAgent._ollama_model_names_static()
            _add_unique(self.ollama_model_combo, names or [])
        except Exception:
            pass
        # Fallback: add common defaults if live query returned nothing.
        if self.ollama_model_combo.count() == 0:
            _add_unique(self.ollama_model_combo, [
                "llama3.2", "llama3:8b", "llama3:70b", "mistral", "codellama",
                "qwen2.5:0.5b", "qwen2.5:1.5b", "qwen2.5:3b", "phi3:mini", "gemma2:2b",
            ])
        # Default selection reflects the LIVE chosen model (override) so the combo
        # shows what's actually active; env value is the fallback seed. The dropdown
        # is silently re-populated from locally-found models at startup via
        # populate_ollama_model_combos() (ease of switching).
        _active_main = getattr(self.worker, "_ollama_model_override", None) \
            or os.getenv("OLLAMA_MODEL", "llama3.2")
        self.ollama_model_combo.setCurrentText(_active_main)
        self.ollama_chat_model_combo = QComboBox()
        self.ollama_chat_model_combo.setEditable(True)
        _active_chat = getattr(self.worker, "_chat_ollama_model_override", None) \
            or os.getenv("OLLAMA_CHAT_MODEL", "")
        self.ollama_chat_model_combo.setCurrentText(_active_chat)
        self.refresh_chat_model_btn = QPushButton("Refresh")
        self.refresh_chat_model_btn.clicked.connect(self.refresh_ollama_models)
        ollama_chat_row = QWidget()
        ollama_chat_layout = QHBoxLayout(ollama_chat_row)
        ollama_chat_layout.setContentsMargins(0, 0, 0, 0)
        ollama_chat_layout.addWidget(self.ollama_chat_model_combo)
        ollama_chat_layout.addWidget(self.refresh_chat_model_btn)
        self.refresh_ollama_btn = QPushButton("Refresh")
        self.refresh_ollama_btn.clicked.connect(self.refresh_ollama_models)
        ollama_layout.addWidget(self.ollama_model_combo)
        ollama_layout.addWidget(self.refresh_ollama_btn)
        self.ollama_role = QComboBox()
        self.ollama_role.addItems(ROLE_ITEMS)
        self.ollama_role.setCurrentText(_role_from_env("OLLAMA"))
        ollama_box_layout.addRow("Ollama Main Model:", ollama_row)
        ollama_box_layout.addRow("Ollama Chat Model:", ollama_chat_row)
        ollama_box_layout.addRow("Ollama Role:", self.ollama_role)
        # v2.0.34ag (A2): per-role GPU offload controls moved to the "Model & GPU" tab.
        ollama_note = QLabel("Use for: Local private inference. Best for offline/cheap. Cost: free, uses local GPU/CPU.")
        ollama_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((ollama_note, "caption", "font-size:10px;padding-top:3px;"))
        ollama_note.setWordWrap(True)
        ollama_box_layout.addRow(ollama_note)
        ollama_vbox.addWidget(ollama_body)

        def _ollama_refresh():
            # This legacy control block is retained only for save/load
            # compatibility. ProviderConfigWidget is the visible Settings
            # surface; showing this unattached box creates a second top-level
            # window titled "python".
            ollama_box.hide()
        self.ollama_hide.toggled.connect(lambda *_: _ollama_refresh())
        self.ollama_role.currentTextChanged.connect(lambda *_: _ollama_refresh())
        ollama_coll.toggled.connect(lambda *_: _ollama_refresh())
        _ollama_refresh()


        tb = QPushButton("Test Connection")
        tb.clicked.connect(self.test_api_connection)
        lay.addWidget(tb)

        # v2.0.34ag (A2): LLM Parameters + Model Info moved to the "Model & GPU" tab.
        perfg = QGroupBox("Performance & Cache")
        perfl = QFormLayout(perfg)
        perfl.setContentsMargins(12, 12, 12, 12)
        perfl.setVerticalSpacing(8)
        self.polling_spin = QSpinBox()
        self.polling_spin.setRange(10, 3600)
        self.polling_spin.setValue(self.manager.HEARTBEAT_INTERVAL)
        self.polling_spin.setSuffix(" s")
        perfl.addRow("Heartbeat Interval:", self.polling_spin)
        heartbeat_note = QLabel("How often the manager thinks/acts when idle. Discovery runs every 5 heartbeats independently. When work is queued, it's processed immediately without an LLM call — the LLM is only needed when deciding strategy, not for routine dispatch.")
        heartbeat_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((heartbeat_note, "caption", "font-size:10px;padding-top:3px;"))
        heartbeat_note.setWordWrap(True)
        perfl.addRow(heartbeat_note)

        self.idle_cooldown_spin = QSpinBox()
        self.idle_cooldown_spin.setRange(60, 3600)
        self.idle_cooldown_spin.setValue(int(os.getenv("IDLE_HEARTBEAT_COOLDOWN", 600)))
        self.idle_cooldown_spin.setSuffix(" s")
        perfl.addRow("Idle LLM cooldown:", self.idle_cooldown_spin)
        idle_note = QLabel("LLM heartbeat only fires when idle for this long. Queued work is processed immediately without the LLM. Higher = fewer LLM calls when no work is pending.")
        idle_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((idle_note, "caption", "font-size:10px;padding-top:3px;"))
        idle_note.setWordWrap(True)
        perfl.addRow(idle_note)

        self.startup_spin = QSpinBox()
        self.startup_spin.setRange(0, 60)
        self.startup_spin.setValue(int(os.getenv("STARTUP_DELAY_SECS", 5)))
        self.startup_spin.setSuffix(" s")
        perfl.addRow("Startup Delay:", self.startup_spin)
        startup_note = QLabel("Delay before agents start. Useful if you need to start Ollama first.")
        startup_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((startup_note, "caption", "font-size:10px;padding-top:3px;"))
        startup_note.setWordWrap(True)
        perfl.addRow(startup_note)

        self.research_cache_ttl_spin = QSpinBox()
        self.research_cache_ttl_spin.setRange(0, 3600)
        self.research_cache_ttl_spin.setValue(int(os.getenv("RESEARCH_CACHE_TTL", 120)))
        self.research_cache_ttl_spin.setSuffix(" s")
        perfl.addRow("Research Cache TTL:", self.research_cache_ttl_spin)
        cache_note = QLabel("How long file scans are cached. Lower = fresher data but slower scans.")
        cache_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((cache_note, "caption", "font-size:10px;padding-top:3px;"))
        cache_note.setWordWrap(True)
        perfl.addRow(cache_note)

        self.max_file_spin = QSpinBox()
        self.max_file_spin.setRange(1, 500)
        self.max_file_spin.setValue(int(os.getenv("MAX_FILE_SIZE_MB", 10)))
        perfl.addRow("Max File Size (MB):", self.max_file_spin)
        file_size_note = QLabel("Skip files larger than this when scanning. Lower = faster scans.")
        file_size_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((file_size_note, "caption", "font-size:10px;padding-top:3px;"))
        file_size_note.setWordWrap(True)
        perfl.addRow(file_size_note)

        self.research_max_chars = QSpinBox()
        self.research_max_chars.setRange(500, 20000)
        self.research_max_chars.setValue(int(os.getenv("RESEARCH_MAX_CHARS", 3000)))
        self.research_max_chars.setSuffix(" chars")
        perfl.addRow("Research chars/file:", self.research_max_chars)
        research_chars_note = QLabel("Max chars read per file during research scans. Higher = more context but slower.")
        research_chars_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((research_chars_note, "caption", "font-size:10px;padding-top:3px;"))
        research_chars_note.setWordWrap(True)
        perfl.addRow(research_chars_note)

        self.deep_read_chars = QSpinBox()
        self.deep_read_chars.setRange(1000, 50000)
        self.deep_read_chars.setValue(int(os.getenv("DEEP_READ_MAX_CHARS", 8000)))
        self.deep_read_chars.setSuffix(" chars")
        perfl.addRow("Deep read chars/file:", self.deep_read_chars)
        deep_read_note = QLabel("Max chars for deep file analysis. Higher = more thorough but much slower.")
        deep_read_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((deep_read_note, "caption", "font-size:10px;padding-top:3px;"))
        deep_read_note.setWordWrap(True)
        perfl.addRow(deep_read_note)

        self.auto_research = QCheckBox()
        self.auto_research.setChecked(
            os.getenv("AUTO_RESEARCH", "False").lower() == "true")
        perfl.addRow("Auto-scan on start:", self.auto_research)
        auto_research_note = QLabel("Automatically scan files when program starts.")
        auto_research_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((auto_research_note, "caption", "font-size:10px;padding-top:3px;"))
        auto_research_note.setWordWrap(True)
        perfl.addRow(auto_research_note)
        lay.addWidget(perfg)

        # ── LLM Parameters (relocated from the removed "Model & GPU" tab) ──
        # Generic LLM controls that are still relevant with llama.cpp as the
        # default provider. Widget names are kept identical so save_settings and
        # _refresh_model_info keep working unmodified (v2.0.36w).
        llmg = QGroupBox("LLM Parameters")
        llml = QFormLayout(llmg)
        llml.setContentsMargins(12, 12, 12, 12)
        llml.setVerticalSpacing(8)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(128, 8192)
        self.max_tokens_spin.setValue(int(os.getenv("MAX_TOKENS", 1024)))
        llml.addRow("Max Tokens:", self.max_tokens_spin)
        max_tokens_note = QLabel("Maximum length of generated responses. Higher = longer answers but slower.")
        max_tokens_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((max_tokens_note, "caption", "font-size:10px;padding-top:3px;"))
        max_tokens_note.setWordWrap(True)
        llml.addRow(max_tokens_note)
        self.llm_budget_edit = QLineEdit()
        self.llm_budget_edit.setPlaceholderText("0 = off (no cap)")
        self.llm_budget_edit.setText(os.getenv("LLM_DAILY_BUDGET_USD", "0"))
        self.llm_budget_edit.textChanged.connect(self._apply_llm_budget)
        llml.addRow("Daily LLM budget (USD):", self.llm_budget_edit)
        budget_note = QLabel("A4: hard daily cloud-LLM spend cap. When exceeded, billable providers are skipped and the bot falls back to the free/local model. 0 disables the cap.")
        budget_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((budget_note, "caption", "font-size:10px;padding-top:3px;"))
        budget_note.setWordWrap(True)
        llml.addRow(budget_note)
        self.winrate_edit = QLineEdit()
        self.winrate_edit.setPlaceholderText("0 = never auto-decline")
        self.winrate_edit.setText(os.getenv("WINRATE_DECLINE_BELOW", "20"))
        self.winrate_edit.textChanged.connect(self._apply_winrate)
        llml.addRow("Auto-decline if win-rate < (%):", self.winrate_edit)
        winrate_note = QLabel("A5: win-rate feedback loop. Jobs are auto-declined if a platform's success rate is below this threshold. Cold-start safe (no data = no decline).")
        winrate_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((winrate_note, "caption", "font-size:10px;padding-top:3px;"))
        winrate_note.setWordWrap(True)
        llml.addRow(winrate_note)
        lay.addWidget(llmg)

        # ── Model Info (relocated from the removed "Model & GPU" tab) ──
        infog = QGroupBox("Model Info")
        infol = QFormLayout(infog)
        infol.setContentsMargins(12, 12, 12, 12)
        infol.setVerticalSpacing(6)
        self.model_info_browser = QTextEdit()
        self.model_info_browser.setMinimumHeight(90)
        self.model_info_browser.setMaximumHeight(130)
        self.model_info_browser.setReadOnly(True)
        infol.addRow(self.model_info_browser)
        self.refresh_model_info_btn = QPushButton("Refresh Model Info")
        self.refresh_model_info_btn.clicked.connect(
            lambda: self._refresh_model_info(live=True))
        infol.addRow(self.refresh_model_info_btn)
        info_note = QLabel(
            "Shows the type of each selected model: dense vs Mixture-of-Experts (MoE), "
            "approximate parameter count, context window, and price.")
        info_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((info_note, "caption", "font-size:10px;padding-top:3px;"))
        info_note.setWordWrap(True)
        infol.addRow(info_note)
        lay.addWidget(infog)
        # PERF: defer model info refresh to avoid blocking tab paint
        QTimer.singleShot(100, lambda: self._refresh_model_info(live=False))

        # Security Settings with explanations
        secg = QGroupBox("Security")
        secl = QFormLayout(secg)
        secl.setContentsMargins(12, 12, 12, 12)
        secl.setVerticalSpacing(8)
        self.blocklist_edit = QLineEdit(os.getenv("FILENAME_BLOCKLIST",
            "config.yaml,.env,credentials.json,id_rsa"))
        secl.addRow("Blocklist (comma sep):", self.blocklist_edit)
        blocklist_note = QLabel("Files the agent will never read. Keeps secrets safe.")
        blocklist_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((blocklist_note, "caption", "font-size:10px;padding-top:3px;"))
        blocklist_note.setWordWrap(True)
        secl.addRow(blocklist_note)

        self.blocked_mime_edit = QLineEdit(os.getenv("BLOCKED_MIME_TYPES",
            "application/x-executable,application/x-sharedlib"))
        secl.addRow("Blocked MIME (comma):", self.blocked_mime_edit)
        mime_note = QLabel("Blocked file types. Prevents reading binaries or executables.")
        mime_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((mime_note, "caption", "font-size:10px;padding-top:3px;"))
        mime_note.setWordWrap(True)
        secl.addRow(mime_note)
        lay.addWidget(secg)

        # Action Pipeline with explanations
        pipeg = QGroupBox("Action Pipeline")
        pipel = QFormLayout(pipeg)
        pipel.setContentsMargins(12, 12, 12, 12)
        pipel.setVerticalSpacing(8)

        self.pipeline_enabled_check = QCheckBox()
        self.pipeline_enabled_check.setChecked(
            os.getenv("PIPELINE_ENABLED", "true").lower() == "true")
        pipel.addRow("Enable validation pipeline:", self.pipeline_enabled_check)
        pipeline_enabled_note = QLabel("Run code through validation before writing to disk.")
        pipeline_enabled_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((pipeline_enabled_note, "caption", "font-size:10px;padding-top:3px;"))
        pipeline_enabled_note.setWordWrap(True)
        pipel.addRow(pipeline_enabled_note)

        self.pipeline_allow_write_check = QCheckBox()
        self.pipeline_allow_write_check.setChecked(
            os.getenv("PIPELINE_ALLOW_WRITE", "true").lower() == "true")
        pipel.addRow("Allow file write/create:", self.pipeline_allow_write_check)

        self.pipeline_allow_selfimprove_check = QCheckBox()
        self.pipeline_allow_selfimprove_check.setChecked(
            os.getenv("PIPELINE_ALLOW_SELF_IMPROVE", "false").lower() == "true")
        pipel.addRow("Allow self-improvement:", self.pipeline_allow_selfimprove_check)
        for _name, _check in (
            ("PIPELINE_ENABLED", self.pipeline_enabled_check),
            ("PIPELINE_ALLOW_WRITE", self.pipeline_allow_write_check),
            ("PIPELINE_ALLOW_SELF_IMPROVE", self.pipeline_allow_selfimprove_check),
        ):
            _check.stateChanged.connect(
                lambda state, name=_name: os.environ.__setitem__(
                    name, str(bool(state)).lower()))
        self_improve_note = QLabel("Allow the agent to modify its own code. Only enable if you trust the validation pipeline.")
        self_improve_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self_improve_note, "caption", "font-size:10px;padding-top:3px;"))
        self_improve_note.setWordWrap(True)
        pipel.addRow(self_improve_note)

        pipe_val_btn = QPushButton("🔍 Validate Clipboard Code")
        pipe_val_btn.clicked.connect(self._validate_clipboard_code)
        pipel.addRow(pipe_val_btn)

        self.pipeline_result_label = QLabel("")
        self.pipeline_result_label.setWordWrap(True)
        self.pipeline_result_label.setStyleSheet("font-size:10px;")
        pipel.addRow(self.pipeline_result_label)
        lay.addWidget(pipeg)

        # Payout Settings with explanations
        payg = QGroupBox("Payout Destinations")
        payl = QFormLayout(payg)
        payl.setContentsMargins(12, 12, 12, 12)
        payl.setVerticalSpacing(8)
        self.cashapp_edit = QLineEdit(os.getenv("CASHAPP_TAG", "$csmith7899"))
        payl.addRow("Cash App tag:", self.cashapp_edit)
        self.solana_payout_edit = QLineEdit(
            os.getenv("ATOMIC_SOLANA_ADDRESS", ""))
        payl.addRow("Solana address:", self.solana_payout_edit)
        payout_note = QLabel("Auto-payout: agent earnings route to Cash App first, then Solana wallet for on-chain storage.")
        payout_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((payout_note, "caption", "font-size:10px;padding-top:3px;"))
        payout_note.setWordWrap(True)
        payl.addRow(payout_note)
        lay.addWidget(payg)

        # Appearance (v2.0.26: customizable theme coloring + effects toggles)
        apg = QGroupBox("Appearance")
        apl = QFormLayout(apg)
        apl.setContentsMargins(12, 12, 12, 12)
        apl.setVerticalSpacing(8)
        theme_combo = QComboBox()
        theme_combo.addItems(self.THEMES.keys())
        _th = os.getenv("MRBOT_THEME", "Dark")
        theme_combo.setCurrentText(_th if _th in self.THEMES else "Dark")
        self.theme_combo = theme_combo
        theme_combo.currentTextChanged.connect(self.apply_theme)
        apl.addRow("Theme:", theme_combo)

        customize_btn = QPushButton("Customize colors…")
        customize_btn.clicked.connect(
            lambda: self._open_theme_customizer(theme_combo.currentText()))
        apl.addRow(customize_btn)

        # Effects toggles (perf vs quality)
        self.fx_antialias = QCheckBox(); _seed_fx("ANTIALIASING", self.fx_antialias)
        self.fx_shadows = QCheckBox(); _seed_fx("SOFT_SHADOWS", self.fx_shadows)
        self.fx_glow = QCheckBox(); _seed_fx("HOVER_GLOW", self.fx_glow)
        self.fx_trans = QCheckBox(); _seed_fx("TRANSITIONS", self.fx_trans)
        self.fx_anim = QCheckBox(); _seed_fx("ANIMATIONS", self.fx_anim)
        apl.addRow("Antialiasing:", self.fx_antialias)
        apl.addRow("Soft shadows:", self.fx_shadows)
        apl.addRow("Hover glow:", self.fx_glow)
        apl.addRow("Transitions:", self.fx_trans)
        apl.addRow("Animations:", self.fx_anim)
        self.fx_quality = QComboBox()
        self.fx_quality.addItems(["Quality", "Performance"])
        self.fx_quality.setCurrentText(os.getenv("MRBOT_FX_QUALITY", "Quality"))
        apl.addRow("Render mode:", self.fx_quality)
        # v2.0.34ap (H67): richer quality controls — a 4-step render-quality
        # preset (scales shadow strength/blur) plus discrete layout toggles.
        self.fx_render_quality = QComboBox()
        self.fx_render_quality.addItems(["Low", "Medium", "High", "Ultra"])
        self.fx_render_quality.setCurrentText(
            os.getenv("MRBOT_FX_RENDER_QUALITY", "High"))
        apl.addRow("Render quality:", self.fx_render_quality)
        self.fx_compact = QCheckBox()
        self.fx_compact.setChecked(
            os.getenv("MRBOT_FX_COMPACT_DENSITY", "false").lower() == "true")
        apl.addRow("Compact density:", self.fx_compact)
        self.fx_rounded = QCheckBox()
        self.fx_rounded.setChecked(
            os.getenv("MRBOT_FX_ROUNDED_CORNERS", "true").lower() != "false")
        apl.addRow("Rounded corners:", self.fx_rounded)
        self.fx_button_style = QComboBox()
        self.fx_button_style.addItems(["2.5D (beveled)", "2D (flat)"])
        _bst = os.getenv("MRBOT_FX_BUTTON_STYLE", "2.5D (beveled)")
        self.fx_button_style.setCurrentText(
            _bst if _bst in ("2.5D (beveled)", "2D (flat)") else "2.5D (beveled)")
        apl.addRow("Button style:", self.fx_button_style)
        bstyle_note = QLabel("2.5D = raised bevel (gradient + accent edge). 2D = flat surface. Pair with Soft shadows for depth.")
        bstyle_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:2px;")
        self._themeable.append((bstyle_note, "caption", "font-size:10px;padding-top:2px;"))
        bstyle_note.setWordWrap(True)
        apl.addRow(bstyle_note)
        for _cb in (self.fx_antialias, self.fx_shadows, self.fx_glow,
                    self.fx_trans, self.fx_anim, self.fx_compact, self.fx_rounded):
            _cb.stateChanged.connect(lambda *_: self._apply_effects_now())
        self.fx_quality.currentTextChanged.connect(lambda *_: self._apply_effects_now())
        self.fx_render_quality.currentTextChanged.connect(lambda *_: self._apply_effects_now())
        self.fx_button_style.currentTextChanged.connect(lambda *_: self._apply_effects_now())
        lay.addWidget(apg)

        # Cache Management
        cg = QGroupBox("Cache Management")
        cl = QVBoxLayout(cg)
        ccb = QPushButton("Clear File Cache")
        ccb.clicked.connect(self.clear_file_cache)
        cl.addWidget(ccb)
        lay.addWidget(cg)

        sb = QPushButton("💾 Save All Settings")
        sb.clicked.connect(self.save_settings)
        lay.addWidget(sb)

        lay.addStretch()
        return scroll

    def create_opportunities_tab(self):
        """Create the Opportunities tab — browse, search, and manage discovered opportunities."""
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
        from PySide6.QtCore import QTimer
        from agents.opportunity_portfolio import OpportunityPortfolio
        from agents.workspace_context import register_component

        portfolio_path = os.path.join(
            os.path.expanduser("~"), ".mrbot1000", "opportunities.db")
        self.opportunity_portfolio = OpportunityPortfolio(portfolio_path)
        register_component("opportunity_portfolio", self.opportunity_portfolio)
        
        w = QWidget()
        lay = QVBoxLayout(w)
        
        # Header
        header = QLabel("🔍 Opportunities")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        lay.addWidget(header)
        
        # Controls row
        controls = QHBoxLayout()
        
        self.opp_scan_btn = QPushButton("▶ Scan Now")
        self.opp_scan_btn.clicked.connect(self._on_scan_opportunities)
        controls.addWidget(self.opp_scan_btn)
        
        self.opp_auto_scan_cb = QCheckBox("Auto-scan")
        self.opp_auto_scan_cb.setChecked(False)
        self.opp_auto_scan_cb.toggled.connect(self._configure_opportunity_auto_scan)
        controls.addWidget(self.opp_auto_scan_cb)
        
        self.opp_scan_interval_spin = QSpinBox()
        self.opp_scan_interval_spin.setRange(1, 60)
        self.opp_scan_interval_spin.setValue(5)
        self.opp_scan_interval_spin.setSuffix(" min")
        self.opp_scan_interval_spin.valueChanged.connect(
            lambda _value: self._configure_opportunity_auto_scan(
                self.opp_auto_scan_cb.isChecked()))
        controls.addWidget(QLabel("Interval:"))
        controls.addWidget(self.opp_scan_interval_spin)
        
        self.opp_source_combo = QComboBox()
        self.opp_source_combo.addItems(["all", "upwork", "fiverr", "github", "prolific"])
        controls.addWidget(QLabel("Source:"))
        controls.addWidget(self.opp_source_combo)
        
        self.opp_min_score_spin = QSpinBox()
        self.opp_min_score_spin.setRange(0, 100)
        self.opp_min_score_spin.setValue(50)
        self.opp_min_score_spin.setSuffix("%")
        controls.addWidget(QLabel("Min Score:"))
        controls.addWidget(self.opp_min_score_spin)
        
        controls.addStretch()
        lay.addLayout(controls)
        
        # Opportunities table
        self.opp_table = QTableWidget()
        self.opp_table.setColumnCount(7)
        self.opp_table.setHorizontalHeaderLabels(["Title", "Source", "Category", "Budget", "Score", "Status", "URL"])
        self.opp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.opp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.opp_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.opp_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.opp_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.opp_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.opp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.opp_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        lay.addWidget(self.opp_table)
        
        # Action buttons
        action_row = QHBoxLayout()
        
        self.opp_research_btn = QPushButton("🔬 Research")
        self.opp_research_btn.clicked.connect(self._on_research_opportunity)
        action_row.addWidget(self.opp_research_btn)
        
        self.opp_apply_btn = QPushButton("📝 Apply")
        self.opp_apply_btn.clicked.connect(self._on_apply_opportunity)
        action_row.addWidget(self.opp_apply_btn)
        
        self.opp_reject_btn = QPushButton("❌ Reject")
        self.opp_reject_btn.clicked.connect(self._on_reject_opportunity)
        action_row.addWidget(self.opp_reject_btn)
        
        action_row.addStretch()
        lay.addLayout(action_row)
        
        # Status
        self.opp_status_label = QLabel("Ready")
        lay.addWidget(self.opp_status_label)
        
        # Refresh timer
        self.opp_refresh_timer = QTimer()
        self.opp_refresh_timer.timeout.connect(self._refresh_opportunities)
        self.opp_refresh_timer.start(30000)  # 30s
        self.opp_scan_timer = QTimer()
        self.opp_scan_timer.timeout.connect(self._on_scan_opportunities)
        self._refresh_opportunities()
        
        return w
    
    def create_paper_trading_tab(self):
        """Create the Paper Trading tab — virtual portfolio and strategy testing."""
        from PySide6.QtWidgets import (
            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
            QDoubleSpinBox,
        )
        from PySide6.QtCore import QTimer
        from agents.paper_trading import PaperTradingEngine
        from agents.workspace_context import register_component

        self.paper_engine = PaperTradingEngine()
        register_component("paper_trading", self.paper_engine)
        
        w = QWidget()
        lay = QVBoxLayout(w)
        
        # Header
        header = QLabel("📈 Paper Trading")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        lay.addWidget(header)
        
        # Portfolio summary
        summary_group = QGroupBox("Virtual Portfolio Summary")
        summary_lay = QFormLayout(summary_group)
        
        self.paper_equity_label = QLabel("$10,000.00")
        self.paper_equity_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #00ff88;")
        summary_lay.addRow("Simulated Equity:", self.paper_equity_label)
        
        self.paper_cash_label = QLabel("$10,000.00")
        self.paper_cash_label.setStyleSheet("font-size: 12pt; color: #88aaff;")
        summary_lay.addRow("Virtual Cash:", self.paper_cash_label)
        
        self.paper_return_label = QLabel("0.00%")
        self.paper_return_label.setStyleSheet("font-size: 12pt; color: #00ff88;")
        summary_lay.addRow("Total Return:", self.paper_return_label)
        
        self.paper_sharpe_label = QLabel("0.00")
        self.paper_sharpe_label.setStyleSheet("font-size: 12pt; color: #ffcc44;")
        summary_lay.addRow("Sharpe Ratio:", self.paper_sharpe_label)
        
        self.paper_drawdown_label = QLabel("0.00%")
        self.paper_drawdown_label.setStyleSheet("font-size: 12pt; color: #ff5555;")
        summary_lay.addRow("Max Drawdown:", self.paper_drawdown_label)
        
        self.paper_trades_label = QLabel("0")
        self.paper_trades_label.setStyleSheet("font-size: 12pt; color: #aaaaaa;")
        summary_lay.addRow("Total Trades:", self.paper_trades_label)
        
        lay.addWidget(summary_group)
        lay.addWidget(QLabel(
            "Simulation only: no bank, broker, wallet, exchange, or live order connection. "
            "Prices are entered manually for paper testing."
        ))
        
        # Order entry
        order_group = QGroupBox("Place Order")
        order_lay = QFormLayout(order_group)
        
        self.paper_symbol_edit = QLineEdit()
        self.paper_symbol_edit.setPlaceholderText("Symbol (e.g., AAPL)")
        order_lay.addRow("Symbol:", self.paper_symbol_edit)
        
        self.paper_side_combo = QComboBox()
        self.paper_side_combo.addItems(["BUY", "SELL"])
        order_lay.addRow("Side:", self.paper_side_combo)
        
        self.paper_type_combo = QComboBox()
        self.paper_type_combo.addItems(["MARKET", "LIMIT", "STOP"])
        self.paper_type_combo.currentTextChanged.connect(self._on_paper_order_type_changed)
        order_lay.addRow("Type:", self.paper_type_combo)
        
        self.paper_qty_spin = QSpinBox()
        self.paper_qty_spin.setRange(1, 10000)
        self.paper_qty_spin.setValue(1)
        order_lay.addRow("Quantity:", self.paper_qty_spin)
        
        self.paper_price_spin = QDoubleSpinBox()
        self.paper_price_spin.setRange(0.01, 1000000.0)
        self.paper_price_spin.setDecimals(2)
        self.paper_price_spin.setValue(100.0)
        self.paper_price_spin.setPrefix("$")
        order_lay.addRow("Price:", self.paper_price_spin)
        
        self.paper_place_btn = QPushButton("📤 Place Order")
        self.paper_place_btn.setStyleSheet("""
            QPushButton {
                background: #4caf50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #66bb6a; }
            QPushButton:pressed { background: #388e3c; }
        """)
        self.paper_place_btn.clicked.connect(self._on_place_paper_order)
        order_lay.addRow(self.paper_place_btn)
        
        lay.addWidget(order_group)
        
        # Positions table
        positions_group = QGroupBox("Open Positions")
        positions_lay = QVBoxLayout(positions_group)
        
        self.paper_positions_table = QTableWidget()
        self.paper_positions_table.setColumnCount(6)
        self.paper_positions_table.setHorizontalHeaderLabels(["Symbol", "Qty", "Avg Price", "Current", "Unrealized PnL", "Value"])
        self.paper_positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.paper_positions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.paper_positions_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.paper_positions_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        positions_lay.addWidget(self.paper_positions_table)
        lay.addWidget(positions_group)
        
        # Trade history
        history_group = QGroupBox("Trade History")
        history_lay = QVBoxLayout(history_group)
        
        self.paper_history_table = QTableWidget()
        self.paper_history_table.setColumnCount(7)
        self.paper_history_table.setHorizontalHeaderLabels(["Time", "Symbol", "Side", "Qty", "Price", "Fees", "PnL"])
        self.paper_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.paper_history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.paper_history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.paper_history_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        history_lay.addWidget(self.paper_history_table)
        lay.addWidget(history_group)
        
        # Report button
        self.paper_report_btn = QPushButton("📊 Generate Report")
        self.paper_report_btn.setStyleSheet("""
            QPushButton {
                background: #2196f3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #42a5f5; }
            QPushButton:pressed { background: #1976d2; }
        """)
        self.paper_report_btn.clicked.connect(self._on_generate_paper_report)
        lay.addWidget(self.paper_report_btn)
        
        # Status
        self.paper_status_label = QLabel("Ready")
        lay.addWidget(self.paper_status_label)
        
        # Refresh timer
        self.paper_refresh_timer = QTimer()
        self.paper_refresh_timer.timeout.connect(self._refresh_paper_trading)
        self.paper_refresh_timer.start(10000)  # 10s
        
        return w


    # ── Opportunities Tab Callbacks ─────────────────────────────────────────

    def _on_scan_opportunities(self):
        """Scan for opportunities now."""
        self.opp_status_label.setText("Scanning...")
        try:
            from earning_pipeline import EarningPipeline
            from agents.opportunity_portfolio import PortfolioEntry, WorkStatus
            source = self.opp_source_combo.currentText()
            sources = None if source == "all" else [source]
            pipeline = EarningPipeline(portfolio=self.opportunity_portfolio)

            def add_found_opportunity(opportunity):
                opportunity_id = getattr(opportunity, "id", "")
                if not opportunity_id:
                    return
                existing = self.opportunity_portfolio.get(opportunity_id)
                if existing is not None:
                    return
                self.opportunity_portfolio.add(PortfolioEntry(
                    opportunity_id=opportunity_id,
                    opportunity_ref={
                        "id": opportunity_id,
                        "title": getattr(opportunity, "title", ""),
                        "description": getattr(opportunity, "description", ""),
                        "url": getattr(opportunity, "url", ""),
                        "source": getattr(opportunity, "source", ""),
                        "platform": getattr(opportunity, "platform", ""),
                        "category": getattr(opportunity, "type", ""),
                    },
                    work_status=WorkStatus.EVALUATING,
                    expected_value=float(getattr(opportunity, "estimated_usd_value", 0.0) or 0.0),
                    platform=getattr(opportunity, "platform", "") or "",
                    category=getattr(opportunity, "type", "") or "",
                    next_action="Review evidence and score before approval",
                ))
                self._refresh_opportunities()

            found = pipeline.discover(sources=sources, on_found=add_found_opportunity)
            self._refresh_opportunities()
            self.opp_status_label.setText(f"Scan complete: {len(found)} opportunities found")
        except Exception as exc:
            self.opp_status_label.setText(f"Scan failed: {exc}")

    def _configure_opportunity_auto_scan(self, enabled: bool):
        """Start or stop the user-configured opportunity scan timer."""
        timer = getattr(self, "opp_scan_timer", None)
        if timer is None:
            return
        if enabled:
            timer.setInterval(self.opp_scan_interval_spin.value() * 60 * 1000)
            timer.start()
            self.opp_status_label.setText("Auto-scan enabled")
        else:
            timer.stop()
            self.opp_status_label.setText("Auto-scan disabled")

    def _refresh_opportunities(self):
        """Refresh opportunities table."""
        from PySide6.QtCore import Qt
        entries = self.opportunity_portfolio.list_all()
        minimum = self.opp_min_score_spin.value() / 100
        source = self.opp_source_combo.currentText()
        self.opp_table.setRowCount(0)
        for entry in entries:
            if source != "all" and entry.platform.lower() != source.lower():
                continue
            if entry.policy_score and entry.policy_score < minimum:
                continue
            ref = entry.opportunity_ref or {}
            row = self.opp_table.rowCount()
            self.opp_table.insertRow(row)
            values = (
                ref.get("title", entry.opportunity_id), entry.platform or ref.get("source", ""),
                entry.category or ref.get("category", ""),
                f"${entry.expected_value:,.2f}", f"{entry.policy_score * 100:.0f}%",
                entry.work_status.value, ref.get("url", ref.get("source_url", "")),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, entry.opportunity_id)
                self.opp_table.setItem(row, column, item)

    def _on_research_opportunity(self):
        """Research selected opportunity."""
        entry = self._selected_opportunity_entry()
        if entry is None:
            self.opp_status_label.setText("Select an opportunity first")
            return
        from agents.opportunity_portfolio import WorkStatus
        try:
            self.opportunity_portfolio.transition_work_status(
                entry.opportunity_id, WorkStatus.EVALUATING)
            self._refresh_opportunities()
            self.opp_status_label.setText("Opportunity marked for evaluation")
        except Exception as exc:
            self.opp_status_label.setText(f"Research unavailable: {exc}")

    def _on_apply_opportunity(self):
        """Apply to selected opportunity."""
        entry = self._selected_opportunity_entry()
        if entry is None:
            self.opp_status_label.setText("Select an opportunity first")
            return
        from agents.opportunity_portfolio import WorkStatus
        try:
            if entry.work_status == WorkStatus.NEW:
                self.opportunity_portfolio.transition_work_status(
                    entry.opportunity_id, WorkStatus.EVALUATING)
                entry = self.opportunity_portfolio.get(entry.opportunity_id)
            if entry.work_status == WorkStatus.EVALUATING:
                self.opportunity_portfolio.transition_work_status(
                    entry.opportunity_id, WorkStatus.QUALIFIED)
                entry = self.opportunity_portfolio.get(entry.opportunity_id)
            self.opportunity_portfolio.transition_work_status(
                entry.opportunity_id, WorkStatus.AWAITING_APPROVAL)
            self._refresh_opportunities()
            self.opp_status_label.setText(
                "Application queued for human approval; nothing was submitted")
        except Exception as exc:
            self.opp_status_label.setText(f"Apply unavailable: {exc}")

    def _on_reject_opportunity(self):
        """Reject selected opportunity."""
        entry = self._selected_opportunity_entry()
        if entry is None:
            self.opp_status_label.setText("Select an opportunity first")
            return
        from agents.opportunity_portfolio import WorkStatus
        try:
            if entry.work_status == WorkStatus.NEW:
                self.opportunity_portfolio.transition_work_status(
                    entry.opportunity_id, WorkStatus.ABANDONED)
            else:
                self.opportunity_portfolio.transition_work_status(
                    entry.opportunity_id, WorkStatus.REJECTED)
            self._refresh_opportunities()
            self.opp_status_label.setText("Opportunity rejected")
        except Exception as exc:
            self.opp_status_label.setText(f"Reject unavailable: {exc}")

    def _selected_opportunity_entry(self):
        """Return the portfolio entry represented by the selected table row."""
        row = self.opp_table.currentRow()
        if row < 0:
            return None
        item = self.opp_table.item(row, 0)
        if item is None:
            return None
        return self.opportunity_portfolio.get(item.data(Qt.UserRole))

    # ── Paper Trading Tab Callbacks ─────────────────────────────────────────

    def _on_paper_order_type_changed(self, order_type: str):
        """Enable/disable price field based on order type."""
        if order_type == "MARKET":
            self.paper_price_spin.setEnabled(False)
            self.paper_price_spin.setStyleSheet("color: #888;")
        else:
            self.paper_price_spin.setEnabled(True)
            self.paper_price_spin.setStyleSheet("color: #e0e0e0;")

    def _on_place_paper_order(self):
        """Place a paper order."""
        symbol = self.paper_symbol_edit.text().strip()
        if not symbol:
            self.paper_status_label.setText("Error: Symbol required")
            return
        from agents.paper_trading import OrderSide, OrderType
        side = OrderSide.BUY if self.paper_side_combo.currentText() == "BUY" else OrderSide.SELL
        order_type = OrderType(self.paper_type_combo.currentText().lower())
        price = float(self.paper_price_spin.value())
        if order_type == OrderType.MARKET:
            self.paper_engine.update_price(symbol.upper(), price)
        order = self.paper_engine.place_order(
            symbol.upper(), side, float(self.paper_qty_spin.value()), order_type, price)
        if order is None:
            self.paper_status_label.setText(
                "Order rejected: check price, cash, position, and quantity")
        else:
            self.paper_status_label.setText(
                f"Order {order.status}: {order.symbol} {order.filled:g} @ ${order.average_price:,.2f}")
        self._refresh_paper_trading()

    def _on_generate_paper_report(self):
        """Generate paper trading report."""
        report = self.paper_engine.get_report()
        self.paper_status_label.setText(
            f"Report ready: {self.paper_engine.get_performance()['total_trades']} trades")
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.paper_report_btn.window(), "Paper Trading Report", report)
        except Exception:
            pass

    def _refresh_paper_trading(self):
        """Refresh paper trading display."""
        perf = self.paper_engine.get_performance()
        self.paper_equity_label.setText(f"${perf['current_equity']:,.2f}")
        self.paper_cash_label.setText(f"${perf['cash']:,.2f}")
        self.paper_return_label.setText(f"{perf['total_return_pct']:.2f}%")
        self.paper_sharpe_label.setText(f"{perf['sharpe_ratio']:.2f}")
        self.paper_drawdown_label.setText(f"{perf['max_drawdown_pct']:.2f}%")
        self.paper_trades_label.setText(str(perf['total_trades']))

        positions = self.paper_engine.get_all_positions()
        self.paper_positions_table.setRowCount(0)
        for position in positions:
            row = self.paper_positions_table.rowCount()
            self.paper_positions_table.insertRow(row)
            values = (
                position.symbol, f"{position.quantity:g}",
                f"${position.average_price:,.2f}", f"${position.current_price:,.2f}",
                f"${position.unrealized_pnl:,.2f}",
                f"${position.quantity * position.current_price:,.2f}",
            )
            for column, value in enumerate(values):
                self.paper_positions_table.setItem(row, column, QTableWidgetItem(value))

        trades = list(reversed(self.paper_engine.trades))
        self.paper_history_table.setRowCount(0)
        from datetime import datetime
        for trade in trades[-100:]:
            row = self.paper_history_table.rowCount()
            self.paper_history_table.insertRow(row)
            values = (
                datetime.fromtimestamp(trade.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                trade.symbol, trade.side.value.upper(), f"{trade.quantity:g}",
                f"${trade.price:,.2f}", f"${trade.fees:,.2f}",
                f"${trade.pnl:,.2f}",
            )
            for column, value in enumerate(values):
                self.paper_history_table.setItem(row, column, QTableWidgetItem(value))

    # ── Analytics Tab ─────────────────────────────────────────────────────

    def create_analytics_tab(self):
        """Create the Analytics tab — market data and strategy performance."""
        from gui.analytics_tab import AnalyticsTab
        from agents.workspace_context import register_component
        self.analytics_tab = AnalyticsTab(parent=self)
        register_component("analytics", self.analytics_tab)
        return self.analytics_tab
    
    def create_reputation_tab(self):
        """Create the Reputation tab — track agent reputation across platforms."""
        from agents.reputation import ReputationTracker

        self.reputation_tracker = ReputationTracker()
        w = QWidget()
        lay = QVBoxLayout(w)
        
        # Header
        header = QLabel("⭐ Reputation")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        lay.addWidget(header)
        
        # Overall score
        score_group = QGroupBox("Overall Score")
        score_lay = QFormLayout(score_group)
        
        self.reputation_score_label = QLabel("0.0")
        self.reputation_score_label.setStyleSheet("font-size: 24pt; font-weight: bold; color: #ffcc44;")
        score_lay.addRow("Internal Score:", self.reputation_score_label)
        
        self.reputation_tasks_label = QLabel("0")
        score_lay.addRow("Total Tasks:", self.reputation_tasks_label)
        
        self.reputation_earnings_label = QLabel("$0.00")
        self.reputation_earnings_label.setStyleSheet("color: #00ff88;")
        score_lay.addRow("Verified Payments:", self.reputation_earnings_label)
        
        self.reputation_roi_label = QLabel("0%")
        score_lay.addRow("ROI:", self.reputation_roi_label)
        
        lay.addWidget(score_group)
        
        # Badges
        badges_group = QGroupBox("Badges")
        badges_lay = QHBoxLayout(badges_group)
        self.reputation_badges_layout = badges_lay
        badges_lay.addWidget(QLabel("No badges earned yet"))
        lay.addWidget(badges_group)
        
        # Platform breakdown
        platform_group = QGroupBox("Platform Breakdown")
        platform_lay = QVBoxLayout(platform_group)
        
        self.reputation_platform_table = QTableWidget()
        self.reputation_platform_table.setColumnCount(5)
        self.reputation_platform_table.setHorizontalHeaderLabels(["Platform", "Tasks", "Success Rate", "Recorded Value", "ROI"])
        self.reputation_platform_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.reputation_platform_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        platform_lay.addWidget(self.reputation_platform_table)
        
        lay.addWidget(platform_group)
        
        # Refresh button
        self.reputation_refresh_btn = QPushButton("🔄 Refresh")
        self.reputation_refresh_btn.clicked.connect(self._on_refresh_reputation)
        lay.addWidget(self.reputation_refresh_btn)

        self._on_refresh_reputation()
        
        return w
    
    def create_data_explorer_tab(self):
        """Create the Data Explorer tab — web scraping and data extraction."""
        w = QWidget()
        lay = QVBoxLayout(w)
        
        # Header
        header = QLabel("🌐 Data Explorer")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        lay.addWidget(header)
        
        # URL input
        url_group = QGroupBox("URL")
        url_lay = QHBoxLayout(url_group)
        self.data_url_edit = QLineEdit()
        self.data_url_edit.setPlaceholderText("Enter URL to scrape...")
        url_lay.addWidget(self.data_url_edit)
        
        self.data_scrape_btn = QPushButton("🔍 Scrape")
        self.data_scrape_btn.clicked.connect(self._on_scrape_url)
        url_lay.addWidget(self.data_scrape_btn)
        
        lay.addWidget(url_group)
        
        # Results
        results_group = QGroupBox("Results")
        results_lay = QVBoxLayout(results_group)
        
        self.data_results_edit = QTextEdit()
        self.data_results_edit.setReadOnly(True)
        self.data_results_edit.setStyleSheet("font-family: Consolas, Monaco, monospace; font-size: 11px;")
        results_lay.addWidget(self.data_results_edit)
        
        lay.addWidget(results_group)
        
        # Status
        self.data_status_label = QLabel("Ready")
        lay.addWidget(self.data_status_label)
        
        return w


    # ── Analytics Tab Callbacks ────────────────────────────────────────────

    def _on_refresh_reputation(self):
        """Refresh reputation display."""
        tracker = getattr(self, "reputation_tracker", None)
        if tracker is None:
            return
        overall = tracker.get_overall_metrics()
        self.reputation_score_label.setText(f"{tracker.get_reputation_score():.1f}/100")
        self.reputation_tasks_label.setText(str(overall["total_tasks"]))
        self.reputation_earnings_label.setText(f"${overall['verified_earnings']:,.2f}")
        self.reputation_roi_label.setText(
            "N/A" if overall["total_costs"] <= 0 else f"{overall['roi']:.1f}%")

        while self.reputation_badges_layout.count():
            item = self.reputation_badges_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        badges = tracker.get_badges()
        if not badges:
            self.reputation_badges_layout.addWidget(QLabel("No badges earned yet"))
        else:
            for badge in badges:
                label = QLabel(f"{badge.icon} {badge.name}")
                label.setToolTip(badge.description)
                self.reputation_badges_layout.addWidget(label)
        self.reputation_badges_layout.addStretch()

        metrics = tracker.get_all_metrics()
        self.reputation_platform_table.setRowCount(0)
        for platform, item in sorted(metrics.items()):
            row = self.reputation_platform_table.rowCount()
            self.reputation_platform_table.insertRow(row)
            values = (
                platform, str(item.total_tasks), f"{item.success_rate * 100:.1f}%",
                f"${item.total_earnings:,.2f}",
                "N/A" if item.total_costs <= 0 else f"{item.roi:.1f}%",
            )
            for column, value in enumerate(values):
                self.reputation_platform_table.setItem(row, column, QTableWidgetItem(value))

    # ── Data Explorer Tab Callbacks ────────────────────────────────────────

    def _on_scrape_url(self):
        """Scrape the entered URL."""
        url = self.data_url_edit.text().strip()
        if not url:
            self.data_status_label.setText('Error: URL required')
            return
        if not url.startswith(("http://", "https://")):
            self.data_status_label.setText('Error: URL must start with http:// or https://')
            return
        self.data_status_label.setText(f'Scraping {url}...')
        self.data_results_edit.clear()
        self.data_scrape_btn.setEnabled(False)
        self._data_explorer_worker = DataExplorerWorker(url)
        self._data_explorer_worker.finished.connect(self._on_scrape_finished)
        self._data_explorer_worker.start()

    def _on_scrape_finished(self, result: dict):
        """Render a completed scrape in the Data Explorer results pane."""
        self.data_scrape_btn.setEnabled(True)
        if not result.get("ok"):
            self.data_status_label.setText(f"Scrape failed: {result.get('error', 'unknown error')}")
            self.data_results_edit.setPlainText("No data returned.")
            return

        lines = [f"URL: {result.get('url', '')}", ""]
        text = (result.get("text") or "").strip()
        if text:
            lines.extend(["TEXT", text, ""])
        links = result.get("links") or []
        if links:
            lines.append("LINKS")
            lines.extend(f"- {link}" for link in links[:100])
            lines.append("")
        tables = result.get("tables") or []
        if tables:
            lines.append("TABLES")
            lines.extend(str(table) for table in tables[:20])
        self.data_results_edit.setPlainText("\n".join(lines).strip() or "(page returned no readable content)")
        self.data_status_label.setText(
            f"Scrape complete: {len(text)} characters, {len(links)} links, {len(tables)} tables"
        )

    def _on_provider_widget_changed(self, provider_name: str, action: str):
        """Handle provider configuration changes from the widget."""
        from agents.provider_manager import ProviderManager
        pm = ProviderManager.instance()
        normalized_provider = ProviderManager.normalize_provider_name(provider_name)
        is_local_route_change = (
            provider_name == "local"
            or normalized_provider in {"llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp"}
        )
        if is_local_route_change:
            # The Settings tab changes the process environment immediately,
            # so rebuild the shared runtime before Providers & GPU renders its
            # route labels or handles a launch request.
            try:
                from agents.dual_brain_runtime import DualBrainRuntime
                self.dual_brain_runtime = DualBrainRuntime.from_env()
                panel = getattr(self, "providers_gpu_tab", None)
                if panel is not None:
                    panel.runtime = self.dual_brain_runtime
                    panel._apply_runtime()
                    panel._repopulate_model_combo(True)
                    panel._repopulate_model_combo(False)
                    panel._refresh_provider_status()
            except Exception:
                pass
        
        if action.startswith("model:"):
            model = action[6:]
            provider = pm.get_provider(provider_name)
            if provider:
                provider.selected_model = model
        elif action.startswith("gpu:"):
            gpu_index = int(action[4:])
            pm.assign_provider_to_gpu(provider_name, gpu_index)
        elif action == "toggle":
            # ProviderConfigWidget has already applied the new state. Do not
            # toggle it a second time here or an Enable click becomes Disabled.
            pass
        
        # Keep the user's toggle/model state; probing is performed by the
        # provider widget's refresh path and must not overwrite an enable click.
        try:
            from agents.base_worker import _active_worker
            if _active_worker is not None:
                _active_worker.invalidate_provider_registry()
        except Exception:
            pass

