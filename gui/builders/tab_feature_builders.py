"""Feature-specific Qt tab builders."""

import os
import queue
import re
import threading
import time
from datetime import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QMessageBox,
    QScrollArea, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget, QAbstractItemView,
)

from gui.builders.tab_workers import (
    DataExplorerWorker, LiveOrderProposalWorker, LivePortfolioWorker,
    SocialDiscoveryWorker, MoltbookFeedWorker,
)


def _dual_brain_message_log_path() -> str:
    """Path of the Collaboration tab's message log.

    ARCH-ENG-246: this was computed from ``__file__`` -- i.e. inside the
    source tree (``gui/dual_brain_messages.db``). A live SQLite store in the
    checkout is exactly what ARCH-ENG-167's root-hygiene audit exists to
    prevent, and it caught this one: three governed tests failed on the
    undeclared store the Collaboration tab created the first time the GUI
    was built. All persistence lives under the app-data directory beside
    ``goals.db`` / the event log -- same LOCALAPPDATA convention, same
    fallback for an unset environment.
    """
    data_dir = os.path.join(os.environ.get("LOCALAPPDATA", "."), "MrBot1000")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        # The log will surface its own failure; constructing a tab must not
        # die because the data directory is unwritable.
        pass
    return os.path.join(data_dir, "dual_brain_messages.db")


class FeatureTabBuildersMixin:

    def create_chat_tab(self):
        """Create the Chat tab (Human ↔ Small Brain)."""
        from agents.brains.big_brain import BigBrainAdapter
        from agents.brains.small_brain import SmallBrainAdapter
        from gui.tabs.chat_tab import ChatTab

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
        from agents.brains.big_brain import BigBrainAdapter
        from agents.brains.small_brain import SmallBrainAdapter
        from gui.tabs.dialogue_tab import DialogueTab

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
        # Give Dialogue the exact opportunity rows the Opportunities tab shows,
        # so the personas plan around real, visible candidates. The provider is
        # read lazily on every turn; until the tab builds it returns nothing and
        # the Dialogue board falls back to the portfolio snapshot.
        try:
            self.dialogue_tab._visible_opportunity_entries = (
                lambda: (self, list(getattr(self, "_opp_visible_entries", []) or []))
            )
        except Exception:
            pass
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

        from agents.brains.big_brain import BigBrainAdapter
        from agents.brains.small_brain import SmallBrainAdapter
        from agents.runtime.dual_brain import DualBrainRuntime
        from gui.widgets.dual_brain_control import DualBrainControl

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
        from gui.tabs.model_library_tab import ModelLibraryTab

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
        from gui.tabs.safety_tools_tab import SafetyTab
        self.safety_tools_tab = SafetyTab(parent=self)
        # Hand the tab a real guard when one exists. Without this the tab
        # permanently took its `approval_queue` fallback and never saw a
        # SafetyGuard-queued item. Since HumanApprovalLayer now mirrors into
        # HumanApprovalQueue, the fallback is correct either way — this only
        # makes the guard-sourced view available where a guard is wired.
        guard = getattr(self, "safety_guard", None)
        if guard is None:
            earning = getattr(self, "_earning_tab", None)
            guard = getattr(earning, "safety_guard", None) if earning else None
        if guard is not None:
            self.safety_tools_tab.safety_guard = guard
        # ARCH-ENG-284 (U-01): the instruction gate is the trust anchor every
        # platform adapter uses. Hand the same instance to the tab that now
        # owns the quarantine review surface, so an approval here is the
        # approval the adapters observe. None is valid (gate unavailable) and
        # the tab then fails visibly closed rather than silently.
        self.safety_tools_tab.set_instruction_gate(
            getattr(self, "instruction_gate", None))
        return self.safety_tools_tab

    def create_collaboration_tab(self):
        """Create the Collaboration / Run Monitor tab.

        Owns the shared DualBrainCoordinator (backed by the canonical runtime)
        so Chat/Dialogue/monitor all observe the same collaboration ledger. The
        injected model_fn routes inference to the Big/Small brain adapters; a
        down server degrades to a FAILED run (never blocks or crashes).
        """
        from agents.core.comms_log import MessageLog
        from agents.cognition.coordinator import DualBrainCoordinator
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        from gui.tabs.collaboration_tab import CollaborationTab

        # Shared canonical runtime (cheap: no network at construction).
        if not hasattr(self, "dual_brain_runtime") or self.dual_brain_runtime is None:
            self.dual_brain_runtime = DualBrainRuntime.from_env()

        def _model_fn(role, _stage, prompt):
            if role == BrainRole.BIG:
                from agents.brains.big_brain import BigBrainAdapter
                return BigBrainAdapter().analyze_with_tools(prompt)
            from agents.brains.small_brain import SmallBrainAdapter
            return SmallBrainAdapter().chat(prompt)

        if not hasattr(self, "dual_brain_coordinator") or self.dual_brain_coordinator is None:
            msg_log_path = _dual_brain_message_log_path()
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

    def create_management_tab(self):
        """Management Control Center — administrative-only edition.
        
        Brain start/stop/restart and model selection live exclusively in
        Providers & GPU. This tab handles earnings, research, proposals,
        payouts, and system actions only.
        """
        from gui.tabs.management_tab import ManagementTab
        self.management_tab = ManagementTab(parent=self)
        
        # Connect signals to main window methods
        self.management_tab.request_run_cycle.connect(self._run_earning_cycle)
        self.management_tab.request_force_improve.connect(self.force_safe_improve)
        self.management_tab.request_force_rescan.connect(self.force_research_rescan)
        self.management_tab.request_select_research_folder.connect(self.select_research_folder)
        self.management_tab.request_review_proposal.connect(self._on_management_review_proposal)
        self.management_tab.request_submit_proposal.connect(self._on_management_submit_proposal)
        self.management_tab.request_verify_paid.connect(self._on_management_verify_paid)
        # ARCH-ENG-287 (Z-01): wire the reconciliation surface to the live
        # lifecycle method it exists to reach.
        self.management_tab.request_reconcile_paid.connect(
            self._reconcile_paid_evidence)

        return self.management_tab

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


    def create_file_browser_tab(self):
        """Web Browser tab — the AGENTS' live web-browsing surface.

        v2.1.84 (ARCH-ENG-105): this is where the personas' web activity renders
        with REAL page loading (a QWebEngineView), not just text. When an agent
        runs web_read/web_search, the URL loads here so the operator can watch
        what it fetches. A manual URL bar remains for the operator. The agents'
        data still comes from web_eyes text extraction; this tab is the visual
        mirror. Navigation arrives on the GUI thread via gui.widgets.web_nav_bus.
        """
        from PySide6.QtCore import QThread

        # Real page rendering (embedded Chromium). Falls back to text-only if
        # QtWebEngine is unavailable.
        web_view = None
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtCore import QUrl
            web_view = QWebEngineView()
            web_view.setMinimumHeight(320)
        except Exception:
            web_view = None

        class _WebReadWorker(QThread):
            done = Signal(dict)

            def __init__(self, url: str):
                super().__init__()
                self._url = url

            def run(self):
                try:
                    from agents.integrations.browser import WebController
                    result = WebController().read_page(self._url)
                    if not isinstance(result, dict):
                        result = {"ok": False, "error": "unexpected reader result"}
                except Exception as exc:  # network/deps — never crash the GUI
                    result = {"ok": False, "error": str(exc)}
                self.done.emit(result)

        w = QWidget()
        lay = QVBoxLayout(w)

        header = QLabel("🌐 Web Browser")
        header.setFont(QFont("Segoe UI", 16, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 6px;")
        lay.addWidget(header)
        note = QLabel(
            "Live view of the agents' web browsing. When a persona runs "
            "web_read/web_search, the page loads here in real time. You can also "
            "open a URL yourself below. Robots.txt / human-open-only hosts are "
            "respected by the agents; use Open in system browser for pages that "
            "need login or interaction.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;")
        self._themeable.append((note, "caption", "font-size:10px;"))
        lay.addWidget(note)

        # URL bar + actions
        bar = QHBoxLayout()
        self.web_url_edit = QLineEdit()
        self.web_url_edit.setPlaceholderText("https://example.com/page")
        self.web_url_edit.returnPressed.connect(lambda: self._web_browser_read(w))
        bar.addWidget(self.web_url_edit)
        read_btn = QPushButton("📖 Open page")
        read_btn.clicked.connect(lambda: self._web_browser_read(w))
        bar.addWidget(read_btn)
        open_btn = QPushButton("↗ Open in system browser")
        open_btn.clicked.connect(self._web_browser_open_external)
        bar.addWidget(open_btn)
        lay.addLayout(bar)

        self.web_status_label = QLabel(
            "Watching for agent web activity…")
        self.web_status_label.setWordWrap(True)
        self.web_status_label.setStyleSheet(f"color:{self._t('caption')};font-size:10px;")
        self._themeable.append((self.web_status_label, "caption", "font-size:10px;"))
        lay.addWidget(self.web_status_label)

        # Real rendered page (or a text-only placeholder if no WebEngine).
        if web_view is not None:
            lay.addWidget(web_view, stretch=3)
        else:
            fallback = QLabel(
                "Visual page rendering unavailable (QtWebEngine not installed). "
                "Showing extracted text only.")
            fallback.setWordWrap(True)
            fallback.setStyleSheet(f"color:{self._t('caption')};")
            lay.addWidget(fallback)

        # Activity log — every agent web action, newest last.
        self.web_activity_log = QPlainTextEdit()
        self.web_activity_log.setReadOnly(True)
        self.web_activity_log.setMaximumBlockCount(500)
        self.web_activity_log.setFixedHeight(110)
        lay.addWidget(self.web_activity_log, stretch=1)

        self.web_output = QTextEdit()
        self.web_output.setReadOnly(True)
        self.web_output.setMaximumHeight(140)
        lay.addWidget(self.web_output)

        # Off-thread fetch for the operator's manual reads; keep the worker.
        self._web_worker = None

        def _load_url(url: str, context: str):
            """Load *url* into the view + log it (GUI thread only)."""
            if not url:
                return
            self.web_url_edit.setText(url)
            if web_view is not None:
                try:
                    web_view.setUrl(QUrl(url))
                except Exception:
                    pass
            _log_line(f"▶ {context}: {url}")

        def _log_line(text: str):
            try:
                from datetime import datetime
                ts = datetime.now().strftime("%H:%M:%S")
                self.web_activity_log.appendPlainText(f"[{ts}] {text}")
            except Exception:
                pass

        def _on_nav(url: str, context: str):
            self.web_status_label.setText(f"🌐 {context}: {url}")
            _load_url(url, context)

        def _on_activity(record: dict):
            kind = record.get("kind", "")
            if kind == "search":
                q = record.get("query", "")
                _log_line(f"🔎 agent searched: {q}")
                for r in record.get("results", [])[:5]:
                    _log_line(f"    • {r.get('title','')} — {r.get('url','')}")
            elif kind == "read":
                _log_line(f"📄 agent read: {record.get('url','')}")

        # Connect the agent→tab nav bus (GUI thread). QueuedConnection so an
        # emit from a worker thread (the agent tool) is delivered here safely.
        try:
            from PySide6.QtCore import Qt as _Qt
            from gui.widgets.web_nav_bus import (
                web_nav_bus, recent_navigations)
            bus = web_nav_bus()
            bus.navigate.connect(_on_nav, _Qt.ConnectionType.QueuedConnection)
            bus.activity.connect(_on_activity, _Qt.ConnectionType.QueuedConnection)
            self._web_nav_bus = bus  # keep a ref alive
            # Replay recent activity: this tab is lazy-built on first show, so
            # the agents may have browsed before it existed (ARCH-ENG-105).
            for entry in recent_navigations():
                try:
                    if entry[0] == "nav":
                        _log_line(f"▶ {entry[2]}: {entry[1]}")
                    elif entry[0] == "activity":
                        rec = entry[1]
                        if rec.get("kind") == "search":
                            _log_line(f"🔎 agent searched: {rec.get('query','')}")
                        elif rec.get("kind") == "read":
                            _log_line(f"📄 agent read: {rec.get('url','')}")
                except Exception:
                    pass
            # Load the most recent navigated URL into the view.
            _last_url = ""
            for entry in reversed(recent_navigations()):
                if entry[0] == "nav":
                    _last_url = entry[1]
                    break
            if _last_url and web_view is not None:
                try:
                    web_view.setUrl(QUrl(_last_url))
                    self.web_status_label.setText(f"🌐 last agent page: {_last_url}")
                except Exception:
                    pass
        except Exception:
            self._web_nav_bus = None

        def _on_done(result):
            self._web_worker = None
            read_btn.setEnabled(True)
            url = result.get("url", self.web_url_edit.text().strip())
            if result.get("human_open_only"):
                self.web_status_label.setText(
                    f"🔒 {url} — blocked by robots.txt / human-open-only. "
                    "Use Open in system browser.")
                self.web_output.setPlainText(
                    result.get("error") or "This host only allows human access.")
                return
            if not result.get("ok"):
                self.web_status_label.setText(
                    f"⚠️ Could not read {url}: {result.get('error', 'unknown error')}")
                self.web_output.setPlainText(
                    result.get("text") or result.get("error", ""))
                return
            title = result.get("title") or url
            text = result.get("text") or result.get("content") or ""
            self.web_status_label.setText(
                f"✅ {title} — {len(text):,} chars"
                + (" (via headless browser)" if result.get("escalated") else ""))
            self.web_output.setPlainText(text if text else "(no extractable text)")

        def _read():
            url = self.web_url_edit.text().strip()
            if not url:
                self.web_status_label.setText("Enter a URL first.")
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                url = "https://" + url
                self.web_url_edit.setText(url)
            # Show it immediately in the view, then fetch text off-thread.
            _load_url(url, "operator")
            read_btn.setEnabled(False)
            self.web_status_label.setText(f"⏳ Reading {url} ...")
            self.web_output.setPlainText("")
            worker = _WebReadWorker(url)
            worker.done.connect(_on_done)
            worker.finished.connect(worker.deleteLater)
            self._web_worker = worker
            worker.start()

        # Stash the read trigger so the button lambdas above can call it.
        w._web_browser_read = _read
        return w

    def _web_browser_read(self, tab):
        """Trigger the Web Browser tab's read (bound per-tab via ``_web_browser_read``)."""
        fn = getattr(tab, "_web_browser_read", None)
        if callable(fn):
            fn()

    def _web_browser_open_external(self):
        """Open the current URL in the user's default system browser."""
        import webbrowser
        url = getattr(self, "web_url_edit", None)
        url = url.text().strip() if url is not None else ""
        if url and not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        if url:
            webbrowser.open(url)


    def create_payments_tab(self):
        """Create the Payments tab — wallet management, transactions, and payouts."""
        # Import the full PaymentsTab implementation
        try:
            from gui.tabs.payments_tab import PaymentsTab
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
            from gui.tabs.earning_tab import EarningTab
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
            from gui.tabs.earning_insights import TabAwareInsightsPanel
            from agents.core.event_logger import StructuredEventLogger
            from agents.safety.approval import HumanApprovalQueue
            from agents.runtime.context import register_component

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
            from gui.panels.approval_panel import ApprovalPanel
            from agents.safety.approval import HumanApprovalQueue

            panel = ApprovalPanel(
                parent=self,
                approval_queue=HumanApprovalQueue.instance(),
            )
            self._approval_panel = panel
            try:
                panel.item_decided.connect(self._on_approval_decided)
            except Exception:
                pass
            try:
                self._refresh_approval_alert()
            except Exception:
                pass
            return panel
        except Exception as e:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel(f"Approval queue unavailable: {e}"))
            return w

    def create_registration_tab(self):
        """Gated platform sign-up panel (Phase B)."""
        try:
            from gui.panels.registration_panel import RegistrationPanel
            from agents.safety.approval import HumanApprovalQueue

            panel = RegistrationPanel(
                parent=self,
                approval_queue=HumanApprovalQueue.instance(),
            )
            self._registration_panel = panel
            return panel
        except Exception as e:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel(f"Registration unavailable: {e}"))
            return w

    def create_logs_tab(self):
        """Live Logs tab with full information display including tokens/sec and trigger info."""
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
        
        # Export logs button
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export_logs)
        frow.addWidget(export_btn)
        
        lay.addLayout(frow)

        # Table widget for structured log display
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(6)
        self.log_table.setHorizontalHeaderLabels(["Time", "Severity", "Source", "Message", "Tokens/s", "Details"])
        # Column widths: Time/Severity/Source are compact, Message is wide, Tokens/s and Details are medium
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Time
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Severity
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Source
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)  # Message — wide
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Tokens/s
        self.log_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Interactive)  # Details — user-resizable
        self.log_table.horizontalHeader().resizeSection(5, 120)  # default 120px
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setWordWrap(True)  # wrap long messages to multiple lines
        self.log_table.setStyleSheet(
            "font-family:Consolas,Monaco,monospace;font-size:11px;"
            "background:#0a0a0f;color:#d4d4d4;"
            "QHeaderView::section { background:#1a1a1f; color:#e0e0e0; }"
        )
        self.log_table.itemSelectionChanged.connect(self._show_log_details)
        # lay.addWidget(self.log_table)  # removed — splitter below
        
        # Details panel for selected log entry
        details_group = QGroupBox("Entry Details")
        details_layout = QVBoxLayout(details_group)
        self.log_details = QTextEdit()
        self.log_details.setReadOnly(True)
        self.log_details.setMinimumHeight(80)
        self.log_details.setMaximumHeight(250)  # larger max so more content visible
        self.log_details.setStyleSheet(
            "font-family:Consolas,Monaco,monospace;font-size:10px;"
            "background:#0a0a0f;color:#d4d4d4;"
        )
        details_layout.addWidget(self.log_details)
        # lay.addWidget(details_group)  # removed — splitter below

        # Resizable vertical splitter for table + details
        from PySide6.QtWidgets import QSplitter
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.log_table)
        splitter.addWidget(details_group)
        splitter.setStretchFactor(0, 3)  # table gets 3x more space
        splitter.setStretchFactor(1, 1)  # details gets 1x
        splitter.setSizes([400, 150])
        lay.addWidget(splitter)
        
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
        self.db_stat_prompt_tokens = self._stat_cell("Prompt Tokens", "0", "#e91e63")
        self.db_stat_completion_tokens = self._stat_cell("Completion Tokens", "0", "#009688")

        stats_grid.addWidget(self.db_stat_calls, 0, 0)
        stats_grid.addWidget(self.db_stat_errors, 0, 1)
        stats_grid.addWidget(self.db_stat_avg_latency, 0, 2)
        stats_grid.addWidget(self.db_stat_chars, 0, 3)
        stats_grid.addWidget(self.db_stat_cost, 1, 0)
        stats_grid.addWidget(self.db_stat_tokens_sec, 1, 1)
        stats_grid.addWidget(self.db_stat_uptime, 1, 2)
        stats_grid.addWidget(self.db_stat_db_size, 1, 3)
        stats_grid.addWidget(self.db_stat_prompt_tokens, 2, 0)
        stats_grid.addWidget(self.db_stat_completion_tokens, 2, 1)

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

        # ── Diagnostics sections (merged from the old Diagnostics tab, v2.1.11) ──
        health_group = QGroupBox("Brain Provider Health")
        health_layout = QVBoxLayout(health_group)
        self.diagnostics_health_table = QTableWidget(0, 7)
        self.diagnostics_health_table.setHorizontalHeaderLabels([
            "Role", "Provider", "Model", "Reachable", "Model Status",
            "Models", "Latency",
        ])
        self.diagnostics_health_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.diagnostics_health_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diagnostics_health_table.setSelectionMode(QAbstractItemView.NoSelection)
        health_layout.addWidget(self.diagnostics_health_table)
        lay.addWidget(health_group)

        performance_group = QGroupBox("Backend Performance Baseline")
        performance_layout = QVBoxLayout(performance_group)
        self.diagnostics_performance_label = QLabel("No telemetry recorded")
        self.diagnostics_performance_label.setWordWrap(True)
        performance_layout.addWidget(self.diagnostics_performance_label)
        lay.addWidget(performance_group)

        reconciliation_group = QGroupBox("State Reconciliation (read-only)")
        reconciliation_layout = QVBoxLayout(reconciliation_group)
        self.diagnostics_reconciliation_label = QLabel("No report loaded")
        reconciliation_layout.addWidget(self.diagnostics_reconciliation_label)
        self.diagnostics_conflict_table = QTableWidget(0, 6)
        self.diagnostics_conflict_table.setHorizontalHeaderLabels([
            "Severity", "Opportunity", "Category", "Message", "Review", "Sources",
        ])
        self.diagnostics_conflict_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.diagnostics_conflict_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diagnostics_conflict_table.setSelectionMode(QAbstractItemView.NoSelection)
        reconciliation_layout.addWidget(self.diagnostics_conflict_table, stretch=1)
        lay.addWidget(reconciliation_group, stretch=1)

        # Refresh button
        btn_row = QHBoxLayout()
        db_refresh_btn = QPushButton("🔄 Refresh Stats")
        db_refresh_btn.clicked.connect(self.refresh_db_stats)
        btn_row.addWidget(db_refresh_btn)
        btn_row.addStretch(1)
        # Also refresh diagnostics sections (health, perf, reconciliation)
        diag_refresh_btn = QPushButton("🔍 Refresh Diagnostics")
        # ARCH-ENG-221: `clicked` emits a `bool checked`, which would bind
        # straight to `force` -- and it is False on a normal click, silently
        # making the Refresh button a no-op refresh. Wrap it explicitly.
        diag_refresh_btn.clicked.connect(lambda _=False: self.refresh_diagnostics(force=True))
        btn_row.addWidget(diag_refresh_btn)
        lay.addLayout(btn_row)

        # Keep new calls and events visible without requiring a manual refresh.
        #
        # ARCH-ENG-221: THIS TIMER WAS NEVER VISIBILITY-GATED.
        #
        # It ran every 5 s for the whole process lifetime, whether or not this tab
        # was on screen, and `refresh_db_stats` is not cheap: `get_llm_stats()`
        # (app/database.py) is FOUR unindexed full-table aggregates over the
        # append-only `llm_calls` table, which is written once per LLM call and
        # never pruned. On top of that it rebuilds four `QTableWidget`s
        # cell-by-cell -- the event table alone is 100 rows x 4 columns = 400
        # `QTableWidgetItem` allocations -- on the GUI thread, every tick.
        #
        # The consequence on the target machine (6 cores) is a recurring GUI
        # stall that grows without limit as `llm_calls` grows, in a process
        # that may already be holding a 10 GB model in RAM.
        #
        # It is now stopped while hidden, using the `refresh_coordinator`
        # pattern already established in this file at :987-1001.
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(5000)
        self._stats_timer.timeout.connect(self.refresh_db_stats)

        def _stats_show(event):
            self._stats_timer.start()
            QWidget.showEvent(w, event)

        def _stats_hide(event):
            self._stats_timer.stop()
            QWidget.hideEvent(w, event)

        w.showEvent = _stats_show
        w.hideEvent = _stats_hide
        # Populate once now; the timer only runs while the tab is visible.
        QTimer.singleShot(0, self.refresh_db_stats)

        return w

    def create_diagnostics_tab(self):
        """Backward-compat shim: build only the diagnostics sections.

        Since v2.1.11 these live inside the DB Stats tab.  This method is kept
        so existing tests and any external callers keep working; it builds a
        standalone widget containing just the diagnostics groups.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        title = QLabel("Runtime Diagnostics")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        health_group = QGroupBox("Brain Provider Health")
        health_layout = QVBoxLayout(health_group)
        self.diagnostics_health_table = QTableWidget(0, 7)
        self.diagnostics_health_table.setHorizontalHeaderLabels([
            "Role", "Provider", "Model", "Reachable", "Model Status",
            "Models", "Latency",
        ])
        self.diagnostics_health_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.diagnostics_health_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diagnostics_health_table.setSelectionMode(QAbstractItemView.NoSelection)
        health_layout.addWidget(self.diagnostics_health_table)
        lay.addWidget(health_group)

        performance_group = QGroupBox("Backend Performance Baseline")
        performance_layout = QVBoxLayout(performance_group)
        self.diagnostics_performance_label = QLabel("No telemetry recorded")
        self.diagnostics_performance_label.setWordWrap(True)
        performance_layout.addWidget(self.diagnostics_performance_label)
        lay.addWidget(performance_group)

        reconciliation_group = QGroupBox("State Reconciliation (read-only)")
        reconciliation_layout = QVBoxLayout(reconciliation_group)
        self.diagnostics_reconciliation_label = QLabel("No report loaded")
        reconciliation_layout.addWidget(self.diagnostics_reconciliation_label)
        self.diagnostics_conflict_table = QTableWidget(0, 6)
        self.diagnostics_conflict_table.setHorizontalHeaderLabels([
            "Severity", "Opportunity", "Category", "Message", "Review", "Sources",
        ])
        self.diagnostics_conflict_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.diagnostics_conflict_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diagnostics_conflict_table.setSelectionMode(QAbstractItemView.NoSelection)
        reconciliation_layout.addWidget(self.diagnostics_conflict_table, stretch=1)
        lay.addWidget(reconciliation_group, stretch=1)

        refresh = QPushButton("Refresh Diagnostics")
        refresh.clicked.connect(lambda _=False: self.refresh_diagnostics(force=True))
        lay.addWidget(refresh)
        self._diagnostics_refresh_button = refresh
        QTimer.singleShot(0, self.refresh_diagnostics)
        return w

    def _create_feature_monitor(self, title: str, columns: list[str], refresh_fn):
        """Build a read-only feature monitor with visibility-aware refresh."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        heading = QLabel(title)
        heading.setFont(QFont("Segoe UI", 16, QFont.Bold))
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)
        status = QLabel("Loading…")
        status.setWordWrap(True)
        layout.addWidget(status)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(table, stretch=1)
        widget._feature_status = status
        widget._feature_table = table
        widget._feature_refresh_key = f"feature-monitor:{title}:{id(widget)}"
        widget._feature_refresh = refresh_fn
        from gui.builders.refresh_coordinator import refresh_coordinator
        coordinator = refresh_coordinator()
        coordinator.register(widget._feature_refresh_key, refresh_fn, 5000)

        def _show(event):
            refresh_fn()
            coordinator.set_visible(widget._feature_refresh_key, True)
            QWidget.showEvent(widget, event)

        def _hide(event):
            coordinator.set_visible(widget._feature_refresh_key, False)
            QWidget.hideEvent(widget, event)

        widget.showEvent = _show
        widget.hideEvent = _hide
        return widget

    def create_social_activity_tab(self):
        """Show social activity and provide a gated discovery action."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agent.db")
        holder = {}
        _QUERY = ("SELECT ts, event_type, source, message FROM events "
                  "WHERE lower(source) LIKE '%social%' OR lower(event_type) LIKE '%social%' "
                  "ORDER BY ts DESC LIMIT 100")

        def apply(rows, error):
            # Runs on the GUI thread (worker callback) — safe to touch widgets.
            table = holder["widget"]._feature_table
            status = holder["widget"]._feature_status
            if error:
                status.setText(f"Social activity unavailable: {error}")
                table.setRowCount(0)
                return
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels(
                ["Timestamp", "Event", "Source", "Conversation / Post / Topic", "Next action"])
            table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                for col_idx, value in enumerate(row):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(str(value or "")))
                table.setItem(row_idx, 4, QTableWidgetItem(
                    "Review opportunity" if "opportun" in str(row[1]).lower()
                    else "Inspect evidence"))
            status.setText(f"{len(rows)} persisted social events; read-only monitor")

        def refresh():
            # Run the SQLite read off the GUI thread so the tab never freezes
            # on the 5s poll or on first show.
            try:
                from gui.workers.db_query_worker import run_db_query
                run_db_query(db_path, _QUERY, apply, parent=holder.get("widget"))
            except Exception as exc:
                apply([], str(exc))

        widget = self._create_feature_monitor(
            "Social Activity", ["Timestamp", "Event", "Source", "Conversation / Post / Topic"],
            refresh)
        holder["widget"] = widget
        action_row = QHBoxLayout()
        scan_button = QPushButton("Scan Social Sources")
        scan_button.setToolTip(
            "Run the feature-gated social discovery service and save found opportunities.")
        action_row.addWidget(scan_button)
        action_row.addStretch(1)
        widget.layout().insertLayout(2, action_row)

        def scan_finished(result):
            table = holder["widget"]._feature_table
            status = holder["widget"]._feature_status
            if result.get("ok"):
                opportunities = result.get("opportunities", [])
                status.setText(
                    f"Social scan found {len(opportunities)} opportunities; "
                    "review them in the earning pipeline before any action.")
                table.setColumnCount(5)
                table.setHorizontalHeaderLabels(
                    ["ID", "Title", "Platform", "Estimated value", "Review"])
                table.setRowCount(len(opportunities))
                for row_idx, item in enumerate(opportunities):
                    values = (
                        item.get("id", ""),
                        item.get("title", ""),
                        item.get("platform", ""),
                        item.get("amount", 0.0),
                        "Evaluate + verify",
                    )
                    for col_idx, value in enumerate(values):
                        table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))
            else:
                status.setText(f"Social scan failed: {result.get('error', 'unknown error')}")
            scan_button.setEnabled(True)
            holder.pop("scan_worker", None)

        def scan():
            status = holder["widget"]._feature_status
            scan_button.setEnabled(False)
            status.setText("Scanning social sources…")
            worker = SocialDiscoveryWorker(getattr(self, "earning_pipeline", None))
            holder["scan_worker"] = worker
            worker.finished.connect(scan_finished)
            worker.start()

        scan_button.clicked.connect(scan)

        # ── Moltbook live feed + gated posting (Phase E, ARCH-ENG-088) ──
        # Agents and the human can both SEE the moltbook feed here, and the
        # agent can post/respond — but only through an approved approval item
        # (the social_post tool enforces the gate; a pending post is never
        # shown as sent).
        mb_row = QHBoxLayout()
        mb_load = QPushButton("🦞 Load Moltbook Feed")
        mb_load.setToolTip(
            "Read the live Moltbook feed (needs MOLTBOOK_API_KEY). Read-only.")
        mb_post = QPushButton("✍️ Post to Moltbook…")
        mb_post.setToolTip(
            "Draft a post/response. Opens a human approval first; the agent "
            "only posts after it is approved (social_post tool).")
        mb_row.addWidget(mb_load)
        mb_row.addWidget(mb_post)
        mb_row.addStretch(1)
        widget.layout().insertLayout(3, mb_row)

        mb_box = QGroupBox("Moltbook Activity (posts + our responses)")
        mb_lay = QVBoxLayout(mb_box)
        mb_table = QTableWidget()
        mb_table.setColumnCount(5)
        mb_table.setHorizontalHeaderLabels(
            ["Submolt", "Title", "Author", "Preview", "Link"])
        mb_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        mb_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        mb_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        mb_lay.addWidget(mb_table)

        # ARCH-ENG-129: the draft the operator reviews. The post body and
        # submolt are captured here and recorded in the approval item, so the
        # approval names the exact content social_post may publish.
        mb_draft = QHBoxLayout()
        mb_draft.addWidget(QLabel("Submolt:"))
        mb_submolt = QLineEdit()
        mb_submolt.setPlaceholderText("general")
        mb_submolt.setMaximumWidth(160)
        mb_draft.addWidget(mb_submolt)
        mb_draft.addStretch(1)
        mb_lay.addLayout(mb_draft)
        mb_body = QPlainTextEdit()
        mb_body.setPlaceholderText(
            "Write the post to publish. Approving it in the Approvals tab "
            "authorizes exactly this text — nothing else.")
        mb_body.setMaximumHeight(120)
        mb_lay.addWidget(mb_body)

        widget.layout().insertWidget(4, mb_box)
        holder["mb_table"] = mb_table
        holder["mb_load"] = mb_load
        holder["mb_post"] = mb_post
        holder["mb_body"] = mb_body
        holder["mb_submolt"] = mb_submolt

        def mb_feed_finished(result):
            mb_load.setEnabled(True)
            status = holder["widget"]._feature_status
            if not result.get("ok"):
                status.setText(f"Moltbook feed: {result.get('error', 'unavailable')}")
                mb_table.setRowCount(0)
                holder.pop("mb_worker", None)
                return
            rows = result.get("rows", [])
            mb_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate((row["submolt"], row["title"],
                                         row["author"], row["preview"],
                                         row["url"])):
                    mb_table.setItem(r, c, QTableWidgetItem(val))
            status.setText(f"Moltbook feed: {len(rows)} posts (read-only view)")

        def mb_load_feed():
            mb_load.setEnabled(False)
            holder["widget"]._feature_status.setText("Loading Moltbook feed…")
            worker = MoltbookFeedWorker(sort="hot", limit=25)
            holder["mb_worker"] = worker
            worker.finished.connect(mb_feed_finished)
            worker.start()

        mb_load.clicked.connect(mb_load_feed)

        def mb_start_post():
            # Route through the approval queue first. social_post only fires
            # once the item is APPROVED — a pending post is never a sent post.
            #
            # ARCH-ENG-129: the approval records the tool AND the content, so
            # the operator approves the exact post that will be published.
            # Before this the queued item carried no scope at all, and
            # `social_post` only checked `status == APPROVED` — a human who
            # reviewed one draft could have any other content published
            # (reproduced by executing it). An approval authorizes one action.
            try:
                from agents.safety.approval import (
                    ApprovalItem, ApprovalKind, HumanApprovalQueue,
                )
                body = (mb_body.toPlainText() or "").strip()
                submolt = (mb_submolt.text() or "").strip() or "general"
                if not body:
                    holder["widget"]._feature_status.setText(
                        "Write the post body first — an empty post cannot be "
                        "approved or published.")
                    return
                item = HumanApprovalQueue.instance().enqueue(ApprovalItem(
                    kind=ApprovalKind.SUBMISSION,
                    title=f"Post to Moltbook /m/{submolt}",
                    description=(
                        "Publish this post to the Moltbook social network via "
                        "the social_post tool. The post will still require "
                        "Moltbook's verification challenge to become visible."),
                    requested_by="social_activity_tab",
                    details={"tool": "social_post",
                             "arguments": {"network": "moltbook",
                                           "content": body},
                             "submolt": submolt},
                    payload={"tool": "social_post",
                             "arguments": {"network": "moltbook",
                                           "content": body}},
                ))
                holder["widget"]._feature_status.setText(
                    f"Moltbook post queued for approval (id {item.id}); "
                    "it posts only after you approve it.")
            except Exception as exc:
                holder["widget"]._feature_status.setText(
                    f"Could not queue Moltbook post: {exc}")

        mb_post.clicked.connect(mb_start_post)

        refresh()
        return widget

    def create_self_improvement_tab(self):
        """Show self-improvement learning history and pending code-patch proposals."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "earning_memory.db")
        holder = {}
        _QUERY = ("SELECT created_at, learning_type, confidence, insight "
                  "FROM learning_history ORDER BY created_at DESC LIMIT 100")

        def apply(rows, error):
            # Runs on the GUI thread (worker callback) — safe to touch widgets.
            table = holder["widget"]._feature_table
            status = holder["widget"]._feature_status
            if error:
                status.setText(f"Self-improvement history unavailable: {error}")
                table.setRowCount(0)
                return
            table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                for col_idx, value in enumerate(row):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(str(value or "")))
            recommendation = "Next action: collect a verified outcome before changing rankings."
            pipeline = getattr(self, "earning_pipeline", None)
            loop = getattr(pipeline, "learning_loop", None) if pipeline else None
            memory = getattr(loop, "memory", None) if loop else None
            dashboard = holder.get("dashboard")
            if memory is not None:
                try:
                    analytics = memory.learning_dashboard()
                    successful_terms = memory.get_successful_search_terms(3)
                    if successful_terms:
                        recommendation = (
                            "Next action: prioritize a new discovery using verified terms: "
                            + ", ".join(successful_terms)
                        )
                    if dashboard is not None:
                        lines = []
                        for name, value in analytics.items():
                            if isinstance(value, list):
                                rendered = f"{len(value)} row(s)"
                            elif isinstance(value, dict) and "error" in value:
                                rendered = f"unavailable ({value['error']})"
                            else:
                                rendered = str(value)
                            lines.append(f"{name}: {rendered[:180]}")
                        dashboard.setText("Learning analytics:\n" + "\n".join(lines))
                except Exception as exc:
                    recommendation = f"Learning recommendation unavailable: {exc}"
                    if dashboard is not None:
                        dashboard.setText(f"Learning analytics unavailable: {exc}")
            status.setText(
                f"{len(rows)} learning insights; {recommendation} "
                "All changes remain bounded and evidence-gated.")

        def refresh():
            # Run the SQLite read off the GUI thread so the tab never freezes
            # on the 5s poll or on first show.
            try:
                from gui.workers.db_query_worker import run_db_query
                run_db_query(db_path, _QUERY, apply, parent=holder.get("widget"))
            except Exception as exc:
                apply([], str(exc))

        widget = self._create_feature_monitor(
            "Self-Improvement Progress", ["Timestamp", "Learning Type", "Confidence", "Blueprint / Plan / Research / Action"],
            refresh)
        holder["widget"] = widget

        # ── Pending code-patch proposals (approval-gated) ─────────────────────
        # ARCH-ENG-306 (P-02): surface every read-only learning aggregation the
        # memory computes, not just the single next-action recommendation.
        dashboard_label = QLabel("Learning analytics: waiting for memory...")
        dashboard_label.setWordWrap(True)
        dashboard_label.setStyleSheet("color: #888; font-size: 11px;")
        widget.layout().addWidget(dashboard_label)
        holder["dashboard"] = dashboard_label

        patch_box = QGroupBox("Pending Code Patches (human approval required)")
        patch_lay = QVBoxLayout(patch_box)
        patch_status = QLabel("No pending code patches")
        patch_status.setWordWrap(True)
        patch_lay.addWidget(patch_status)
        patch_table = QTableWidget(0, 5)
        patch_table.setHorizontalHeaderLabels(
            ["ID", "Author", "Target", "Motivation", "Detail"])
        patch_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        patch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        patch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        patch_lay.addWidget(patch_table, stretch=1)

        btn_lay = QHBoxLayout()
        approve_btn = QPushButton("✅ Approve & Apply")
        approve_btn.setToolTip("Approve the selected patch, then back up, apply, verify, and roll back on failure.")
        deny_btn = QPushButton("❌ Decline")
        deny_btn.setToolTip("Decline the selected patch; no file is touched.")
        btn_lay.addWidget(approve_btn)
        btn_lay.addWidget(deny_btn)
        btn_lay.addStretch(1)
        patch_lay.addLayout(btn_lay)
        widget.layout().addWidget(patch_box)

        def _code_patch_service():
            services = getattr(self, "_earning_services", None)
            if services is None:
                return None
            return getattr(services, "code_patch_service", None)

        def _refresh_patches():
            svc = _code_patch_service()
            if svc is None:
                patch_status.setText("Self-improvement disabled or service unavailable.")
                patch_table.setRowCount(0)
                return
            queue = getattr(svc, "approval_queue", None)
            pending = queue.pending() if queue is not None else []
            patch_table.setRowCount(len(pending))
            for row_idx, item in enumerate(pending):
                details = item.details or {}
                values = (
                    item.id,
                    item.requested_by,
                    details.get("target_path", ""),
                    item.title,
                    item.description,
                )
                for col_idx, value in enumerate(values):
                    patch_table.setItem(row_idx, col_idx, QTableWidgetItem(str(value or "")))
            patch_status.setText(
                f"{len(pending)} pending code patch(es); approve to back up, apply, verify, and roll back on failure.")

        def _selected_patch_id():
            sel = patch_table.selectedItems()
            if not sel:
                return None
            return patch_table.item(sel[0].row(), 0).text()

        def _on_approve():
            patch_id = _selected_patch_id()
            svc = _code_patch_service()
            if not patch_id or svc is None:
                return
            from agents.services.self_improvement_commands import approve_and_apply
            result = approve_and_apply(svc, patch_id)
            patch_status.setText(
                f"Apply result: {result.get('status', result.get('ok'))} — {result.get('detail', '')}")
            _refresh_patches()
            refresh()

        def _on_deny():
            patch_id = _selected_patch_id()
            svc = _code_patch_service()
            if not patch_id or svc is None:
                return
            from agents.services.self_improvement_commands import decline_patch
            result = decline_patch(svc, patch_id)
            patch_status.setText(f"Decline result: {result.get('status')}")
            _refresh_patches()

        approve_btn.clicked.connect(_on_approve)
        deny_btn.clicked.connect(_on_deny)

        # Refresh patches on the same visibility-aware cadence as the table.
        from gui.builders.refresh_coordinator import refresh_coordinator
        coordinator = refresh_coordinator()
        patch_key = f"self-improve-patches:{id(widget)}"
        coordinator.register(patch_key, _refresh_patches, 5000)

        def _show(event):
            _refresh_patches()
            coordinator.set_visible(patch_key, True)
            QWidget.showEvent(widget, event)

        def _hide(event):
            coordinator.set_visible(patch_key, False)
            QWidget.hideEvent(widget, event)

        widget.showEvent = _show
        widget.hideEvent = _hide

        refresh()
        _refresh_patches()
        return widget

    def create_autonomous_learning_tab(self):
        """Show autonomous run and stage progress from the durable run store."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "autonomous_runs.db")
        portfolio_path = os.path.join(os.path.dirname(db_path), "opportunity_portfolio.db")
        holder = {}
        _QUERY = ("SELECT run_id, opportunity_id, status, success, updated_at, decision_reason "
                  "FROM autonomous_runs ORDER BY updated_at DESC LIMIT 100")

        def _feedback_summary() -> str:
            """Per-platform outcome summary from recorded runs (Phase C).

            Read-only aggregation over the run store joined to the portfolio's
            platform. Runs off the GUI thread (called from apply via the worker
            path); returns '' when unavailable so the tab degrades gracefully.
            """
            try:
                import sqlite3
                from agents.earning.strategy_feedback import StrategyFeedback

                class _Store:
                    def list_runs(self, limit=100):
                        if not os.path.exists(db_path):
                            return []
                        with sqlite3.connect(db_path) as conn:
                            conn.row_factory = sqlite3.Row
                            rows = conn.execute(
                                "SELECT opportunity_id, success, paid, payment_amount, "
                                "decision FROM autonomous_runs "
                                "ORDER BY updated_at DESC LIMIT ?", (limit,))
                            return [dict(r) for r in rows]

                def _resolve(opportunity_id: str) -> str:
                    if not opportunity_id or not os.path.exists(portfolio_path):
                        return ""
                    try:
                        with sqlite3.connect(portfolio_path) as conn:
                            row = conn.execute(
                                "SELECT platform FROM opportunity_portfolio "
                                "WHERE opportunity_id = ?", (opportunity_id,)).fetchone()
                            return (row[0] or "") if row else ""
                    except Exception:
                        return ""

                fb = StrategyFeedback(_Store(), _resolve)
                lines = fb.summary_lines()
                if not lines:
                    return ""
                return "Strategy feedback (recorded outcomes): " + " | ".join(lines)
            except Exception:
                return ""

        def _compute_feedback_async():
            """Compute the per-platform feedback summary OFF the GUI thread and
            cache it for apply() to read (never blocks the 5s poll)."""
            import threading

            def _work():
                summary = _feedback_summary()
                holder["feedback"] = summary

            t = threading.Thread(target=_work, daemon=True)
            t.start()

        def apply(rows, error):
            # Runs on the GUI thread (worker callback) — safe to touch widgets.
            table = holder["widget"]._feature_table
            status = holder["widget"]._feature_status
            if error:
                status.setText(f"Autonomous learning history unavailable: {error}")
                table.setRowCount(0)
                return
            table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                for col_idx, value in enumerate(row):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(str(value or "")))
            if not rows:
                next_action = "Next action: start a gated discovery/evaluation cycle."
            else:
                statuses = {str(row[2] or "").lower() for row in rows}
                if "await_approval" in statuses or "pending_approval" in statuses:
                    next_action = "Next action: review the pending human approval."
                elif "failed" in statuses:
                    next_action = "Next action: inspect the failed stage and retry only after its cause is understood."
                elif "completed_unpaid" in statuses:
                    next_action = "Next action: verify payment evidence before treating the run as successful."
                else:
                    next_action = "Next action: run the next eligible opportunity through evaluation."
            # Use the cached (off-thread-computed) feedback; kick off a refresh
            # for the next poll if it isn't ready yet.
            feedback = holder.get("feedback") or ""
            if not feedback:
                _compute_feedback_async()
            suffix = ("  " + feedback) if feedback else ""
            status.setText(
                f"{len(rows)} durable autonomous runs; {next_action} "
                "Learning cannot bypass evidence or authorization." + suffix)

        def refresh():
            # Run the SQLite read off the GUI thread so the tab never freezes
            # on the 5s poll or on first show.
            try:
                from gui.workers.db_query_worker import run_db_query
                run_db_query(db_path, _QUERY, apply, parent=holder.get("widget"))
            except Exception as exc:
                apply([], str(exc))

        widget = self._create_feature_monitor(
            "Autonomous Learning Progress",
            ["Run", "Opportunity", "Status", "Success", "Updated", "Decision / Action"],
            refresh)
        holder["widget"] = widget
        refresh()
        return widget

    def refresh_diagnostics(self, force: bool = False):
        """Refresh sanitized health and reconciliation data without mutations.

        ARCH-ENG-221: THIS USED TO PASS `refresh_health=True` UNCONDITIONALLY.

        `DualBrainRuntime.list_models` has a 10 s TTL on its health cache
        (`dual_brain.py:1149`, added by ARCH-ENG-188 precisely so the UI would
        not re-probe on every repaint). Passing `refresh=True` bypassed that TTL
        entirely -- so the 5 s diagnostics timer forced a fresh probe twice per
        TTL, each one `urllib.urlopen(timeout=3)` per role ON THE GUI THREAD
        (`HEALTH_TIMEOUT_S = 3.0`, `dual_brain.py:877`). Against a llama-server
        that has accepted the socket but not yet loaded the model, that is up to
        a 6-second frozen window every 5 seconds.

        Note the shape of the defect: it is the SAME one ARCH-ENG-179, -185 and
        -188 were raised for, inverted. Those cached an observation and presented
        it as current fact; this discarded the expiry that was built to stop it,
        and paid for the probe on the thread that must never block.

        `force=True` remains available for the explicit "Refresh Diagnostics"
        button, where the operator has asked for live data and can wait.
        """
        if not hasattr(self, "diagnostics_health_table"):
            return
        try:
            runtime = getattr(self, "dual_brain_runtime", None)
            snapshot = (runtime.snapshot(refresh_health=True) if force else
                        runtime.snapshot()) if runtime is not None else {}
        except Exception as exc:
            snapshot = {}
            self.log_signal.emit(f"[Diagnostics] Provider health unavailable: {exc}")

        health_table = self.diagnostics_health_table
        health_table.setRowCount(0)
        for key in ("big", "small"):
            health = snapshot.get(key, {})
            row = health_table.rowCount()
            health_table.insertRow(row)
            values = [
                health.get("display_name", key.title()),
                health.get("provider", "unknown"),
                health.get("model", "") or "unselected",
                "yes" if health.get("reachable") else "no",
                health.get("model_status", "unknown"),
                str(health.get("model_count", 0)),
                f"{health.get('latency_ms', 0)} ms",
            ]
            for column, value in enumerate(values):
                health_table.setItem(row, column, QTableWidgetItem(str(value)))

        try:
            from agents.runtime.performance import telemetry
            perf = telemetry.snapshot()
            self.diagnostics_performance_label.setText(
                f"Startup {perf['startup_ms'] or 'n/a'} ms | "
                f"CPU {perf['process_cpu_ratio']:.1%} | "
                f"Python memory {perf['python_memory_current_bytes'] / 1048576:.1f} MiB | "
                f"LLM calls {perf['model_calls']} "
                f"(avg {perf['avg_model_latency_ms']:.1f} ms, "
                f"errors {perf['model_errors']}, retries {perf['retries']}) | "
                f"Prompt {perf['prompt_chars']} chars / {perf['prompt_tokens']} est. tokens | "
                f"GUI batches {perf['gui_updates']}"
            )
        except Exception as exc:
            self.diagnostics_performance_label.setText(
                f"Performance telemetry unavailable: {exc}")

        root = getattr(self, "_composition_root", None)
        report = getattr(root, "reconciliation_report", None)
        if root is not None:
            try:
                from agents.core.state_reconciliation import reconcile_many
                opportunity_ids = {
                    state.get("opportunity_id")
                    for state in root.lifecycle.get_all_states()
                    if state.get("opportunity_id")
                }
                opportunity_ids.update(
                    entry.opportunity_id for entry in root.portfolio.list_all()
                    if getattr(entry, "opportunity_id", None)
                )
                opportunity_ids.update(
                    root.pipeline.evidence_store.subject_ids("opportunity")
                )
                report = reconcile_many(
                    opportunity_ids,
                    lifecycle=root.lifecycle,
                    portfolio=root.portfolio,
                    evidence_store=root.pipeline.evidence_store,
                    accounting=root.pipeline.accounting,
                    run_store=root.run_store,
                )
                root.reconciliation_report = report
            except Exception as exc:
                self.log_signal.emit(f"[Diagnostics] Reconciliation unavailable: {exc}")
        conflicts = list(getattr(report, "conflicts", []) or [])
        generated_at = getattr(report, "generated_at", None)
        stamp = (datetime.fromtimestamp(generated_at).strftime("%Y-%m-%d %H:%M:%S")
                 if generated_at else "unknown")
        self.diagnostics_reconciliation_label.setText(
            f"{len(conflicts)} conflict(s) | generated {stamp} | read-only")
        conflict_table = self.diagnostics_conflict_table
        conflict_table.setRowCount(0)
        for conflict in conflicts:
            row = conflict_table.rowCount()
            conflict_table.insertRow(row)
            values = [
                getattr(conflict, "severity", "unknown"),
                getattr(conflict, "opportunity_id", ""),
                getattr(conflict, "category", ""),
                getattr(conflict, "message", ""),
                "yes" if getattr(conflict, "requires_human_review", True) else "no",
                ", ".join(sorted(getattr(conflict, "sources", {}).keys())),
            ]
            for column, value in enumerate(values):
                conflict_table.setItem(row, column, QTableWidgetItem(str(value)))

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

    # ARCH-ENG-278 (AW-03): this is the orchestrator left by splitting the
    # former 870-line method. Each section is a `_build_*` helper below.
    def create_settings_tab(self):
        # v2.0.33: per-provider main/chat role control. Defined up-front so both
        # the LLM Providers group (OpenAI/Anthropic) and the _prov_row helper can
        # use them without a forward-reference error.
        from gui.widgets.provider_config_widget import ProviderConfigWidget, CloudProviderPanel, LocalProviderPanel
        
        from app.effects import env_bool as _env_bool

        def _seed_fx(name, cb):
            cb.blockSignals(True)
            cb.setChecked(_env_bool(f"MRBOT_FX_{name}", True))
            cb.blockSignals(False)

        scroll  = QScrollArea()
        scroll.setWidgetResizable(True)
        inner   = QWidget()
        scroll.setWidget(inner)
        lay     = QVBoxLayout(inner)

        # ARCH-ENG-200: THE RE-HOMING CONTAINER.
        #
        # Three group boxes below -- `cloudg`, `localg` and `llamacppg` -- are
        # built and NEVER added to a layout, because `ProviderConfigWidget` is
        # the visible surface for those sections. They still had to exist
        # because `save_settings` reads attributes off their widgets (the
        # `*_key_edit` / `*_base_edit` fields).
        #
        # An UNPARENTED QWidget in Qt is a TOP-LEVEL WINDOW. So these were not
        # merely invisible -- they were stray windows titled "Cloud Providers",
        # "Local Providers" and "llama.cpp (local dual-brain)", competing for
        # the taskbar and the alt-tab list.
        #
        # NOTE THE ARGUMENT ORDER: PySide6's signature is QGroupBox(title, parent).
        # QGroupBox(parent, title) also re-homes the widget but SILENTLY DROPS
        # THE TITLE -- it binds the parent to the title slot and leaves title()
        # empty. That was the first attempt here, and the regression suite caught
        # it because the titles are what diagnostics and the object tree show.
        #
        # Re-homing them under one parented, hidden container fixes that without
        # changing a single value: `QWidget()` with a parent is an ordinary child
        # object, not a window. Nothing is laid out, so nothing is displayed, and
        # every `self.<attr>` the save path reads still resolves to a live widget.
        #
        # ARCH-ENG-275 (AB-01): the fourth box, `ollama_box`, is GONE rather
        # than re-homed. It was the hidden second writer of
        # `OLLAMA_MAIN_MODEL` / `OLLAMA_CHAT_MODEL` (ARCH-ENG-196 could only make
        # the persisted value win over it) and the only reader of a hidden role
        # and hide toggle. `ProviderConfigWidget` persists the role and the
        # model the moment the operator changes them, so there is no value left
        # that only the hidden box could supply. Nothing here fetches models
        # either: ARCH-ENG-193 recorded that the old live population had to stay
        # on a background thread because a blocking fetch froze the Settings
        # tab, and with the hidden combos gone no fetch runs at build time.
        rehome = QWidget(inner)          # parented -> a child, never a window
        rehome.setObjectName("settingsUnrenderedSections")
        rehome.setVisible(False)         # and never shown even if a layout changes
        rehome_layout = QVBoxLayout(rehome)
        # NOTE: `rehome_layout` is intentionally never added to `lay`. Adding
        # it would re-introduce the duplicate sections this container exists to
        # retire; its only job is to give the four group boxes a parent.
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        # Provider Configuration (hot-reload, no restart needed)
        # Parent immediately so the provider surface cannot become a separate
        # top-level Qt window while the Settings tab is being assembled.
        provider_config = ProviderConfigWidget(inner)
        provider_config.provider_changed.connect(self._on_provider_widget_changed)
        lay.addWidget(provider_config)

        # Quick-save at the TOP as well as the bottom: the bottom "Save All
        # Settings" sits deep inside the scroll area, so a user who changed one
        # toggle had to scroll to the very end to apply it. Same handler, same
        # values — this is just a second, always-visible shortcut.
        top_save = QPushButton("💾 Save All Settings")
        top_save.setObjectName("settingsQuickSaveButton")
        top_save.setToolTip("Save settings immediately (same as the button at the bottom)")
        top_save.clicked.connect(self.save_settings)
        lay.addWidget(top_save)
        self._build_registration_group(lay)
        self._build_provider_sections(lay, rehome, rehome_layout)
        self._build_performance_group(lay)
        self._build_llm_group(lay)
        self._build_rate_group(lay)
        self._build_model_info_group(lay)
        self._build_security_group(lay)
        self._build_feature_group(lay)
        self._build_pipeline_group(lay)
        self._build_payout_group(lay)
        self._build_appearance_group(lay, _seed_fx)
        self._build_cache_group(lay)

        sb = QPushButton("💾 Save All Settings")
        sb.clicked.connect(self.save_settings)
        lay.addWidget(sb)

        lay.addStretch()
        return scroll

    def _build_registration_group(self, lay):
        # Registration (identity only — wallet/cashApp moved to Payout Destinations below)
        rg = QGroupBox("Agent Registration")
        rl = QFormLayout(rg)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setVerticalSpacing(8)
        self.name_edit   = QLineEdit(os.getenv("AGENT_NAME", "CodeSelfLearnBot"))
        self.user_edit   = QLineEdit(os.getenv("AGENT_USERNAME", "codeselflearn-2026"))
        rl.addRow("Agent Name:",    self.name_edit)
        rl.addRow("Username:",      self.user_edit)
        rb = QPushButton("Register")
        rb.clicked.connect(self.register_autonomous)
        rl.addRow(rb)
        # v2.0.34ag (A5): reuse the top-level status_label (created in __init__).
        if not hasattr(self, "status_label") or self.status_label is None:
            self.status_label = QLabel("Agent status: Not registered")
        self.status_label.setText("Agent status: Not registered")
        rl.addRow(self.status_label)
        lay.addWidget(rg)

    def _build_provider_sections(self, lay, rehome, rehome_layout):
        # v2.0.33: per-provider main/chat role control. Defined up-front so both
        # the LLM Providers group (OpenAI/Anthropic) and the _prov_row helper can
        # use them without a forward-reference error.
        from gui.widgets.provider_config_widget import ProviderConfigWidget, CloudProviderPanel, LocalProviderPanel
        
        ROLE_ITEMS = ["Both", "Main only", "Chat only", "Disabled"]

        # F4 consolidation: the role reader lives in ONE place
        # (provider_config_widget.role_from_env). This closure used to be a
        # second copy of that logic, which is how the two panels drift — the
        # Role dropdown would then show different answers depending on which
        # one built it. Behaviour is unchanged (see role_from_env's docstring).
        def _role_from_env(env_prefix):
            from gui.widgets.provider_config_widget import role_from_env
            return role_from_env(env_prefix)

        # ARCH-ENG-203: this closure WAS the correct three-state parser, and it
        # was also a private copy of logic that belongs to `app.effects`, the
        # module that owns these settings. It is now a one-line delegation so
        # the semantics live in exactly one place. The two ad-hoc parsers below
        # (`.lower() == "true"` and `.lower() != "false"`) were seeded from the
        # same settings and disagreed with each other; see `env_bool`.
        from app.effects import env_bool as _env_bool

        # v2.0.26: providers grouped into CLOUD and LOCAL for clarity.
        # v2.0.32: model field is now a QComboBox (editable) + Fetch button that
        # pulls the provider's models w/ pricing from app.provider_models.py.
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
        # ARCH-ENG-200: parented, so this is a child object rather than a
        # stray top-level window. See the re-homing container above.
        cloudg = QGroupBox("Cloud Providers", rehome)
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

        # Nous Research (portal.nousresearch.com). Previously supported by the
        # backend adapter registry (worker_provider_mixin registers "nous") but
        # absent from this UI and from save_settings(), so it could never be
        # disabled and was retried forever as a fallback. That produced an
        # endless "trying nous -> 404 -> trying big-brain" loop whenever the
        # local brain was down.
        self.nous_key, self.nous_base, self.nous_model, self.nous_chat, self.nous_role, self.nous_fetch, self.nous_hide = \
            _prov_row(cloudl, "NOUS", "Nous Research", "https://inference-api.nousresearch.com/v1", "hermes-4-405b")
        self.nous_note = QLabel("Use for: Nous Research Hermes models via the Nous portal. Cost: paid per token (portal credits). Leave the role Disabled unless you have a NOUS_API_KEY.")
        self.nous_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((self.nous_note, "caption", "font-size:10px;padding-top:3px;"))
        self.nous_note.setWordWrap(True)
        cloudl.addWidget(self.nous_note)
        # ProviderConfigWidget above is the single visible provider surface.
        # Keep these controls constructed for existing save/fetch code, but do
        # not render a second copy of the provider list.

        # ── Local Providers (OpenAI-compatible local servers) ──────────────
        # ARCH-ENG-200: parented, so this is a child object rather than a
        # stray top-level window. See the re-homing container above.
        localg = QGroupBox("Local Providers", rehome)
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
        # ARCH-ENG-200: parented, so this is a child object rather than a
        # stray top-level window. See the re-homing container above.
        llamacppg = QGroupBox("llama.cpp (local dual-brain)", rehome)
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


        tb = QPushButton("Test Connection")
        tb.clicked.connect(self.test_api_connection)
        lay.addWidget(tb)

    def _build_performance_group(self, lay):
        # v2.0.34ag (A2): LLM Parameters + Model Info moved to the "Model & GPU" tab.
        perfg = QGroupBox("Performance & Cache")
        perfl = QFormLayout(perfg)
        perfl.setContentsMargins(12, 12, 12, 12)
        perfl.setVerticalSpacing(8)
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
        
        # Cache statistics display
        self.cache_stats_label = QLabel("Loading cache stats…")
        self.cache_stats_label.setStyleSheet(f"color:{self._t('accent')};font-size:10px;padding:4px;")
        self.cache_stats_label.setWordWrap(True)
        perfl.addRow("Cache Stats:", self.cache_stats_label)
        cache_refresh_btn = QPushButton("Refresh Stats")
        cache_refresh_btn.clicked.connect(self._refresh_cache_stats)
        perfl.addRow(cache_refresh_btn)
        # Populate cache stats on first build
        QTimer.singleShot(200, self._refresh_cache_stats)
        lay.addWidget(perfg)

    def _build_llm_group(self, lay):
        # ── LLM Parameters (relocated from the removed "Model & GPU" tab) ──
        # Generic LLM controls that are still relevant with llama.cpp as the
        # default provider. Widget names are kept identical so save_settings and
        # _refresh_model_info keep working unmodified (v2.0.36w).
        llmg = QGroupBox("LLM Parameters")
        llml = QFormLayout(llmg)
        llml.setContentsMargins(12, 12, 12, 12)
        llml.setVerticalSpacing(8)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(128, 16384)
        self.max_tokens_spin.setValue(int(os.getenv("MAX_TOKENS", 1024)))
        llml.addRow("Max Tokens:", self.max_tokens_spin)
        max_tokens_note = QLabel("Maximum length of generated responses. Higher = longer answers but slower.")
        max_tokens_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((max_tokens_note, "caption", "font-size:10px;padding-top:3px;"))
        max_tokens_note.setWordWrap(True)
        llml.addRow(max_tokens_note)

        # ── Dialogue token limits (per brain) ──────────────────────────────
        # Independent of the generic Max Tokens above. Dialogue is the tab where
        # the two brains converse; a longer reply budget suits deep planning and
        # a shorter one suits quick banter. Each brain has its own control so the
        # big/small models can be tuned separately.
        self.dialogue_tokens_big_spin = QSpinBox()
        self.dialogue_tokens_big_spin.setRange(128, 32768)
        self.dialogue_tokens_big_spin.setSingleStep(128)
        self.dialogue_tokens_big_spin.setValue(int(os.getenv("DIALOGUE_MAX_TOKENS_BIG", "1024")))
        llml.addRow("Dialogue tokens — Big Brain:", self.dialogue_tokens_big_spin)

        self.dialogue_tokens_small_spin = QSpinBox()
        self.dialogue_tokens_small_spin.setRange(128, 32768)
        self.dialogue_tokens_small_spin.setSingleStep(128)
        self.dialogue_tokens_small_spin.setValue(int(os.getenv("DIALOGUE_MAX_TOKENS_SMALL", "512")))
        llml.addRow("Dialogue tokens — Small Brain:", self.dialogue_tokens_small_spin)

        # Auto mode scales the per-brain budget with the model's configured
        # context: a large-context model gets a bigger reply budget, a small one
        # stays tight. The manual values above become the floors in auto mode.
        self.dialogue_auto_tokens_cb = QCheckBox(
            "Auto-scale dialogue tokens with model context length")
        self.dialogue_auto_tokens_cb.setChecked(
            os.getenv("DIALOGUE_AUTO_TOKENS", "true").lower() in ("1", "true", "yes"))
        llml.addRow("", self.dialogue_auto_tokens_cb)

        dialogue_tokens_note = QLabel(
            "Reply length budget for the Dialogue tab only. Auto-scale derives the "
            "budget from each model's configured context (longer for large-context "
            "models); the values above act as the minimum. Raise them for long, "
            "detailed exchanges or lower them for short ones.")
        dialogue_tokens_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((dialogue_tokens_note, "caption", "font-size:10px;padding-top:3px;"))
        dialogue_tokens_note.setWordWrap(True)
        llml.addRow(dialogue_tokens_note)

        # Temperature control
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(float(os.getenv("LLM_TEMPERATURE", 0.7)))
        llml.addRow("Temperature:", self.temperature_spin)
        temp_note = QLabel("Controls randomness. 0 = deterministic, 2 = very creative.")
        temp_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((temp_note, "caption", "font-size:10px;padding-top:3px;"))
        temp_note.setWordWrap(True)
        llml.addRow(temp_note)
        
        # Top-P control
        self.top_p_spin = QDoubleSpinBox()
        self.top_p_spin.setRange(0.0, 1.0)
        self.top_p_spin.setSingleStep(0.05)
        self.top_p_spin.setValue(float(os.getenv("LLM_TOP_P", 0.9)))
        llml.addRow("Top-P:", self.top_p_spin)
        topp_note = QLabel("Nucleus sampling. 0.9 = consider top 90% of probability mass.")
        topp_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((topp_note, "caption", "font-size:10px;padding-top:3px;"))
        topp_note.setWordWrap(True)
        llml.addRow(topp_note)
        
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

    def _build_rate_group(self, lay):
        # ── Provider Rate & Budget (Phase F, ARCH-ENG-091) ──
        # Per-provider calls/sec + daily call cap so a cloud subscription/budget
        # isn't burned too fast. Local providers are hardware-bound (no $ cap
        # unless the operator opts in). Values persist via save_settings and the
        # runtime reads <PROVIDER>_RATE_PER_SEC / <PROVIDER>_MAX_CALLS_PER_DAY.
        from agents.safety.provider_rate_limiter import is_local_provider
        prg = QGroupBox("Provider Rate & Budget")
        prl_box = QFormLayout(prg)
        prl_box.setContentsMargins(12, 12, 12, 12)
        prl_box.setVerticalSpacing(8)
        self._provider_rate_edits = {}
        self._provider_cap_edits = {}
        _PROVIDERS = ("openai", "anthropic", "groq", "openrouter", "nous",
                      "deepseek", "gemini", "mistral", "ollama")
        for prov in _PROVIDERS:
            up = prov.upper()
            rate_edit = QLineEdit()
            rate_edit.setPlaceholderText("calls/sec")
            cur_rate = os.getenv(f"{up}_RATE_PER_SEC", "").strip()
            rate_edit.setText(cur_rate if cur_rate else
                              ("2.0" if is_local_provider(prov) else "1.0"))
            cap_edit = QLineEdit()
            cap_edit.setPlaceholderText("0 = unlimited")
            cur_cap = os.getenv(f"{up}_MAX_CALLS_PER_DAY", "").strip()
            cap_edit.setText(cur_cap if cur_cap else
                             ("0" if is_local_provider(prov) else "500"))
            tag = " (local, hardware-bound)" if is_local_provider(prov) else ""
            prl_box.addRow(f"{prov}{tag} — rate/sec:", rate_edit)
            prl_box.addRow(f"{prov} — max calls/day:", cap_edit)
            self._provider_rate_edits[up] = rate_edit
            self._provider_cap_edits[up] = cap_edit
        prb_note = QLabel(
            "Per-provider rate limit (calls/sec) and daily call cap. Cloud "
            "providers are capped by default so a budget lasts; local providers "
            "are hardware-bound (0 = unlimited) unless you set a cap. Over-limit "
            "calls are refused and the bot falls back to the next provider.")
        prb_note.setWordWrap(True)
        prb_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((prb_note, "caption", "font-size:10px;padding-top:3px;"))
        prl_box.addRow(prb_note)
        lay.addWidget(prg)

    def _build_model_info_group(self, lay):
        # ── Model Info (relocated from the removed "Model & GPU" tab) ──
        infog = QGroupBox("Model Info")
        infol = QVBoxLayout(infog)
        infol.setContentsMargins(12, 12, 12, 12)
        infol.setSpacing(6)
        self.model_info_browser = QTextEdit()
        self.model_info_browser.setMinimumHeight(120)
        self.model_info_browser.setMaximumHeight(180)
        self.model_info_browser.setReadOnly(True)
        infol.addWidget(self.model_info_browser)
        
        btn_row = QHBoxLayout()
        self.refresh_model_info_btn = QPushButton("Refresh Model Info")
        self.refresh_model_info_btn.clicked.connect(
            lambda: self._refresh_model_info(live=True))
        btn_row.addWidget(self.refresh_model_info_btn)
        self.copy_model_info_btn = QPushButton("Copy to Clipboard")
        self.copy_model_info_btn.clicked.connect(self._copy_model_info_to_clipboard)
        btn_row.addWidget(self.copy_model_info_btn)
        btn_row.addStretch()
        infol.addLayout(btn_row)
        
        info_note = QLabel(
            "Shows the type of each selected model: dense vs Mixture-of-Experts (MoE), "
            "approximate parameter count, context window, and price.")
        info_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((info_note, "caption", "font-size:10px;padding-top:3px;"))
        info_note.setWordWrap(True)
        infol.addWidget(info_note)
        lay.addWidget(infog)
        # PERF: defer model info refresh to avoid blocking tab paint
        QTimer.singleShot(100, lambda: self._refresh_model_info(live=False))

    def _build_security_group(self, lay):
        # Security Settings with explanations
        secg = QGroupBox("Security")
        secl = QFormLayout(secg)
        secl.setContentsMargins(12, 12, 12, 12)
        secl.setVerticalSpacing(8)
        # ARCH-ENG-202: show what is ACTUALLY blocked, not a local guess.
        #
        # This used to default to a hardcoded four entries while
        # `worker_safety` enforced fourteen, so the Settings screen understated
        # the protection by ten files -- `passwd`, `shadow`, `sudoers`, `id_dsa`,
        # `hosts`, `.bashrc` and four more were invisible. An operator reading
        # this screen had no way to know they were blocked.
        #
        # The correct default is the runtime's own effective set. `os.getenv`
        # alone is not enough either: the value is a floor PLUS operator
        # additions, and the screen must show both.
        from agents.brains.worker_safety import (effective_blocklist_text,
                                                 effective_mime_text,
                                                 refresh_from_env)
        refresh_from_env()   # .env may have been reloaded since import
        self.blocklist_edit = QLineEdit(effective_blocklist_text())
        secl.addRow("Blocklist (comma sep):", self.blocklist_edit)
        blocklist_note = QLabel(
            "Files the agent will never read. These protected entries cannot be "
            "removed — anything you add here is blocked on top of them.")
        blocklist_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((blocklist_note, "caption", "font-size:10px;padding-top:3px;"))
        blocklist_note.setWordWrap(True)
        secl.addRow(blocklist_note)

        self.blocked_mime_edit = QLineEdit(effective_mime_text())
        secl.addRow("Blocked MIME (comma):", self.blocked_mime_edit)
        mime_note = QLabel(
            "Blocked file types. Prevents reading binaries or executables. "
            "Same rule — the built-in types cannot be removed.")
        mime_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((mime_note, "caption", "font-size:10px;padding-top:3px;"))
        mime_note.setWordWrap(True)
        secl.addRow(mime_note)
        lay.addWidget(secg)

    def _build_feature_group(self, lay):
        # Optional capability boundaries. These are explicit operator controls;
        # risky features remain disabled unless the user opts in and saves.
        featureg = QGroupBox("Optional Features")
        featurel = QFormLayout(featureg)
        featurel.setContentsMargins(12, 12, 12, 12)
        featurel.setVerticalSpacing(8)
        from agents.core.feature_flags import feature_enabled
        optional_features = (
            ("live_trading", "Enable live trading and portfolio tabs"),
            ("crypto_operations", "Enable crypto operations"),
            ("airdrop_claiming", "Enable airdrop discovery and claiming"),
            ("defi_scanning", "Enable DeFi scanning"),
            ("social_automation", "Enable social-platform automation"),
            ("self_improvement", "Enable self-improvement"),
            ("autonomous_learning", "Enable autonomous learning"),
        )
        self.feature_flag_checks = {}
        for feature_name, label in optional_features:
            check = QCheckBox()
            check.setChecked(feature_enabled(feature_name))
            self.feature_flag_checks[feature_name] = check
            featurel.addRow(label + ":", check)
        # Self-improvement monitor cadence (minutes). Only meaningful when
        # self-improvement is enabled; the background monitor re-verifies
        # applied patches on this interval.
        self.self_improve_monitor_spin = QSpinBox()
        self.self_improve_monitor_spin.setRange(1, 1440)
        self.self_improve_monitor_spin.setValue(
            int(os.getenv("MRBOT_SELF_IMPROVE_MONITOR_MINUTES", "30")))
        self.self_improve_monitor_spin.setSuffix(" min")
        featurel.addRow("Self-improve monitor interval:", self.self_improve_monitor_spin)

        # Web discovery opt-in (Phase E, ARCH-ENG-087). Enables the generic web
        # discovery source (ddgs/tavily/brave) for real feed/web search. OFF by
        # default (human-review-gated). This mirrors the toggle in the
        # Opportunities tab; both persist ALLOW_WEB_DISCOVERY to .env and the
        # runtime reads that env in agents/discovery/web_discovery.py.
        web_on = os.getenv("ALLOW_WEB_DISCOVERY", "false").lower() in ("1", "true", "yes")
        self.settings_web_discovery_check = QCheckBox()
        self.settings_web_discovery_check.setChecked(web_on)
        self.settings_web_discovery_check.setToolTip(
            "Enable the generic web discovery source (ddgs/tavily/brave) for "
            "real web/feed discovery. Persists ALLOW_WEB_DISCOVERY to .env. "
            "Also available in the Opportunities tab.")
        featurel.addRow("Enable web discovery:", self.settings_web_discovery_check)

        feature_note = QLabel(
            "Disabled features do not load their optional adapters. Saving a "
            "change may add or remove related tabs after restart."
        )
        feature_note.setWordWrap(True)
        feature_note.setStyleSheet(
            f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((feature_note, "caption", "font-size:10px;padding-top:3px;"))
        featurel.addRow(feature_note)
        lay.addWidget(featureg)

    def _build_pipeline_group(self, lay):
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
        # ARCH-ENG-238 (AW-02): read the variable through the ONE canonical
        # env parser. The old inline `.lower() == "true"` disagreed with
        # `app/action_pipeline.py` (env_bool): for the perfectly reasonable
        # hand-written `PIPELINE_ALLOW_SELF_IMPROVE=1`, the checkbox rendered
        # UNCHECKED while the agent was permitted to modify its own code. The
        # write side (stateChanged -> "true"/"false") is unchanged and remains
        # readable by every parser.
        from app.effects import env_bool
        self.pipeline_allow_selfimprove_check.setChecked(
            env_bool("PIPELINE_ALLOW_SELF_IMPROVE", False))
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

    def _build_payout_group(self, lay):
        # Payout Settings with explanations
        payg = QGroupBox("Payout Destinations")
        payl = QFormLayout(payg)
        payl.setContentsMargins(12, 12, 12, 12)
        payl.setVerticalSpacing(8)
        self.cashapp_payout_edit = QLineEdit(os.getenv("CASHAPP_TAG", ""))
        payl.addRow("Cash App tag:", self.cashapp_payout_edit)
        self.solana_payout_edit = QLineEdit(os.getenv("ATOMIC_SOLANA_ADDRESS", ""))
        payl.addRow("Solana address:", self.solana_payout_edit)
        payout_note = QLabel("Auto-payout: agent earnings route to Cash App first, then Solana wallet for on-chain storage.")
        payout_note.setStyleSheet(f"color:{self._t('caption')};font-size:10px;padding-top:3px;")
        self._themeable.append((payout_note, "caption", "font-size:10px;padding-top:3px;"))
        payout_note.setWordWrap(True)
        payl.addRow(payout_note)
        lay.addWidget(payg)

    def _build_appearance_group(self, lay, _seed_fx):
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
        # ARCH-ENG-203: was `.lower() == "true"`, which reads "1", "yes" and
        # "on" as False while `effects.py` reads them as True -- so the toggle
        # could show unchecked while the feature was actually on.
        self.fx_compact.setChecked(
            _env_bool("MRBOT_FX_COMPACT_DENSITY", False))
        apl.addRow("Compact density:", self.fx_compact)
        self.fx_rounded = QCheckBox()
        # ARCH-ENG-203: was `.lower() != "false"`, which treats ANY unrecognised
        # value as True. A typo here would read as ON rather than falling back to
        # the documented default. It also meant this checkbox and the one four
        # lines above parsed the same .env format in opposite directions.
        self.fx_rounded.setChecked(
            _env_bool("MRBOT_FX_ROUNDED_CORNERS", True))
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

    def _build_cache_group(self, lay):
        # Cache Management
        cg = QGroupBox("Cache Management")
        cl = QVBoxLayout(cg)
        ccb = QPushButton("Clear File Cache")
        ccb.clicked.connect(self.clear_file_cache)
        cl.addWidget(ccb)
        lay.addWidget(cg)


    def create_opportunities_tab(self):
        """Create the Opportunities tab — browse, search, and manage discovered opportunities."""
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
        from PySide6.QtCore import QTimer
        from agents.earning.opportunity_portfolio import OpportunityPortfolio, canonical_portfolio_path
        from agents.runtime.context import register_component

        # Reuse the shared portfolio if the composition root (or any earlier
        # tab) already registered one, so Dialogue and this tab never read
        # different stores. Fall back to the canonical path otherwise.
        existing = getattr(self, "opportunity_portfolio", None)
        if existing is None:
            try:
                from agents.runtime.context import _component
                existing = _component("opportunity_portfolio")
            except Exception:
                existing = None
        if existing is None:
            self.opportunity_portfolio = OpportunityPortfolio(
                canonical_portfolio_path())
        else:
            self.opportunity_portfolio = existing
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
        self.opp_source_combo.addItems([
            "all", "upwork", "fiverr", "social", "microtask", "ugig",
            "moltbook", "airdrop", "defi", "web", "content", "dynamic",
        ])
        self.opp_source_combo.currentTextChanged.connect(self._reset_opportunity_page)
        controls.addWidget(QLabel("Source:"))
        controls.addWidget(self.opp_source_combo)

        self.opp_search_edit = QLineEdit()
        self.opp_search_edit.setPlaceholderText("Search title, description, or URL")
        self.opp_search_edit.textChanged.connect(self._reset_opportunity_page)
        controls.addWidget(self.opp_search_edit)

        self.opp_status_combo = QComboBox()
        self.opp_status_combo.addItems(["all", "NEW", "EVALUATING", "QUALIFIED",
                                        "AWAITING_APPROVAL", "REJECTED", "ABANDONED"])
        self.opp_status_combo.currentTextChanged.connect(self._reset_opportunity_page)
        controls.addWidget(QLabel("Status:"))
        controls.addWidget(self.opp_status_combo)
        
        self.opp_min_score_spin = QSpinBox()
        self.opp_min_score_spin.setRange(0, 100)
        self.opp_min_score_spin.setValue(0)
        self.opp_min_score_spin.setSuffix("%")
        self.opp_min_score_spin.valueChanged.connect(self._reset_opportunity_page)
        controls.addWidget(QLabel("Min Score:"))
        controls.addWidget(self.opp_min_score_spin)

        # Web-search term for the generic web discovery source. When set (and
        # web discovery is enabled) the "web" source runs a real provider search
        # for this term; discovery is genuinely driven by it instead of only the
        # fixed seed feeds.
        self.opp_web_query_edit = QLineEdit()
        self.opp_web_query_edit.setPlaceholderText("Web search term (for source=web)")
        controls.addWidget(QLabel("Web query:"))
        controls.addWidget(self.opp_web_query_edit)

        # Toggle web discovery on/off from the UI (persists to .env)
        web_enabled = os.getenv("ALLOW_WEB_DISCOVERY", "false").lower() in ("1", "true", "yes")
        self.opp_web_toggle = QCheckBox("Enable web discovery")
        self.opp_web_toggle.setChecked(web_enabled)
        self.opp_web_toggle.setToolTip(
            "Enable the generic web discovery source (ddgs/tavily/brave). "
            "Persists to .env as ALLOW_WEB_DISCOVERY."
        )
        self.opp_web_toggle.toggled.connect(self._on_web_discovery_toggled)
        controls.addWidget(self.opp_web_toggle)

        controls.addStretch()
        lay.addLayout(controls)

        # Surface the web-discovery gate so "web returns nothing" is explained
        # rather than silently empty. Gated OFF by default (human review).
        web_enabled = os.getenv("ALLOW_WEB_DISCOVERY", "false").lower() in ("1", "true", "yes")
        self.opp_web_gate_label = QLabel()
        if web_enabled:
            self.opp_web_gate_label.setText(
                f"🌐 Web discovery ENABLED (provider: {os.getenv('WEB_PROVIDER', 'ddgs')})")
            self.opp_web_gate_label.setStyleSheet("color:#7ec97e; font-size:11px; padding:2px 0;")
        else:
            self.opp_web_gate_label.setText(
                "🌐 Web discovery OFF — set ALLOW_WEB_DISCOVERY=true (and WEB_PROVIDER) "
                "in .env to enable real web/feed discovery.")
            self.opp_web_gate_label.setStyleSheet("color:#e0a030; font-size:11px; padding:2px 0;")
        lay.addWidget(self.opp_web_gate_label)
        
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
        self.opp_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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

        self.opp_clear_btn = QPushButton("Clear All")
        self.opp_clear_btn.clicked.connect(self._clear_opportunities)
        action_row.addWidget(self.opp_clear_btn)
        
        action_row.addStretch()
        lay.addLayout(action_row)
        
        # Status
        self.opp_status_label = QLabel("Ready")
        lay.addWidget(self.opp_status_label)
        self._opp_scan_queue = queue.Queue()
        self._opp_scan_active = False
        self._opp_scan_page = 1
        self._opp_scan_found = 0
        self._opp_scan_last_refresh = 0.0
        # ARCH-ENG-223: NOT STARTED HERE.
        #
        # This ran at 10 Hz for the entire process lifetime -- waking the Qt
        # event loop ten times a second even when no scan was running, the
        # queue was empty and the tab was hidden. On a 6-core CPU that is a
        # small but permanent slice of a core, and 10 Hz of scheduler jitter
        # landing on every paint.
        #
        # It now starts with the scan (`_on_scan_opportunities`) and stops when
        # the "done" event is drained, so it runs only while there is something
        # to drain.
        self.opp_scan_drain_timer = QTimer(self)
        self.opp_scan_drain_timer.timeout.connect(self._drain_opportunity_scan)
        # Fail-safe: if a scan ends without a "done" event reaching the drain
        # (a worker killed, a queue left with a stale "found"), the timer must
        # not stay armed forever. Started at scan time, it is also stopped here
        # on every scan-completion and failure path.

        page_row = QHBoxLayout()
        self.opp_prev_btn = QPushButton("Previous")
        self.opp_prev_btn.clicked.connect(self._previous_opportunity_page)
        page_row.addWidget(self.opp_prev_btn)
        self.opp_page_label = QLabel("Page 1")
        page_row.addWidget(self.opp_page_label)
        self.opp_next_btn = QPushButton("Next")
        self.opp_next_btn.clicked.connect(self._next_opportunity_page)
        page_row.addWidget(self.opp_next_btn)
        page_row.addWidget(QLabel("Results per page:"))
        self.opp_page_size_combo = QComboBox()
        self.opp_page_size_combo.addItems(["10", "20", "50", "100"])
        self.opp_page_size_combo.setCurrentText("20")
        self.opp_page_size_combo.currentTextChanged.connect(self._reset_opportunity_page)
        page_row.addWidget(self.opp_page_size_combo)
        page_row.addStretch()
        lay.addLayout(page_row)
        self._opp_page = 0
        
        # Refresh timer
        self.opp_refresh_timer = QTimer()
        self.opp_refresh_timer.timeout.connect(self._refresh_opportunities)
        self.opp_refresh_timer.start(30000)  # 30s
        self.opp_scan_timer = QTimer()
        self.opp_scan_timer.timeout.connect(self._on_scan_opportunities)
        self._refresh_opportunities()
        
        return w
    
    def create_live_portfolio_tab(self):
        """Create the live portfolio status surface; no fake balance is shown."""
        from agents.earning.live_trading import LiveTradingService, TradingPolicy, adapter_from_env
        from agents.runtime.context import register_component

        exchange = os.getenv("TRADING_EXCHANGE", "coinbase").strip().lower()
        self.live_exchange_ids = [
            "coinbase", "kraken", "binance", "gemini", "bitfinex", "okx",
            "bybit", "kucoin", "bitstamp", " Gate.io".strip(),
        ]
        if exchange not in self.live_exchange_ids:
            self.live_exchange_ids.insert(0, exchange)
        policy = TradingPolicy(
            preapproval_enabled=os.getenv("TRADING_PREAPPROVAL_ENABLED", "false").lower() in {"1", "true", "yes"},
            max_order_usd=float(os.getenv("TRADING_MAX_ORDER_USD", "100")),
            max_position_pct=float(os.getenv("TRADING_MAX_POSITION_PCT", "0.05")),
            max_daily_loss_pct=float(os.getenv("TRADING_MAX_DAILY_LOSS_PCT", "0.02")),
            max_volatility_pct=float(os.getenv("TRADING_MAX_VOLATILITY_PCT", "12")),
            max_spread_pct=float(os.getenv("TRADING_MAX_SPREAD_PCT", "1")),
            min_liquidity_multiple=float(os.getenv("TRADING_MIN_LIQUIDITY_MULTIPLE", "20")),
            min_confidence=float(os.getenv("TRADING_MIN_CONFIDENCE", "0.70")),
            min_expected_profit_pct=float(os.getenv("TRADING_MIN_EXPECTED_PROFIT_PCT", "0.25")),
        )
        self.live_trading_policy = policy
        self.live_adapter_from_env = adapter_from_env
        self._configure_live_exchange(exchange)
        register_component("live_trading", self.live_trading_service)
        self.live_portfolio_worker = None
        self.live_order_worker = None

        w = QWidget()
        lay = QVBoxLayout(w)
        header = QLabel("Live Portfolio")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #4fc3f7; padding: 10px;")
        lay.addWidget(header)
        explanation = QLabel(
            "Real exchange state only. No starting balance is invented. Live orders remain "
            "disabled until explicitly enabled and pass the layered risk policy."
        )
        explanation.setWordWrap(True)
        lay.addWidget(explanation)

        status_group = QGroupBox("Connection and Risk Status")
        status_lay = QFormLayout(status_group)
        self.live_exchange_combo = QComboBox()
        self.live_exchange_combo.addItems(self.live_exchange_ids)
        self.live_exchange_combo.setCurrentText(exchange)
        self.live_exchange_combo.currentTextChanged.connect(self._on_live_exchange_changed)
        self.live_status_label = QLabel("Disabled")
        self.live_equity_label = QLabel("Not synchronized")
        self.live_cash_label = QLabel("Not synchronized")
        self.live_error_label = QLabel(self.live_adapter_error or "")
        self.live_error_label.setWordWrap(True)
        status_lay.addRow("Exchange:", self.live_exchange_combo)
        status_lay.addRow("Execution:", self.live_status_label)
        status_lay.addRow("Total equity:", self.live_equity_label)
        status_lay.addRow("Free cash:", self.live_cash_label)
        status_lay.addRow("Configuration:", self.live_error_label)
        lay.addWidget(status_group)

        sync_btn = QPushButton("Refresh Live Portfolio")
        sync_btn.clicked.connect(self._refresh_live_portfolio)
        lay.addWidget(sync_btn)

        # ARCH-ENG-283 (G-05): the operator-accessible order path. Before this,
        # nothing in the product called `assess_order`, `propose_order`, or
        # `execute_order`; the entire guarded execution flow was test-only.
        # The request is assessed against live state, then either enqueued as a
        # scoped approval (default policy) or, for an explicitly enabled
        # preapproval tier, submitted through `execute_order`'s own gates.
        order_group = QGroupBox("Order Request (approval-gated)")
        order_form = QFormLayout(order_group)
        self.live_order_symbol = QLineEdit("BTC/USD")
        self.live_order_symbol.setPlaceholderText("Symbol (e.g. BTC/USD)")
        order_form.addRow("Symbol:", self.live_order_symbol)

        self.live_order_side = QComboBox()
        self.live_order_side.addItems(["buy", "sell"])
        order_form.addRow("Side:", self.live_order_side)

        self.live_order_type = QComboBox()
        self.live_order_type.addItems(["market", "limit"])
        order_form.addRow("Order type:", self.live_order_type)

        self.live_order_qty = QLineEdit()
        self.live_order_qty.setPlaceholderText("Base-asset quantity")
        order_form.addRow("Quantity:", self.live_order_qty)

        self.live_order_limit = QLineEdit()
        self.live_order_limit.setPlaceholderText(
            "Limit price (limit orders only)")
        order_form.addRow("Limit price:", self.live_order_limit)

        self.live_order_profit = QLineEdit("0.5")
        self.live_order_profit.setPlaceholderText("Expected profit %")
        order_form.addRow("Expected profit %:", self.live_order_profit)

        self.live_order_confidence = QLineEdit("0.80")
        self.live_order_confidence.setPlaceholderText("0.0 - 1.0")
        order_form.addRow("Strategy confidence:", self.live_order_confidence)

        self.live_order_asset = QComboBox()
        self.live_order_asset.addItems(
            ["major", "stable", "alt", "meme", "unknown"])
        order_form.addRow("Asset class:", self.live_order_asset)

        self.live_order_reason = QLineEdit()
        self.live_order_reason.setPlaceholderText(
            "Why this order? (advisory; never overrides risk)")
        order_form.addRow("Reasoning:", self.live_order_reason)

        self.live_order_request_btn = QPushButton(
            "🛡️ Assess & Request Approval")
        self.live_order_request_btn.clicked.connect(
            self._on_live_order_request)
        order_form.addRow(self.live_order_request_btn)

        self.live_order_status = QLabel(
            "No order requested. Requires a configured exchange and "
            "MRBOT_ENABLE_LIVE_TRADING=1.")
        self.live_order_status.setWordWrap(True)
        order_form.addRow(self.live_order_status)
        lay.addWidget(order_group)

        self._refresh_live_portfolio()
        return w

    def _configure_live_exchange(self, exchange: str):
        from agents.earning.live_trading import (
            LiveTradingService, default_daily_equity_path,
        )

        adapter = None
        adapter_error = ""
        try:
            adapter = self.live_adapter_from_env(exchange)
        except Exception as exc:
            adapter_error = str(exc)
        # ARCH-ENG-289 (G-06): the risk gate's daily-loss input needs a
        # durable opening balance. This is the production producer; the
        # service still works without it for tests/embedded callers.
        self.live_trading_service = LiveTradingService(
            adapter, policy=self.live_trading_policy,
            daily_equity_path=default_daily_equity_path(),
        )
        self.live_adapter_error = adapter_error
        self.live_selected_exchange = exchange

    def _on_live_exchange_changed(self, exchange: str):
        if not exchange:
            return
        worker = getattr(self, "live_portfolio_worker", None)
        if worker is not None and worker.isRunning():
            return
        self._configure_live_exchange(exchange)
        self.live_error_label.setText(
            self.live_adapter_error or "Exchange adapter configured; refresh to synchronize"
        )
        self._refresh_live_portfolio()

    def _refresh_live_portfolio(self):
        service = getattr(self, "live_trading_service", None)
        if service is None:
            return
        status = service.status()
        self.live_status_label.setText(status["execution_mode"])
        worker = getattr(self, "live_portfolio_worker", None)
        if worker is not None and worker.isRunning():
            return
        self.live_equity_label.setText("Synchronizing...")
        self.live_cash_label.setText("Synchronizing...")
        worker = LivePortfolioWorker(service)
        self.live_portfolio_worker = worker
        worker.finished.connect(self._on_live_portfolio_result)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_live_portfolio_result(self, result: dict):
        self.live_portfolio_worker = None
        if not result.get("ok"):
            self.live_equity_label.setText("Unavailable")
            self.live_cash_label.setText("Unavailable")
            self.live_error_label.setText(result.get("error", "Portfolio synchronization failed"))
            return
        self.live_equity_label.setText(f"${result['equity']:,.2f}")
        self.live_cash_label.setText(f"${result['cash']:,.2f}")
        self.live_error_label.setText(f"Synchronized {result['balances']} non-zero balances")

    def _on_live_order_request(self):
        """ARCH-ENG-283 (G-05): validate, assess, and propose one order."""
        service = getattr(self, "live_trading_service", None)
        if service is None:
            self.live_order_status.setText("Order: live service unavailable")
            return
        status = service.status()
        if not status.get("configured"):
            self.live_order_status.setText(
                "Order: no exchange adapter configured; nothing was requested")
            return
        if not status.get("live_enabled"):
            self.live_order_status.setText(
                "Order: live trading is disabled (set "
                "MRBOT_ENABLE_LIVE_TRADING=1); nothing was requested")
            return

        symbol = self.live_order_symbol.text().strip().upper()
        if not symbol:
            self.live_order_status.setText("Order: symbol required")
            return
        try:
            quantity = float(self.live_order_qty.text().strip())
            limit_price = float(self.live_order_limit.text().strip() or "0")
            expected_profit = float(self.live_order_profit.text().strip() or "0")
            confidence = float(self.live_order_confidence.text().strip() or "0")
        except ValueError:
            self.live_order_status.setText(
                "Order: quantity, limit, profit, and confidence must be numeric")
            return
        order_type = self.live_order_type.currentText()
        if quantity <= 0:
            self.live_order_status.setText("Order: quantity must be positive")
            return
        if order_type == "limit" and limit_price <= 0:
            self.live_order_status.setText(
                "Order: a limit order needs a positive limit price")
            return

        from agents.earning.live_trading import TradeIntent
        intent = TradeIntent(
            exchange=(getattr(self, "live_selected_exchange", "")
                      or os.getenv("TRADING_EXCHANGE", "coinbase")),
            symbol=symbol,
            side=self.live_order_side.currentText(),
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            expected_profit_pct=expected_profit,
            strategy_confidence=max(0.0, min(1.0, confidence)),
            asset_class=self.live_order_asset.currentText(),
            reasoning=self.live_order_reason.text().strip(),
        )

        worker = getattr(self, "live_order_worker", None)
        if worker is not None and worker.isRunning():
            self.live_order_status.setText(
                "Order: an assessment is already in progress")
            return
        self.live_order_request_btn.setEnabled(False)
        self.live_order_status.setText(
            "Order: assessing against live market and account state...")
        worker = LiveOrderProposalWorker(service, intent)
        self.live_order_worker = worker
        worker.finished.connect(self._on_live_order_proposed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_live_order_proposed(self, result: dict):
        self.live_order_worker = None
        self.live_order_request_btn.setEnabled(True)
        status = result.get("status", "")
        if status == "awaiting_approval":
            approval_id = result.get("approval_id", "")
            self.live_order_status.setText(
                f"Awaiting human approval ({approval_id}). Approve it in "
                "Safety & Tools → Approvals; approval is bound to this exact "
                "order.")
            return
        if result.get("ok") and status in {"preapproved", "live", "executed"}:
            order = (result.get("execution") or {}).get("order")
            self.live_order_status.setText(
                f"Submitted ({status}): {order}")
            return
        if status == "blocked":
            self.live_order_status.setText(
                "Blocked: " + (result.get("error") or "risk policy refused"))
            return
        self.live_order_status.setText(
            "Order failed: " + (result.get("error") or "unknown error"))

    def create_paper_trading_tab(self):
        """Create the Strategy Simulator tab — virtual portfolio testing only."""
        from PySide6.QtWidgets import (
            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
            QDoubleSpinBox,
        )
        from PySide6.QtCore import QTimer
        from agents.earning.paper_trading import PaperTradingEngine
        from agents.runtime.context import register_component

        self.paper_engine = PaperTradingEngine()
        register_component("paper_trading", self.paper_engine)
        
        w = QWidget()
        lay = QVBoxLayout(w)
        
        # Header
        header = QLabel("📈 Strategy Simulator")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        lay.addWidget(header)
        
        # Portfolio summary
        summary_group = QGroupBox("Simulated Portfolio Summary")
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
            "Strategy simulation only: no bank, broker, wallet, exchange, or live order connection. "
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
        if self._opp_scan_active:
            self.opp_status_label.setText("Scan already running")
            return
        self.opp_status_label.setText("Scanning...")
        try:
            from app.earning_pipeline import EarningPipeline
            from agents.earning.opportunity_portfolio import PortfolioEntry, WorkStatus
            source = self.opp_source_combo.currentText()
            sources = None if source == "all" else [source]
            self._opp_scan_active = True
            self._opp_scan_found = 0
            # ARCH-ENG-223: arm the drain timer only while a scan is live.
            self.opp_scan_drain_timer.start(100)

            def add_found_opportunity(opportunity):
                # Discovery runs off-thread; only pass data through the queue.
                self._opp_scan_queue.put(("found", opportunity))

            def run_scan():
                try:
                    pipeline = EarningPipeline(portfolio=self.opportunity_portfolio)
                    web_query = self.opp_web_query_edit.text().strip()
                    found = pipeline.discover(
                        sources=sources, on_found=add_found_opportunity,
                        page=self._opp_scan_page,
                        query=web_query or None,
                    )
                    self._opp_scan_queue.put(("done", len(found), None))
                except Exception as exc:
                    self._opp_scan_queue.put(("done", 0, str(exc)))

            threading.Thread(target=run_scan, daemon=True, name="opportunity-discovery").start()
        except Exception as exc:
            self._opp_scan_active = False
            self.opp_scan_drain_timer.stop()
            self.opp_status_label.setText(f"Scan failed: {exc}")

    def _drain_opportunity_scan(self):
        """Persist a bounded batch of discoveries and refresh progressively."""
        from agents.earning.opportunity_portfolio import PortfolioEntry, WorkStatus
        processed = 0
        while processed < 50:
            try:
                event = self._opp_scan_queue.get_nowait()
            except queue.Empty:
                break
            if event[0] == "done":
                self._opp_scan_active = False
                # ARCH-ENG-223: the scan is over; nothing left to drain.
                self.opp_scan_drain_timer.stop()
                if event[2]:
                    self.opp_status_label.setText(f"Scan failed: {event[2]}")
                else:
                    self.opp_status_label.setText(
                        f"Scan page {self._opp_scan_page}: {event[1]} opportunities found; "
                        f"{self._opp_scan_found} new saved")
                    # Rotate upstream pages on the next scan. Sources without
                    # pagination retain their normal behavior.
                    self._opp_scan_page = min(self._opp_scan_page + 1, 1000)
                self._refresh_opportunities()
                continue
            opportunity = event[1]
            opportunity_id = getattr(opportunity, "id", "")
            if not opportunity_id:
                continue
            ref = {
                "title": getattr(opportunity, "title", ""),
                "description": getattr(opportunity, "description", ""),
                "url": getattr(opportunity, "url", ""),
                "source": getattr(opportunity, "source", ""),
                "platform": getattr(opportunity, "platform", ""),
                "category": getattr(opportunity, "type", ""),
            }
            if self._is_hiring_request(ref):
                continue
            if self.opportunity_portfolio.get(opportunity_id) is not None:
                continue
            entry = PortfolioEntry(
                opportunity_id=opportunity_id,
                opportunity_ref={"id": opportunity_id, **ref},
                work_status=WorkStatus.EVALUATING,
                expected_value=float(getattr(opportunity, "estimated_usd_value", 0.0) or 0.0),
                platform=getattr(opportunity, "platform", "") or "",
                category=getattr(opportunity, "type", "") or "",
                next_action="Review evidence and score before approval",
            )
            self.opportunity_portfolio.add(entry)
            self._opp_scan_found += 1
            self._append_scanned_opportunity(entry)
            processed += 1

    def _append_scanned_opportunity(self, entry):
        """Add one newly discovered row without rebuilding the whole table."""
        if self._opp_page != 0:
            return
        ref = entry.opportunity_ref or {}
        source = self.opp_source_combo.currentText()
        entry_source = str(ref.get("source", "")).lower()
        if (source != "all" and entry.platform.lower() != source.lower()
                and entry_source != source.lower()):
            return
        query = self.opp_search_edit.text().strip().lower()
        haystack = " ".join(str(ref.get(key, "")) for key in
                            ("title", "description", "url")).lower()
        if query and query not in haystack:
            return
        if self.opp_status_combo.currentText() != "all" and entry.work_status.value != self.opp_status_combo.currentText():
            return
        if entry.policy_score < self.opp_min_score_spin.value() / 100:
            return
        page_size = int(self.opp_page_size_combo.currentText())
        if self.opp_table.rowCount() >= page_size:
            return
        from PySide6.QtCore import Qt
        row = self.opp_table.rowCount()
        self.opp_table.insertRow(row)
        values = (
            ref.get("title", entry.opportunity_id), entry.platform or ref.get("source", ""),
            entry.category or ref.get("category", ""), f"${entry.expected_value:,.2f}",
            f"{entry.policy_score * 100:.0f}%", entry.work_status.value,
            ref.get("url", ref.get("source_url", "")),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column == 0:
                item.setData(Qt.UserRole, entry.opportunity_id)
            self.opp_table.setItem(row, column, item)
        self.opp_page_label.setText(f"Live scan: {self._opp_scan_found} new saved")

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
        query = self.opp_search_edit.text().strip().lower()
        status = self.opp_status_combo.currentText()
        filtered = []
        for entry in entries:
            ref = entry.opportunity_ref or {}
            haystack = " ".join(str(ref.get(key, "")) for key in
                                ("title", "description", "url")).lower()
            entry_source = str(ref.get("source", "")).lower()
            if (source != "all" and entry.platform.lower() != source.lower()
                    and entry_source != source.lower()):
                continue
            if status != "all" and entry.work_status.value != status:
                continue
            if query and query not in haystack:
                continue
            if entry.policy_score < minimum:
                continue
            filtered.append(entry)
        page_size = int(self.opp_page_size_combo.currentText())
        page_count = max(1, (len(filtered) + page_size - 1) // page_size)
        self._opp_page = min(self._opp_page, page_count - 1)
        page_entries = filtered[self._opp_page * page_size:(self._opp_page + 1) * page_size]
        # Expose the exact rows this tab is showing so the Dialogue personas
        # plan around real, visible candidates instead of an abstract goal.
        self._opp_visible_entries = list(page_entries)
        self.opp_table.setRowCount(0)
        for entry in page_entries:
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
        self.opp_page_label.setText(
            f"Page {self._opp_page + 1} of {page_count} ({len(filtered)} results)")
        self.opp_prev_btn.setEnabled(self._opp_page > 0)
        self.opp_next_btn.setEnabled(self._opp_page < page_count - 1)

    @staticmethod
    def _is_hiring_request(ref):
        """Exclude posts where someone is seeking a worker rather than work."""
        text = " ".join(str(ref.get(key, "")) for key in ("title", "description")).lower()
        return any(re.search(pattern, text) for pattern in (
            r"\[?for hire\]?", r"looking to hire", r"we are hiring",
            r"hiring a developer", r"need (a|an) (developer|freelancer|worker)",
            r"seeking (a|an) (developer|freelancer|worker)",
        ))

    def _portfolio_contains_duplicate(self, ref):
        """Catch the same listing when a source changes its external ID."""
        url = str(ref.get("url", "")).split("?", 1)[0].rstrip("/").lower()
        title = " ".join(str(ref.get("title", "")).lower().split())
        platform = str(ref.get("platform", "")).lower()
        if not url and not title:
            return False
        for entry in self.opportunity_portfolio.list_all():
            old = entry.opportunity_ref or {}
            old_url = str(old.get("url", "")).split("?", 1)[0].rstrip("/").lower()
            old_title = " ".join(str(old.get("title", "")).lower().split())
            if url and old_url and url == old_url:
                return True
            if title and title == old_title and platform == entry.platform.lower():
                return True
        return False

    def _on_web_discovery_toggled(self, checked: bool):
        """Persist the web-discovery toggle to .env and update the gate label."""
        from app.environment import set_env_values
        set_env_values({"ALLOW_WEB_DISCOVERY": "true" if checked else "false"})
        if checked:
            self.opp_web_gate_label.setText(
                f"🌐 Web discovery ENABLED (provider: {os.getenv('WEB_PROVIDER', 'ddgs')})"
            )
            self.opp_web_gate_label.setStyleSheet("color:#7ec97e; font-size:11px; padding:2px 0;")
        else:
            self.opp_web_gate_label.setText(
                "🌐 Web discovery OFF — tick 'Enable web discovery' to turn it on."
            )
            self.opp_web_gate_label.setStyleSheet("color:#e0a030; font-size:11px; padding:2px 0;")
        self._reset_opportunity_page()

    def _reset_opportunity_page(self, *_args):
        self._opp_page = 0
        self._refresh_opportunities()

    def _previous_opportunity_page(self):
        self._opp_page = max(0, self._opp_page - 1)
        self._refresh_opportunities()

    def _next_opportunity_page(self):
        self._opp_page += 1
        self._refresh_opportunities()

    def _clear_opportunities(self):
        entries = self.opportunity_portfolio.list_all()
        if not entries:
            return
        answer = QMessageBox.question(
            self, "Clear opportunities", "Remove all saved opportunities?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        for entry in entries:
            self.opportunity_portfolio.remove(entry.opportunity_id)
        self._reset_opportunity_page()
        self.opp_status_label.setText("Opportunities cleared")

    def _on_research_opportunity(self):
        """Research selected opportunity."""
        entries = self._selected_opportunity_entries()
        if not entries:
            self.opp_status_label.setText("Select an opportunity first")
            return
        from agents.earning.opportunity_portfolio import WorkStatus
        try:
            for entry in entries:
                self.opportunity_portfolio.transition_work_status(
                    entry.opportunity_id, WorkStatus.EVALUATING)
            self._refresh_opportunities()
            self.opp_status_label.setText(f"{len(entries)} opportunities marked for evaluation")
        except Exception as exc:
            self.opp_status_label.setText(f"Research unavailable: {exc}")

    def _on_apply_opportunity(self):
        """Apply to selected opportunity."""
        entries = self._selected_opportunity_entries()
        if not entries:
            self.opp_status_label.setText("Select an opportunity first")
            return
        from agents.earning.opportunity_portfolio import WorkStatus
        try:
            for entry in entries:
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
                f"{len(entries)} applications queued for human approval; nothing was submitted")
        except Exception as exc:
            self.opp_status_label.setText(f"Apply unavailable: {exc}")

    def _on_reject_opportunity(self):
        """Reject selected opportunity."""
        entries = self._selected_opportunity_entries()
        if not entries:
            self.opp_status_label.setText("Select an opportunity first")
            return
        from agents.earning.opportunity_portfolio import WorkStatus
        try:
            for entry in entries:
                if entry.work_status == WorkStatus.NEW:
                    self.opportunity_portfolio.transition_work_status(
                        entry.opportunity_id, WorkStatus.ABANDONED)
                else:
                    self.opportunity_portfolio.transition_work_status(
                        entry.opportunity_id, WorkStatus.REJECTED)
            self._refresh_opportunities()
            self.opp_status_label.setText(f"{len(entries)} opportunities rejected")
        except Exception as exc:
            self.opp_status_label.setText(f"Reject unavailable: {exc}")

    def _selected_opportunity_entry(self):
        """Return the portfolio entry represented by the selected table row."""
        entries = self._selected_opportunity_entries()
        return entries[0] if entries else None

    def _selected_opportunity_entries(self):
        """Return portfolio entries represented by all selected table rows."""
        rows = sorted({index.row() for index in self.opp_table.selectedIndexes()})
        entries = []
        for row in rows:
            item = self.opp_table.item(row, 0)
            if item is None:
                continue
            entry = self.opportunity_portfolio.get(item.data(Qt.UserRole))
            if entry is not None:
                entries.append(entry)
        if entries:
            return entries
        row = self.opp_table.currentRow()
        if row < 0:
            return []
        item = self.opp_table.item(row, 0)
        if item is None:
            return []
        entry = self.opportunity_portfolio.get(item.data(Qt.UserRole))
        return [entry] if entry is not None else []

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
        from agents.earning.paper_trading import OrderSide, OrderType
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
        from gui.tabs.analytics_tab import AnalyticsTab
        from agents.runtime.context import register_component
        self.analytics_tab = AnalyticsTab(parent=self)
        register_component("analytics", self.analytics_tab)
        return self.analytics_tab
    
    def create_reputation_tab(self):
        """Create the Reputation tab — track agent reputation across platforms."""
        from agents.earning.reputation import ReputationTracker

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
        from agents.providers.provider_manager import ProviderManager
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
                from agents.runtime.dual_brain import DualBrainRuntime
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
            from agents.brains.base_worker import _active_worker
            if _active_worker is not None:
                _active_worker.invalidate_provider_registry()
        except Exception:
            pass


__all__ = ["FeatureTabBuildersMixin"]
