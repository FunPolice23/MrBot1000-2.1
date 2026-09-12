"""
main.py - MrBot1000 Desktop Application
=======================================

DESKTOP APPLICATION UI AND INTEGRATION LAYER

This file contains:
- MainWindow class: Main QMainWindow with tabbed interface
- UI initialization: Management, Agents, Browse, Payments, Earnings, Settings, Logs, DB Stats
- Signal routing: Manager <-> Summarizer <-> UI event handling
- Settings persistence: Save/load checkbox states to .env
- Chat handling: routes summarizer responses to Agents tab

USAGE:
    python main.py
    Opens the MrBot1000 desktop application with full agent orchestration

KEY COMPONENTS:
    - MainWindow: Main application window with 8 tabs
    - ManagerThread: Background agent coordinator
    - SummarizerThread: Chat interface handler
    - AgentsTab: Chat display + live info in the Agents tab (UnifiedChatWidget retired)
    - ActionPipeline: Safe file modification with validation

SECURITY:
    - PATH_TRAVERSAL_PREVENTION: Uses Path.is_relative_to()
    - CLIPBOARD_VALIDATION: Max 10KB JSON, domain blocklist
    - PAYOUT_LIMITS: $10K max, triple confirmation required
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))

# ── Runtime interpreter isolation (v2.0.36x) ──────────────────────────────
# A parent process (e.g. a desktop app / agent shell) may set a global PYTHONPATH
# pointing at ITS OWN venv's site-packages. When this app is launched via the
# project `.venv` interpreter it inherits that PYTHONPATH, so Python would import
# e.g. `openai`/`pydantic_core` from the FOREIGN venv — whose native extensions are
# ABI-incompatible and crash (a broken `pydantic_core._pydantic_core`), which in
# turn makes the LlamaCppAdapter `available()` return False and disables the
# llama.cpp brains. Sanitize sys.path at startup so ONLY this interpreter's own
# site-packages (sys.prefix = the venv, sys.base_prefix = its parent) are used.
# This must run before any third-party import. See the python-interpreter-debugging
# skill (references/cross-interpreter-pythonpath.md).
def _sanitize_sys_path():
    keep_roots = set()
    for base in (sys.prefix, sys.base_prefix):
        if not base:
            continue
        keep_roots.add(os.path.normcase(os.path.abspath(base)))
        keep_roots.add(os.path.normcase(os.path.join(os.path.abspath(base), "Lib", "site-packages")))
        keep_roots.add(os.path.normcase(os.path.join(os.path.abspath(base), "lib", "python")))
    # Keep the repo root (entry dir, already inserted above) and anything under a
    # kept interpreter root; drop foreign venv/site-packages PYTHONPATH entries.
    own_file = os.path.normcase(os.path.abspath(__file__))
    own_dir = os.path.dirname(own_file)
    cleaned = []
    for entry in sys.path:
        if not entry:
            cleaned.append(entry)
            continue
        e = os.path.normcase(os.path.abspath(entry))
        # Always keep the repo root and stdlib zip/app-path markers.
        if e == own_dir or entry == "":
            cleaned.append(entry)
            continue
        under_own = any(
            e == r or e.startswith(r + os.sep) for r in keep_roots)
        if under_own:
            cleaned.append(entry)
            continue
        # A bare PYTHONPATH dir that is NOT a venv/site-packages (e.g. a tools dir)
        # is harmless to keep only if it isn't a foreign interpreter site-packages.
        low = e.lower()
        if low.endswith("site-packages") or "site-packages" in low or low.endswith("\\venv") or low.endswith("/venv"):
            continue  # foreign interpreter package dir -> drop
        cleaned.append(entry)
    sys.path[:] = cleaned

try:
    _sanitize_sys_path()
except Exception:
    pass  # never let path sanitizing itself break startup

# ── CLI flags ──────────────────────────────────────────────────────────────
# -sm / --safe-mode is a convenience alias for MRBOT_SAFE_MODE=true.
# It exercises the workflow without making real file changes.
import argparse

_parser = argparse.ArgumentParser(description="MrBot1000 desktop application", add_help=True)
_parser.add_argument("-sm", "--safe-mode", action="store_true",
                     help="Run in safe mode (alias for MRBOT_SAFE_MODE=true)")
_args, _unknown = _parser.parse_known_args()
if _args.safe_mode:
    os.environ["MRBOT_SAFE_MODE"] = "true"

import html
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv  # set_key no longer used directly (see set_env_values)
from typing import Any, Callable, Dict, List, Optional

def _ensure_qt_font_directory():
    """Point Qt at the system font directory when PySide6's bundled folder is missing.

    Qt no longer ships fonts with PySide6 on some installs, which triggers the
    warning about a missing lib/fonts directory. We fix the root cause by
    pointing QT_QPA_FONTDIR at the real Windows font folder before creating the
    QApplication, while leaving the warning visible only when no valid system
    font directory exists.
    """
    if os.environ.get("QT_QPA_FONTDIR"):
        return

    candidates = []
    for raw in (
        os.environ.get("WINDIR"),
        os.environ.get("SystemRoot"),
        r"C:\Windows\Fonts",
        r"C:\Windows\SystemFonts",
    ):
        if raw:
            candidates.append(Path(raw).expanduser())

    for candidate in candidates:
        if candidate.exists() and any(candidate.iterdir()):
            os.environ["QT_QPA_FONTDIR"] = str(candidate)
            return


_ensure_qt_font_directory()

from PySide6.QtCore import Qt, QThread, QTimer, Signal, qInstallMessageHandler
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from agents.base_worker import ROOT_FOLDER, WorkerAgent
from agents.summarizer import SummarizerThread

# Phase 6: unified event logger, notification service, human-approval queue,
# alerting rule engine, and heartbeat system (credit-based survival tiers).
from agents.event_logger import StructuredEventLogger, Event, EventLevel, EventType
from agents.notifications import NotificationService, NotifLevel, notify
from agents.approval_queue import HumanApprovalQueue, ApprovalKind, ApprovalStatus
from agents.provider_manager import ProviderManager, ProviderStatus
from agents.provider_hot_reload import ProviderHotReload
from agents.alerting import (
    AlertRuleEngine, add_default_rules,
    llm_spend_threshold_rule, survival_tier_change_rule,
    safety_block_rule, pending_approval_aging_rule,
)
from agents.autonomy.heartbeat import HeartbeatSystem, CreditMonitor, SurvivalTier
from database import AgentDB
from gui.tab_builders import TabBuildersMixin
from manager import ManagerThread

# Theme system — single source of truth lives in theme_config.py
# (preset definitions + env-driven "Custom" theme via MRBOT_THEME_*).
from theme_config import (
    CUSTOM_THEME_NAME,
    THEME_PRESETS,
    resolve_theme_definition,
)
from ui import QuadThoughtPanel

try:
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)
except Exception:
    # A locked/locked-temp .env shouldn't crash startup; env vars are read lazily.
    pass

# ── Robust .env write (v2.0.34aj) ─────────────────────────────────────────────
# python-dotenv's set_key() writes a fresh `.tmp_*` then os.replace()s it onto
# .env. On Windows, AV/sync tools briefly lock that brand-new temp, so BOTH the
# replace AND dotenv's own os.unlink() cleanup fail — orphaning plaintext-secret
# `.tmp_*` files (WinError 32/5). We avoid the churn by rewriting .env ONCE per
# save and using a lock-resilient temp + guaranteed cleanup.
def _read_env_lines(path: Path):
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().splitlines()
    except Exception:
        return []


def set_env_values(values: dict):
    """Write many KEY=VALUE pairs to `.env` in a single, lock-resilient pass.

    Rewrites the whole file (preserving unknown keys/comments) and replaces it
    atomically with retry + guaranteed temp cleanup. Never leaves a `.tmp_*` behind.
    """
    env = Path(".env")
    lines = _read_env_lines(env)
    keys = {k: (str(v) if v is not None else "") for k, v in values.items()}
    out = []
    covered = set()
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            out.append(ln)
            continue
        if "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in keys:
                covered.add(k)
                out.append(f"{k}={keys[k]}")
                continue
        out.append(ln)
    for k, v in keys.items():
        if k not in covered:
            out.append(f"{k}={v}")
    data = "\n".join(out) + ("\n" if out else "")
    # Atomic, retry-on-lock write with guaranteed temp cleanup.
    import tempfile
    for attempt in range(5):
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(env.parent), prefix=".env.tmp_")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, env)
            return
        except (PermissionError, OSError):
            # temp may be locked by AV/sync; retry after a short backoff.
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            if attempt == 4:
                raise
            time.sleep(0.15 * (attempt + 1))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    openai = None

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    Anthropic = None

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    ollama = None

load_dotenv()

# ---------------------------------------------------------------------------
# Security Configuration
# ---------------------------------------------------------------------------
# Max characters for clipboard JSON to prevent DoS
MAX_CLIPBOARD_JSON_CHARS = 10000

# Payout security limits
MAX_PAYOUT_AMOUNT_USD = 10000
MIN_PAYOUT_AMOUNT_USD = 0.01

# Blocked domains that should never be interacted with
SECURITY_BLOCKED_DOMAINS = {
    "sketchy-airdrop.xyz",
    ".xyz", ".top", ".site", ".club",  # Low-trust TLDs
}

def validate_clipboard_json(text: str) -> tuple[bool, dict|None, str]:
    """SECURE: Validate clipboard JSON content.
    
    Returns: (is_valid, parsed_dict_or_None, error_message)
    """
    if not text:
        return False, None, "Clipboard is empty"
    
    if len(text) > MAX_CLIPBOARD_JSON_CHARS:
        return False, None, f"JSON exceeds {MAX_CLIPBOARD_JSON_CHARS} char limit"
    
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as e:
        return False, None, f"Invalid JSON: {e}"
    
    if not isinstance(data, dict):
        return False, None, "JSON must be an object/dict"
    
    # Check for blocked domains
    text_lower = text.lower()
    for domain in SECURITY_BLOCKED_DOMAINS:
        if domain in text_lower:
            return False, None, f"Blocked domain detected: {domain}"
    
    return True, data, ""


# ---------------------------------------------------------------------------
# Background HTTP worker
# ---------------------------------------------------------------------------
class HttpWorker(QThread):
    result = Signal(str, object)

    def __init__(self, method, url, tag, **kwargs):
        super().__init__()
        self.method = method
        self.url    = url
        self.tag    = tag
        self.kwargs = kwargs

    def run(self):
        for attempt in range(3):
            try:
                resp = requests.request(
                    self.method, self.url, timeout=10, **self.kwargs)
                if resp.status_code < 500:
                    self.result.emit(self.tag, resp)
                    return
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        self.result.emit(self.tag, None)


class PipelineWorker(QThread):
    """Run the (network-bound) earning pipeline OFF the GUI thread so the app
    stays responsive — a synchronous run_full_cycle() would freeze the UI while
    it discovers gigs over the network (the 'Run Full Cycle freezes' bug)."""
    finished = Signal(object)   # PipelineResult (or None on error)
    errored  = Signal(str)

    def __init__(self, sources, max_risk, db_path, log_fn):
        super().__init__()
        self.sources = sources
        self.max_risk = max_risk
        self.db_path = db_path
        self.log_fn = log_fn

    def run(self):
        try:
            from earning_pipeline import EarningPipeline
            pipeline = EarningPipeline(db_path=self.db_path, log_fn=self.log_fn)
            result = pipeline.run_full_cycle(sources=self.sources, max_risk=self.max_risk)
            self.finished.emit(result)
        except Exception as e:
            self.errored.emit(str(e))


class ModelFetchWorker(QThread):
    """Fetch cloud-provider models (w/ pricing) OFF the GUI thread.

    Emits list[ModelInfo] (or [] on failure) via `finished`.
    """
    finished = Signal(object)

    def __init__(self, provider: str, api_key: str, base_url: str):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        try:
            import provider_models as pm
            models = pm.fetch_models(self.provider, self.api_key, self.base_url)
        except Exception:
            models = []
        self.finished.emit(models)


# ---------------------------------------------------------------------------
# Live-log rendering helper
# ---------------------------------------------------------------------------
def _log_html(ts: str, severity: str, msg: str, color: str) -> str:
    """Render one log entry as safe HTML for the live-log QTextEdit.

    - HTML-escapes the message so a stray '<' / '&' in log text can't break the
      view or inject markup (defense against untrusted gig/scrape data ending up
      in the log).
    - Converts embedded newlines to <br> so multi-line payloads (e.g. the
      'BEGIN UNTRUSTED GIG DATA' envelope) break onto their own line instead of
      collapsing into one giant inline line in the HTML view.
    - Converts bare color strings to style-safe hex RGB.
    """
    if color:
        color = _color_to_hex(color)
    safe = html.escape(msg, quote=False).replace("\n", "<br>")
    return f'<span style="color:{color};">[{ts}] [{severity}] {safe}</span>'


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
def _contrast(hex_color: str) -> str:
    """Return '#000000' or '#ffffff' for readable text on a bg color."""
    h = hex_color.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    if len(h) < 6:
        return "#000000"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#000000"
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return "#000000" if lum > 0.6 else "#ffffff"

class MainWindow(TabBuildersMixin, QMainWindow):
    log_signal = Signal(str)

    # Theme names exposed in the Theme menu / Settings combobox. The actual
    # definitions live in theme_config.py (resolve_theme_definition), so the
    # custom coloring (MRBOT_THEME_*) and all presets stay connected.
    THEMES = {name: None for name in ["Auto"] + THEME_PRESETS + [CUSTOM_THEME_NAME]}

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MrBot1000 v2.1")
        self._window_mode = os.getenv("MRBOT_WINDOW_MODE", "normal").strip().lower()
        self._normal_window_geometry = None
        self._size_for_screen()
        self.root_folder  = ROOT_FOLDER
        self._http_workers = []
        self._log_buffer   = []
        # v2.0.27: theme-state holders for Phase E tokenization. Initialized here
        # (not just in apply_theme) so widget creation in create_ui() can register
        # themeable widgets before apply_theme runs.
        self._last_theme = "Dark"
        self._theme = {}
        self._themeable = []

        self.db = AgentDB()

        # ── Action Pipeline ───────────────────────────────────────────────────
        from action_pipeline import ActionPipeline
        self.pipeline = ActionPipeline(
            root_folder=ROOT_FOLDER,
            db=self.db,
            log_fn=lambda msg: self.log_signal.emit(msg)
        )
        self.pipeline.on_validated = self._on_pipeline_validated
        self.pipeline.on_executed  = self._on_pipeline_executed
        self.pipeline.on_rejected  = self._on_pipeline_rejected

        # ── Earning Pipeline engine (2.0.20h) ─────────────────────────────────
        # Instantiated and handed to the Manager so its discovery engine actually
        # runs during heartbeats (previously dead code — never constructed).
        # v2.1 Phase 3: built via the unified composition root so the GUI, manager,
        # portfolio, autonomous loop, and run store share ONE lifecycle authority
        # and ONE durable run ledger. Guarded: a failure must NOT block startup.
        self.earning_pipeline = None
        self.opportunity_portfolio = None
        self.autonomous_run_store = None
        try:
            from agents.composition_root import build_composition_root
            root = build_composition_root(
                db_path=os.path.join(ROOT_FOLDER, "earning.db"),
                log_fn=lambda msg: self.log_signal.emit(f"[Earning] {msg}"),
            )
            self._composition_root = root
            self.earning_pipeline = root.pipeline
            self.opportunity_portfolio = root.portfolio
            self.autonomous_run_store = root.run_store
        except Exception as _ep_err:
            self.log_signal.emit(f"[Startup] EarningPipeline unavailable: {_ep_err}")

        # v2.0.22 S1: Instruction Provenance Gate — single trust anchor for any
        # external playbook/SKILL.md fetched by platform adapters.
        try:
            from agents.instruction_gate import InstructionGate
            self.instruction_gate = InstructionGate(self.db)
        except Exception as _ig_err:
            self.instruction_gate = None
            self.log_signal.emit(f"[Startup] InstructionGate unavailable: {_ig_err}")

        # ── Phase 6: unified services ──────────────────────────────────────────
        # Event logger (JSONL + in-memory index) — single source of truth for
        # earning, safety, heartbeat, LLM spend, approval, and system events.
        self.event_logger = StructuredEventLogger.instance()
        self.event_logger.info(EventType.SYSTEM.value, "MrBot1000 starting up", source="main")

        # Notification service (desktop toast + in-app panel)
        self.notification_service = NotificationService.instance()

        # Human-approval queue (submissions, payments, gates)
        self.approval_queue = HumanApprovalQueue.instance()

        # Alerting rule engine — evaluates events against rules and fires
        # notifications. Cloud-only spend alerts, tier changes, safety blocks,
        # pending-approval aging.
        self.alerting_engine = AlertRuleEngine.instance()
        add_default_rules()
        self.event_logger.info(
            EventType.SYSTEM.value,
            f"Alerting engine started with {len(self.alerting_engine.get_rules())} rules",
            source="main",
        )

        # Heartbeat system — credit-based survival tiers. Uses the earning
        # pipeline's credit getter if available, else a simple default.
        # NOTE: interval is set after manager is created below.
        self.heartbeat_system = None

        ollama_chat  = os.getenv("OLLAMA_CHAT_MODEL", "").strip() or None
        ollama_main  = os.getenv("OLLAMA_MAIN_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or None
        self.log_signal.emit(f"[Startup] OLLAMA_CHAT_MODEL from env: {ollama_chat}")
        self.log_signal.emit(f"[Startup] OLLAMA_MAIN_MODEL from env: {ollama_main}")
        api_key      = os.getenv("OPENAI_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
        self.worker  = WorkerAgent(api_key, self.log_signal, db=self.db,
                                   chat_ollama_model=ollama_chat,
                                   primary_ollama_model=ollama_main)
        self.manager = ManagerThread(api_key, self.worker, db=self.db,
                                   earning_pipeline=self.earning_pipeline)
        self.summarizer = SummarizerThread(self.worker, db=self.db, manager=self.manager)
        self.manager.set_summarizer(self.summarizer)  # Connect summarizer to manager

        # ── Phase 6: heartbeat + bridges (after manager exists) ─────────────
        self.heartbeat_system = HeartbeatSystem(
            interval=self.manager.HEARTBEAT_INTERVAL,
            credit_getter=lambda: getattr(self.earning_pipeline, 'credits', 500.0)
            if self.earning_pipeline else lambda: 500.0,
        )

        # Bridge: approval queue → notification service
        self.approval_queue.on_change = self._on_approval_queue_change

        # Bridge: event logger → alerting engine
        self.event_logger.on_log = self._on_event_logged

        # Provider hot-reload: monitor .env for changes and update providers at runtime
        try:
            from agents.provider_hot_reload import ProviderHotReload
            self.provider_hot_reload = ProviderHotReload.instance()
            self.provider_hot_reload.register_callback(self._on_provider_config_changed)
            self.provider_hot_reload.start_monitoring(interval=2.0)
            self.log_signal.emit("[Startup] Provider hot-reload monitoring started")
        except Exception as e:
            self.log_signal.emit(f"[Startup] Provider hot-reload unavailable: {e}")
            self.provider_hot_reload = None

        # Register specialized workers with the CEO manager
        try:
            from agents.job_search_worker import JobSearchWorker
            self.job_worker = JobSearchWorker(api_key, self.log_signal, db=self.db)
            self.job_worker.set_new_jobs_callback(self.manager.on_new_jobs)
            self.manager.register_worker("JobSearch", self.job_worker, "job search")
        except Exception:
            self.job_worker = None
            # Not fatal — just means no job search worker
        try:
            from agents.analyst_worker import AnalystWorker
            self.analyst_worker = AnalystWorker(api_key, self.log_signal, db=self.db)
            self.manager.register_worker("Analyst", self.analyst_worker, "code analysis")
        except Exception:
            self.analyst_worker = None
        try:
            from agents.coder import CoderWorker
            self.coder_worker = CoderWorker(api_key, self.log_signal, db=self.db)
            self.manager.register_worker("Coder", self.coder_worker, "code refactoring")
        except Exception:
            self.coder_worker = None
            # Not fatal — Coder ACTIONs fall back to base worker (Bug D fixed)

        self.summarizer.chat_reply.connect(self._on_summarizer_chat_reply)

        self.manager.manager_thought.connect(self._on_manager_thought)
        self.manager.agent_thought.connect(self._on_agent_thought)
        self.manager.comms.connect(self._on_comms)
        self.summarizer.summary_ready.connect(self._on_summary_ready)

        self.manager.log.connect(self._safe_log)
        self.manager.chat_reply.connect(self._on_chat_reply)
        self.manager.agent_status.connect(self._on_agent_status)
        self.log_signal.connect(self._safe_log)

        # New CEO signals
        self.manager.worker_assigned.connect(self._on_worker_assigned)
        self.manager.job_found.connect(self._on_job_found)

        self.manager.manager_thought.connect(self.summarizer.add_manager_thought)
        self.manager.agent_thought.connect(self.summarizer.add_agent_thought)
        self.manager.comms.connect(self.summarizer.add_comms_thought)

        # Create UI first, then start threads
        self.create_ui()
        self.apply_theme("Dark")

        self.summarizer.start()
        self.manager.start()

        # P4 (comms redesign): bridge the EventBus into the GUI thread so the
        # dashboard observes OPPORTUNITY/EVIDENCE/NOTIFICATION events without
        # sniffing arbitrary chat strings or reading a JSON mirror.
        try:
            from agents.comms import QtEventBridge
            if QtEventBridge is not None:
                self._bus_bridge = QtEventBridge(parent=self)
                self._bus_bridge.message.connect(self._on_bus_event)
        except Exception:
            self._bus_bridge = None

        self._balance_timer = QTimer(self)
        self._balance_timer.timeout.connect(self.refresh_balance)
        # PERF: 60s interval (was 30s) — wallet balance doesn't change that fast
        self._balance_timer.start(60000)

        menubar = self.menuBar()
        fm = menubar.addMenu("File")
        fm.addAction("Register Autonomous").triggered.connect(
            self.register_autonomous)
        fm.addAction("Exit").triggered.connect(self.close)

        view_menu = menubar.addMenu("View")
        view_menu.addAction("Show Thought Panel").triggered.connect(
            self._show_thoughts)
        view_menu.addSeparator()
        self.show_thoughts_action = view_menu.addAction("Hide Thought Panel")
        self.show_thoughts_action.setCheckable(True)
        self.show_thoughts_action.toggled.connect(self._toggle_thought_panel)

        view_menu.addAction("🟣 Manager Window").triggered.connect(self._show_manager_win)
        view_menu.addAction("🟢 Agent Window").triggered.connect(self._show_agent_win)
        view_menu.addAction("🟡 Comms Window").triggered.connect(self._show_comms_win)
        view_menu.addAction("📊 Summary Window").triggered.connect(self._show_summary_win)

        view_menu.addSeparator()
        window_mode_menu = view_menu.addMenu("Window Mode")
        self._window_mode_actions = {}
        for mode, label in (
            ("normal", "Normal"),
            ("maximized", "Maximized"),
            ("fullscreen", "Fullscreen"),
            ("borderless", "Borderless"),
        ):
            action = window_mode_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, m=mode: self._set_window_mode(m))
            self._window_mode_actions[mode] = action


        theme_menu = menubar.addMenu("Theme")
        for t in self.THEMES:
            act = theme_menu.addAction(t)
            if t == CUSTOM_THEME_NAME:
                # Opening the Custom entry pops up the color customizer so the
                # user can edit + preview, instead of silently applying old colors.
                act.triggered.connect(
                    lambda _, tn=t: self._open_theme_customizer(tn))
            else:
                act.triggered.connect(lambda _, tn=t: self.apply_theme(tn))

        self.thought_panel = QuadThoughtPanel(self)
        self.thought_panel.hide()

        # v2.0.34ag (A5): status_label is created here (top-level) so it exists
        # before the lazy Management tab is built; create_management_tab reuses it.
        self.status_label = QLabel("Agent status: Not registered")

        if api_key:
            self.status_label.setText("Agent status: Registered ✓")

        for t in self.db.get_thoughts(limit=100):
            self.thought_panel.route(t["source"], f"[history] {t['text']}")
        self.thought_panel.route("System",
                                 f"Agent started. Root: {ROOT_FOLDER}")
        # v2.0.21 P1#1: verify runtime deps at boot so a missing package (e.g.
        # feedparser in a different Python env) shows a clear warning instead of
        # silently killing discovery mid-run.
        self._check_dependencies()
        # v2.0.21 P1#3: surface model-config issues at startup (no crash).
        # Runs here (after thought_panel exists) so warnings can be routed.
        self._validate_model_config(ollama_main, ollama_chat)
        self.thought_panel.route("System", "Research folder: not set")

        self._db_stats_start_timer = QTimer(self)
        self._db_stats_start_timer.setSingleShot(True)
        self._db_stats_start_timer.timeout.connect(self.refresh_db_stats)
        self._db_stats_start_timer.start(600)

    # ── v2.0.21 P1#1: startup dependency check ────────────────────────────────
    def _check_dependencies(self):
        """Import every package pinned in requirements.txt; warn (never crash) on
        a missing one so the app boots and the operator sees WHICH feature is
        disabled (e.g. feedparser -> Reddit/LinkedIn discovery off)."""
        req_path = os.path.join(ROOT_FOLDER, "requirements.txt")
        if not os.path.exists(req_path):
            self.thought_panel.route("System", "[Startup] WARN: requirements.txt not found")
            return
        missing = []
        # distribution-name -> import-name (they differ for some packages)
        import_aliases = {
            "beautifulsoup4": "bs4",
            "python-dotenv": "dotenv",
            "pyyaml": "yaml",
            "pillow": "PIL",
            "lxml": "lxml",
            "python-dateutil": "dateutil",
        }
        with open(req_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # strip version specifiers / extras: "pkg[extra]>=1.2" -> "pkg"
                pkg = line.split(">=")[0].split("==")[0].split("<")[0].split("~")[0].split("[")[0].strip()
                if not pkg:
                    continue
                mod = import_aliases.get(pkg, pkg)
                try:
                    __import__(mod)
                except Exception:
                    missing.append(pkg)
        if missing:
            msg = ("[Startup] WARN: missing deps -> " + ", ".join(missing) +
                   " (related discovery/features disabled)")
            # If CORE packages (the ones main.py itself needs to even run) are
            # missing, the app was almost certainly launched with the wrong
            # interpreter (e.g. `py` -> system Python, not the venv). Say so
            # explicitly instead of just listing packages.
            core = {"PySide6", "ollama", "python-dotenv", "requests"}
            if core & set(missing):
                msg += (" | CORE packages missing — you are likely running the "
                        "wrong Python. Launch with the venv interpreter, e.g. "
                        "venv/Scripts/python.exe main.py")
            self.thought_panel.route("System", msg)
            print(msg)
        else:
            self.thought_panel.route("System", "[Startup] Dependencies OK")

    # ── v2.0.21 P1#3: startup model-config validation ────────────────────────
    def _validate_model_config(self, main_model: str | None, chat_model: str | None):
        """Emit clear startup warnings about model configuration problems.
        Never crashes — purely advisory so the operator can fix config."""
        def warn(msg):
            full = f"[Startup] MODEL WARN: {msg}"
            # Defensive: thought_panel may not exist if called early.
            panel = getattr(self, "thought_panel", None)
            if panel is not None:
                try:
                    panel.route("System", full)
                except Exception:
                    pass
            print(full)

        if not main_model:
            warn("OLLAMA_MAIN_MODEL is not set — falling back to default 'llama3.2'. "
                 "Set OLLAMA_MAIN_MODEL in .env for the intended model.")
        if not chat_model:
            warn("OLLAMA_CHAT_MODEL is not set — chat will use the main model. "
                 "Set OLLAMA_CHAT_MODEL in .env for a lighter chat model.")
        # NOTE (v2.0.22): the previous "large model" / "main==chat VRAM" heuristics
        # were removed — model SIZE and co-location are intentionally operator-
        # controlled (any model on any hardware: 6GB Zen3 → modern RTX, Ollama or
        # other local/cloud providers). See plans/v2.0.22-security-first.md.

    def shutdown(self):
        """Tear down worker threads and DB cleanly (idempotent).

        Centralised so both closeEvent (window closed) and any explicit
        shutdown path call the same teardown. Guarded so it is safe to call
        more than once or when some members are absent.
        """
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True
        # Stop app-owned timers first so a single-shot timer cannot fire into a
        # half-torn-down window.
        for timer in (getattr(self, "_auto_start_timer", None),
                  getattr(self, "_db_stats_start_timer", None),
                  getattr(self, "_stats_timer", None),
                  getattr(self, "_balance_timer", None)):
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        # Stop background QThreads/QTimers owned by built tab widgets (e.g. the
        # GPU poller in Providers & GPU, the refresh timer in Safety & Tools).
        # Leaving them running leaks threads and crashes PySide6 at process exit.
        self._stop_tab_background_threads()
        try:
            self._shutdown_ollama()
        except Exception:
            pass
        try:
            WorkerAgent.shutdown_ollama_executor()
            from agents.providers.ollama_adapter import OllamaAdapter
            OllamaAdapter.shutdown_executor()
        except Exception:
            pass
        for worker in (getattr(self, "manager", None), getattr(self, "summarizer", None)):
            if worker is None:
                continue
            try:
                worker.stop()
                worker.wait(5000)
            except Exception:
                pass
            try:
                if worker.isRunning():
                    worker.terminate()
            except Exception:
                pass
        try:
            job_worker = getattr(self, "job_worker", None)
            if job_worker is not None and hasattr(job_worker, "close"):
                job_worker.close()
        except Exception:
            pass
        try:
            if getattr(self, "db", None) is not None:
                self.db.close()
        except Exception:
            pass

        # Stop Phase 6 services
        try:
            heartbeat = getattr(self, "heartbeat_system", None)
            if heartbeat and hasattr(heartbeat, "stop"):
                heartbeat.stop()
        except Exception:
            pass

    def _stop_tab_background_threads(self):
        """Stop QThread/QTimer resources owned by lazily-built tab widgets.

        Each tab is wrapped in a QScrollArea once built. Any widget exposing a
        ``cleanup()`` method (DualBrainControl, SafetyToolsTab, ...) is asked to
        stop its background work. Idempotent and never raises.
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return
        for index in range(tabs.count()):
            outer = tabs.widget(index)
            if outer is None:
                continue
            inner = outer.widget() if hasattr(outer, "widget") else outer
            cleanup = getattr(inner, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass
        # Also cover widgets referenced directly on the window (built eagerly).
        for attr in ("providers_gpu_tab", "safety_tools_tab"):
            widget = getattr(self, attr, None)
            cleanup = getattr(widget, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _shutdown_ollama(self):
        if not OLLAMA_AVAILABLE or not ollama:
            return
        try:
            # Unload the two active models (not just whatever is in .env).
            # Prefer the live instance overrides (set by save_settings / live
            # switch), falling back to the canonical env vars. This guarantees
            # the model actually resident in VRAM is released on exit.
            active_main = (getattr(self.worker, "_ollama_model_override", None)
                           or os.getenv("OLLAMA_MAIN_MODEL", "").strip()
                           or os.getenv("OLLAMA_MODEL", "").strip())
            active_chat = (getattr(self.worker, "_chat_ollama_model_override", None)
                           or os.getenv("OLLAMA_CHAT_MODEL", "").strip())
            for model in {active_main, active_chat}:
                if not model:
                    continue
                try:
                    # keep_alive:0 tells Ollama to release the model from VRAM
                    ollama.chat(model=model, messages=[], keep_alive=0)
                    self.log_signal.emit(f"[Ollama] unloaded model={model}")
                except Exception as e:
                    self.log_signal.emit(f"[Ollama] failed to unload {model}: {e}")
        except Exception:
            pass

    # --- Summarizer signal handlers ---
    def _on_summarizer_status(self, status: str, task: str):
        # Update sprite only; the tab's own connection handles labels
        state_map = {
            "Idle": "idle",
            "Summarizing": "thinking",
            "Paused": "idle",
        }
        sprite_state = state_map.get(status, "idle")
        self.summarizer_sprite.set_state(sprite_state)

    def _on_summarizer_paused(self, paused: bool):
        # Update pause button in the tab
        if hasattr(self, 'agents_tab'):
            self.agents_tab.set_summarizer_pause_button_state(paused)

    # --- Manager thought handlers ---
    def _on_worker_assigned(self, worker_name: str, task: str):
        pass

    def _on_job_found(self, jobs_json: str):
        try:
            import json
            jobs = json.loads(jobs_json)
            count = len(jobs)
            self._safe_log(f"🔍 {count} new gig(s) queued from JobSearch")
        except Exception:
            pass

    def _on_comms(self, direction: str, text: str):
        self.thought_panel.route("Comms", text, direction)

    def _on_chat_reply(self, trigger: str, text: str, thinking: str = ""):
            # Filter out heartbeat and task messages from chat window
            # These should go to notifications/subtle status, not chat
            if trigger.startswith("Heartbeat:") or trigger.startswith("Task:"):
                # Heartbeat/task decisions - update status, don't clutter chat
                if hasattr(self, 'agent_status_label'):
                    self.agent_status_label.setText(f"Action: {trigger}")
                return
        
            if hasattr(self, "agents_tab") and hasattr(self.agents_tab, "append_reply"):
                self.agents_tab.append_reply("Manager", f"[{trigger}] {text}", thinking)

    # ── EventBus bridge (P4 comms redesign) ──────────────────────────────────
    def _on_bus_event(self, msg):
        """Surface structured bus events in the GUI."""
        try:
            from agents.comms import MessageType
            mtype = msg.message_type
            p = msg.payload or {}
            if mtype == MessageType.OPPORTUNITY_UPDATE:
                opp = p.get("opportunity_id", "?")
                stage = p.get("current_stage") or p.get("stage") or p.get("status") or "?"
                self._safe_log(f"📊 Opportunity {opp} → {stage}")
            elif mtype == MessageType.EVIDENCE_UPDATE:
                self._safe_log(f"🔎 Evidence update: {p.get('evidence_id', '?')}")
            elif mtype == MessageType.NOTIFICATION:
                self._safe_log(f"🔔 {p.get('text', msg.text())}")
            elif mtype == MessageType.ERROR:
                self._safe_log(f"⚠️ Error ({msg.correlation_id}): {p.get('error', '')}")
        except Exception:
            pass

    # ── Phase 6 bridge methods ────────────────────────────────────────────────

    def _on_approval_queue_change(self, item):
        """Called when an approval item is enqueued. Refresh GUI panels."""
        try:
            approval_panel = getattr(self, "_approval_panel", None)
            if approval_panel and hasattr(approval_panel, "refresh_now"):
                approval_panel.refresh_now()
        except Exception:
            pass

    def _on_event_logged(self, event):
        """Called when an event is logged. Evaluate alerting rules."""
        try:
            engine = getattr(self, "alerting_engine", None)
            if engine:
                engine.process_event(event)
        except Exception:
            pass

    def _on_provider_config_changed(self, changes: dict):
        """Handle provider configuration changes at runtime (no restart needed)."""
        try:
            # Log the changes
            for key, value in changes.items():
                if "KEY" not in key and "SECRET" not in key:
                    self.log_signal.emit(f"[Provider] Config changed: {key}={value}")
                else:
                    self.log_signal.emit(f"[Provider] Config changed: {key}=***")
            
            # Re-detect providers
            from agents.provider_manager import ProviderManager
            pm = ProviderManager.instance()
            pm.detect_providers()
            
            # Refresh provider status in UI
            if hasattr(self, 'tabs'):
                # Refresh current tab if it's a provider-related tab
                pass
            
            self.log_signal.emit("[Provider] Configuration updated - changes applied")
        except Exception as e:
            self.log_signal.emit(f"[Provider] Error applying config changes: {e}")

    def _on_manager_thought(self, text: str):
        self.thought_panel.route("Manager", text)
        self.log_signal.emit(f"[Manager] thought: {text}")

    def _on_agent_status(self, status: str, task: str):
        # Update management tab status label
        if hasattr(self, 'agent_status_label'):
            self.agent_status_label.setText(f"Status: {status} — {task}")
        # Update heartbeat label in the agents tab
        if hasattr(self, 'agents_tab'):
            self.agents_tab.last_heartbeat_label.setText(
                f"Last heartbeat: {datetime.now().strftime('%H:%M:%S')}")
        self.log_signal.emit(f"[Manager] agent status: {status} — {task}")

    def _on_agent_thought(self, text: str):
        self.thought_panel.route("Agent", text)
        self.log_signal.emit(f"[Agent] thought: {text}")

    def _safe_log(self, msg: str):
        # v2.0.34an: always buffer, even if log_edit isn't built yet (Live Logs is a
        # lazy tab). This keeps pre-tab-build logs from being dropped; the buffer
        # is replayed into the widget when the tab is first built (_replay_log_buffer).
        if not hasattr(self, "_log_buffer"):
            self._log_buffer = []
        self._append_log(msg)

    def _replay_log_buffer(self):
        """Push all buffered log entries into the (now built) log_table widget.

        Called once when the Live Logs tab is first constructed. Re-applies the
        current filter so the replay matches what the user is looking at.
        """
        if not hasattr(self, "log_table") or self.log_table is None:
            return
        self.log_table.setRowCount(0)
        filter_text = (self.log_filter.text().lower()
                       if hasattr(self, "log_filter") and self.log_filter is not None else "")
        severity_filter = (self.log_severity_combo.currentText()
                          if hasattr(self, "log_severity_combo") and self.log_severity_combo is not None else "All")
        category_filter = (self.log_category_combo.currentText()
                          if hasattr(self, "log_category_combo") and self.log_category_combo is not None else "All")
        for e in self._log_buffer:
            if severity_filter != "All" and e.get("severity") != severity_filter:
                continue
            if category_filter != "All" and e.get("category") != category_filter:
                continue
            if filter_text and filter_text not in e.get("msg", "").lower():
                continue
            self._append_log_to_table(e)
        if getattr(self, "auto_scroll_logs", None) and self.auto_scroll_logs.isChecked():
            self.log_table.scrollToBottom()

    def _append_log_to_table(self, entry):
        """Append a single log entry to the log table widget."""
        if not hasattr(self, "log_table") or self.log_table is None:
            return
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        
        # Time
        ts_item = QTableWidgetItem(entry.get("ts", ""))
        ts_item.setForeground(QColor(entry.get("color", "#aaaaaa")))
        self.log_table.setItem(row, 0, ts_item)
        
        # Severity
        sev_item = QTableWidgetItem(entry.get("severity", "INFO"))
        sev_item.setForeground(QColor(entry.get("color", "#aaaaaa")))
        self.log_table.setItem(row, 1, sev_item)
        
        # Source
        src_item = QTableWidgetItem(entry.get("source", ""))
        src_item.setForeground(QColor(entry.get("color", "#aaaaaa")))
        self.log_table.setItem(row, 2, src_item)
        
        # Message
        msg_item = QTableWidgetItem(entry.get("msg", ""))
        msg_item.setForeground(QColor(entry.get("color", "#aaaaaa")))
        self.log_table.setItem(row, 3, msg_item)
        
        # Tokens/s
        tok_item = QTableWidgetItem(entry.get("tokens_sec", ""))
        tok_item.setForeground(QColor("#4caf50" if entry.get("tokens_sec") else "#666666"))
        self.log_table.setItem(row, 4, tok_item)
        
        # Limit rows
        if self.log_table.rowCount() > 5000:
            self.log_table.removeRow(0)

    def _append_log(self, msg: str, source: str = "", category: str = "", details: str = ""):
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Auto-detect severity from message content
        severity = "INFO"
        if "BLOCKED" in msg or "block" in msg.lower():
            severity = "BLOCKED"
        elif "ERROR" in msg or "❌" in msg or "fail" in msg.lower():
            severity = "ERROR"
        elif "Ollama" in msg or "LLM" in msg or "llm" in msg.lower():
            severity = "OLLAMA"
        elif "Manager" in msg or "Action" in msg or "Manager" in source:
            severity = "MANAGER"
        elif "warning" in msg.lower() or "⚠️" in msg:
            severity = "WARNING"
        elif "success" in msg.lower() or "✅" in msg or "ready" in msg.lower():
            severity = "SUCCESS"
        
        color = {
            "BLOCKED": "#ffcc00",
            "ERROR": "#ff4444",
            "OLLAMA": "#00b0ff",
            "MANAGER": "#00ccff",
            "INFO": "#aaaaaa",
            "WARNING": "#ff9800",
            "SUCCESS": "#4caf50",
        }.get(severity, "#aaaaaa")
        
        # Extract tokens/sec if present in message
        tokens_sec = ""
        if "tokens/s" in msg or "tok/s" in msg:
            import re
            match = re.search(r'([\d.]+)\s*(?:tokens|tok)/s', msg)
            if match:
                tokens_sec = f"{match.group(1)} tok/s"

        entry = {
            "ts": ts,
            "msg": msg,
            "source": source or "system",
            "category": category or "info",
            "details": details,
            "color": color,
            "severity": severity,
            "tokens_sec": tokens_sec,
        }
        self._log_buffer.append(entry)
        if len(self._log_buffer) > 5000:
            self._log_buffer.pop(0)

        # Update the table widget if it exists
        if hasattr(self, "log_table") and self.log_table is not None:
            try:
                self._append_log_to_table(entry)
            except Exception:
                pass

    def _set_log_auto_scroll(self, checked: bool):
        if checked and hasattr(self, "log_table"):
            self.log_table.scrollToBottom()

    def _apply_log_filter(self):
        # PERF: debounce filter rebuilds with a single-shot timer so rapid
        # keystrokes don't rebuild the buffer on every character.
        if not hasattr(self, "_filter_debounce"):
            self._filter_debounce = QTimer()
            self._filter_debounce.setSingleShot(True)
            self._filter_debounce.setInterval(200)
            self._filter_debounce.timeout.connect(self._do_apply_log_filter)
        if not hasattr(self, "log_table"):
            return
        self._filter_debounce.start()

    def _do_apply_log_filter(self):
        if not hasattr(self, "log_table"):
            return
        self.log_table.setRowCount(0)
        filter_text = self.log_filter.text().lower()
        severity_filter = self.log_severity_combo.currentText()
        category_filter = (self.log_category_combo.currentText()
                          if hasattr(self, "log_category_combo") else "All")
        for e in self._log_buffer:
            if severity_filter != "All" and e.get("severity") != severity_filter:
                continue
            if category_filter != "All" and e.get("category") != category_filter:
                continue
            if filter_text and filter_text not in e.get("msg", "").lower():
                continue
            self._append_log_to_table(e)
        if getattr(self, "auto_scroll_logs", None) and self.auto_scroll_logs.isChecked():
            self.log_table.scrollToBottom()

    def _clear_log(self):
        self._log_buffer.clear()
        if hasattr(self, "log_table"):
            self.log_table.setRowCount(0)

    def _toggle_thought_panel(self, checked):
        if checked:
            self.thought_panel.hide()
            self.show_thoughts_action.setText("Show Thought Panel")
        else:
            self.thought_panel.show()
            self.thought_panel.raise_()
            self.show_thoughts_action.setText("Hide Thought Panel")

    def create_ui(self):
        # Centered title header at the top of the program
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        try:
            from version import __version__
        except Exception:
            __version__ = "2.1.1"
        title_lbl = QLabel(f"MrBot1000 v{__version__}")
        title_lbl.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        title_lbl.setStyleSheet(
            "font-size:15px; font-weight:bold; padding:8px 0px; "
            "color:#4fc3f7; background-color:#1a1a1f; border-bottom:1px solid #2b3034;"
        )
        container_layout.addWidget(title_lbl)

        tabs = QTabWidget()
        self.tabs = tabs
        container_layout.addWidget(tabs)
        self.setCentralWidget(container)

        # v2.0.34ag (A5): lazy-build tabs on first show — faster startup + lower
        # peak memory. Each tab starts as a placeholder; the real builder runs once
        # the operator first opens it. Widget attributes (self.model_info_browser,
        # self.ollama_*_gpu_spin, …) are only needed after the tab is visible, so
        # deferring is safe.
        self._tab_builders = []  # list of (index, builder_fn, built_flag)
        tab_specs = [
                    ("Management",     self.create_management_tab),
                    ("Providers & GPU", self.create_providers_gpu_tab),
                    ("Model Library",  self.create_model_library_tab),
                    ("Safety & Tools", self.create_safety_tools_tab),
                    ("Chat",           self.create_chat_tab),
                    ("Dialogue",       self.create_dialogue_tab),
                    ("Browse Root",    self.create_file_browser_tab),
                    ("Payments",       self.create_payments_tab),
                    ("Earnings",       self.create_earnings_tab),
                    ("Insights",       self.create_insights_tab),
                    ("Approvals",      self.create_approval_tab),
                    ("Opportunities",  self.create_opportunities_tab),
                    ("Paper Trading",  self.create_paper_trading_tab),
                    ("Analytics",      self.create_analytics_tab),
                    ("Reputation",     self.create_reputation_tab),
                    ("Data Explorer",  self.create_data_explorer_tab),
                    ("Settings",       self.create_settings_tab),
                    ("Live Logs",      self.create_logs_tab),
                    ("DB Stats",       self.create_db_stats_tab),
                ]
        for label, builder in tab_specs:
            idx = tabs.addTab(QLabel("Loading…"), label)
            self._tab_builders.append([idx, builder, False])

        # Management is the startup dashboard and is intentionally built eagerly;
        # Providers & GPU is also built eagerly because it owns the primary
        # provider/GPU status surface and must never remain on a Loading label.
        self._ensure_tab_built(0)
        self._ensure_tab_built(1)
        self._ensure_tab_built(2)

        # Auto-populate the Ollama model dropdowns the first time the Settings
        # tab is opened, so you don't have to click Refresh manually (v2.0.20h).
        self._ollama_autorefresh_done = False
        self._settings_tab_index = next(
            i for i, (lbl, _) in enumerate(tab_specs) if lbl == "Settings")
        tabs.currentChanged.connect(self._on_tab_changed)

        # ── Auto-start llama-server on app launch ─────────────────────────────
        # v2.1: Auto-start is DISABLED. Models must be started manually from
        # the Providers & GPU tab. This prevents the brains from auto-running
        # at startup when the operator doesn't want them to.
        self._auto_start_timer = None

        # Apply the saved presentation mode after the menu actions exist.
        QTimer.singleShot(0, lambda: self._set_window_mode(self._window_mode, persist=False))

    def _size_for_screen(self):
        """Choose a usable initial size on the current display."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        available = screen.availableGeometry()
        width = min(1450, max(960, int(available.width() * 0.92)))
        height = min(950, max(640, int(available.height() * 0.90)))
        self.resize(min(width, available.width()), min(height, available.height()))
        self.move(
            available.left() + max(0, (available.width() - self.width()) // 2),
            available.top() + max(0, (available.height() - self.height()) // 2),
        )

    def _set_window_mode(self, mode: str, persist: bool = True):
        """Switch presentation mode without rebuilding or reparenting the UI."""
        mode = mode if mode in {"normal", "maximized", "fullscreen", "borderless"} else "normal"
        if self.isFullScreen():
            self.showNormal()
        if self._normal_window_geometry is None and not self.isMaximized():
            self._normal_window_geometry = self.geometry()
        self.setWindowFlag(Qt.FramelessWindowHint, mode == "borderless")
        if mode == "fullscreen":
            self.showFullScreen()
        elif mode == "maximized":
            self.showMaximized()
        else:
            self.showNormal()
            if mode == "borderless":
                screen = self.screen() or QApplication.primaryScreen()
                if screen is not None:
                    self.setGeometry(screen.availableGeometry())
            elif self._normal_window_geometry is not None:
                self.setGeometry(self._normal_window_geometry)
            else:
                self._size_for_screen()
        self._window_mode = mode
        for name, action in getattr(self, "_window_mode_actions", {}).items():
            action.blockSignals(True)
            action.setChecked(name == mode)
            action.blockSignals(False)
        if persist:
            os.environ["MRBOT_WINDOW_MODE"] = mode
            try:
                set_env_values({"MRBOT_WINDOW_MODE": mode})
            except Exception:
                pass

    def _log(self, msg):
        """Write a log line to the Providers & GPU tab if available.
        Defers Management tab build to event loop so startup isn't blocked
        by synchronous widget construction on every log emission."""
        providers_tab = getattr(self, "providers_gpu_tab", None)
        if providers_tab is not None and hasattr(providers_tab, "append_log"):
            providers_tab.append_log(msg)
        # Defer Management tab build to next event loop cycle so it doesn't
        # block on every log emission during startup (v2.0.36k).
        if not hasattr(self, "_management_build_deferred"):
            self._management_build_deferred = True
            QTimer.singleShot(0, lambda: self._ensure_tab_built(0))

    def _toggle_summarizer_pause(self, checked):
        self.summarizer.set_paused(checked)

    def _show_thoughts(self):
        self.thought_panel.show()
        self.thought_panel.raise_()
        self.show_thoughts_action.setChecked(False)

    def _toggle_pause(self, checked):
        self.manager.set_paused(checked)
        # Update the button in the tab
        if hasattr(self, 'agents_tab'):
            self.agents_tab.set_pause_button_state(checked)
            # Update heartbeat label text
            if checked:
                self.agents_tab.heartbeat_label.setText("Heartbeat: PAUSED")
            else:
                self.agents_tab.heartbeat_label.setText(
                    f"Heartbeat every {self.manager.HEARTBEAT_INTERVAL}s")
        self.thought_panel.route(
            "System", "Heartbeat paused" if checked else "Heartbeat resumed")

    def _human_send(self, text: str):
        # v2.0.22b + P2 comms redesign: route chat through the EventBus as a
        # structured USER_REQUEST (destination "chat" = Chat interface/Summarizer
        # thread). The Summarizer forwards task/command intents back to the
        # Manager as a structured TASK_REQUEST — no arbitrary prompt loops.
        # Falls back to the direct queue path if the bus/summarizer is unavailable.
        try:
            from agents.comms import EventBus, Message, MessageType
            bus = EventBus.instance()
            bus.publish(Message(MessageType.USER_REQUEST, "gui", "chat",
                                payload={"text": text}))
        except Exception:
            if getattr(self, "summarizer", None) is not None:
                self.summarizer.send_human_message(text)
            else:
                self.manager.send_human_message(text)
        self.thought_panel.route("Comms", text, "Human→M")

    # ── A2: Verify-then-mark-paid ──────────────────────────────────────────────
    def _build_payout_verifier(self):
        try:
            from agents.payout_verifier import PayoutVerifier
            return PayoutVerifier()
        except Exception:
            return None

    def _verify_and_mark_paid(self):
        """GUI: verify a payout (on-chain or manual ref) before marking paid.

        Uses the LIVE earning pipeline + its lifecycle (the one the dashboard reads)
        so a verified payout is actually reflected in the revenue report. Routes
        straight through `mark_paid_verified` with the verifier's real evidence
        (no note-hack that would discard crypto verification).
        """
        opp_id = self.pay_opp_id.text().strip()
        try:
            amount = float(self.pay_amount.text().strip() or "0")
        except ValueError:
            self.pay_status.setText("Payout: amount must be numeric")
            return
        wallet = self.pay_wallet.text().strip()
        ref = self.pay_ref.text().strip()
        if not opp_id:
            self.pay_status.setText("Payout: opportunity id required")
            return

        # Must have a live pipeline to record against; otherwise verification is moot.
        pipe = getattr(self, "earning_pipeline", None)
        if pipe is None or getattr(pipe, "lifecycle", None) is None:
            self.pay_status.setText("Payout: earning pipeline unavailable")
            return

        verifier = self._build_payout_verifier()
        evidence = None
        if verifier is not None:
            if wallet:
                try:
                    from agents.wallet_manager import WalletManager, resolve_wallet_root
                    wm = WalletManager(root_folder=str(
                        resolve_wallet_root(getattr(pipe, "db_path", None))))
                    evidence = verifier.verify_crypto(wm, wallet, amount)
                except Exception as e:
                    self.pay_status.setText(f"Payout: wallet check failed: {e}")
                    return
            elif ref:
                evidence = verifier.verify_manual(amount, ref)
            else:
                self.pay_status.setText("Payout: need wallet OR txn reference to verify")
                return

        # Build/ensure a lifecycle state, then record via mark_paid_verified.
        # `evidence` is a VerificationEvidence (an Evidence subclass) — pass the object so
        # the lifecycle records it in the EvidenceStore and gates the transition on policy.
        try:
            state = pipe.lifecycle.mark_paid_verified(
                opp_id, amount=amount, evidence=evidence)
        except Exception as e:
            self.pay_status.setText(f"Payout: record failed: {e}")
            self.log_signal.emit(f"[Payout] record error: {e}")
            return

        if state is not None and state.status == "paid":
            self.pay_status.setText(
                f"Payout: VERIFIED + marked paid ({evidence.method if evidence else 'n/a'})")
            # C2 (H39 fix): record the REAL acceptance into the submission ramp
            # so win-rate reflects verified payouts, not mere submissions.
            try:
                pipe = getattr(self, "earning_pipeline", None)
                if pipe is not None:
                    from agents.submission_ramp import get_ramp
                    opp = pipe.memory.get_opportunity_history(opp_id)
                    platform = (opp or {}).get("platform") or "unknown"
                    get_ramp(getattr(pipe, "memory", None)).record_accept(platform)
            except Exception:
                pass
        else:
            self.pay_status.setText("Payout: NOT verified — left as submitted (audit logged)")
        self.log_signal.emit(f"[Payout] {self.pay_status.text()}")

    # ── A1: Gig proposal review + human-confirmed submission ──────────────────
    def _build_upwork_client(self):
        """Construct an UpworkClient from .env creds (or None if absent)."""
        try:
            import os

            from agents.upwork_client import UpworkClient
            cid = os.getenv("UPWORK_CLIENT_ID", "")
            csec = os.getenv("UPWORK_CLIENT_SECRET", "")
            at = os.getenv("UPWORK_ACCESS_TOKEN", "")
            rt = os.getenv("UPWORK_REFRESH_TOKEN", "")
            if not (cid and csec and at and rt):
                return None
            return UpworkClient(cid, csec, at, rt)
        except Exception:
            return None

    def _build_reviewer(self):
        try:
            from agents.proposal_reviewer import ProposalReviewer
            return ProposalReviewer()
        except Exception:
            return None

    def _review_proposal_draft(self):
        """Run the review gate on the current draft + job description and show the result."""
        job_desc = self.proposal_job_desc.toPlainText().strip()
        draft = self.proposal_draft.toPlainText().strip()
        if not draft:
            self.proposal_status.setText("Proposal: no draft to review")
            return
        reviewer = self._build_reviewer()
        if reviewer is None:
            self.proposal_status.setText("Proposal: reviewer unavailable")
            return
        # Use the pasted job description so the requirement-coverage check is real
        # (not a no-op). Without a description, coverage defaults to pass.
        res = reviewer.review(job_desc, draft, job_title=self.proposal_job_id.text().strip() or "draft")
        self.proposal_status.setText(f"Review: {'PASS' if res.can_submit else 'BLOCK'} — {res.summary}")

    def _submit_proposal_gui(self):
        """GUI entry: review gate -> human confirm -> submit via pipeline (records lifecycle)."""
        job_id = self.proposal_job_id.text().strip()
        job_desc = self.proposal_job_desc.toPlainText().strip()
        draft = self.proposal_draft.toPlainText().strip()
        if not job_id or not draft:
            self.proposal_status.setText("Proposal: job_id + draft required")
            return
        reviewer = self._build_reviewer()
        res = None
        if reviewer is not None:
            res = reviewer.review(job_desc, draft, job_title=job_id)
            if not res.can_submit:
                self.proposal_status.setText(f"Proposal: BLOCKED — {res.summary}")
                self.log_signal.emit(f"[Proposal] blocked by review gate: {res.summary}")
                return

        # Human confirmation (triple-confirm style, mirrors payout security).
        preview = (f"Submit Upwork proposal\n\nJob: {job_id}\n\n"
                   f"{res.summary if res else ''}\n\nCover:\n{draft[:600]}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Confirm Proposal Submission")
        box.setText(preview)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.button(QMessageBox.Yes).setText("Submit")
        if box.exec() != QMessageBox.Yes:
            self.proposal_status.setText("Proposal: cancelled by user")
            return

        # Dispatch off-thread to avoid blocking the GUI on network I/O. Route
        # through EarningPipeline.submit_gig_proposal so the lifecycle records
        # applied/submitted and the review gate re-runs as a safety net.
        self.proposal_status.setText("Proposal: submitting…")
        client = self._build_upwork_client()
        if client is None:
            self.proposal_status.setText("Proposal: no Upwork credentials in .env")
            self.log_signal.emit("[Proposal] no Upwork credentials; cannot submit live")
            return

        import earning_pipeline as EP
        opp = EP.Opportunity(id=job_id, source="gig", type="gig",
                             title=self.proposal_job_id.text().strip(),
                             description=job_desc, platform="Upwork",
                             payment_amount=0.0, estimated_usd_value=0.0,
                             status="new")

        # Small dedicated thread: run the (blocking) pipeline submit off the GUI
        # thread, then surface the result back on the GUI thread.
        class _SubmitThread(QThread):
            done = Signal(object)
            def __init__(self, pipe, o, cov, rev, cli):
                super().__init__()
                self.pipe, self.o, self.cov, self.rev, self.cli = pipe, o, cov, rev, cli
            def run(self):
                try:
                    self.done.emit(self.pipe.submit_gig_proposal(
                        self.o, self.cov, reviewer=self.rev,
                        confirm_cb=lambda s: True,  # already confirmed in GUI
                        client=self.cli))
                except Exception:
                    self.done.emit(None)  # signal error
        pipe = getattr(self, "earning_pipeline", None)
        if pipe is None:
            self.proposal_status.setText("Proposal: earning pipeline unavailable")
            self.log_signal.emit("[Proposal] no earning pipeline; cannot submit live")
            return

        self._submit_worker = _SubmitThread(pipe, opp, draft, reviewer, client)
        self._submit_worker.done.connect(
            lambda r: self._on_proposal_submitted(job_id, r))
        self._submit_worker.start()

    def _on_proposal_submitted(self, job_id, result):
        if result is None:
            self.proposal_status.setText("Proposal: submit error")
            self.log_signal.emit(f"[Proposal] submit error for {job_id}")
            return
        if not result.success:
            self.proposal_status.setText(f"Proposal: {result.action_taken}")
            self.log_signal.emit(f"[Proposal] {result.message}")
            return
        pid = (result.message or "").replace("Submitted proposal ", "").replace(f" for {job_id}", "")
        msg = f"Submitted proposal {pid} for {job_id}"
        self.proposal_status.setText(f"Proposal: {msg}")
        self.proposals_list.addItem(f"{job_id} → {pid or 'pending'}")
        self.log_signal.emit(f"[Proposal] {msg}")


    def _format_ago(self, seconds: float) -> str:
        """Format seconds as human-readable 'ago' string."""
        if seconds <= 0:
            return "just now"
        if seconds < 60:
            return f"{int(seconds)}s ago"
        if seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m ago"
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours}h {mins}m ago"

    def _refresh_stream_health(self):
        """v2.0.34ac (G5): render live steady-stream telemetry into the Management tab."""
        try:
            mgr = getattr(self, "manager", None)
            if mgr is None or not hasattr(mgr, "get_runtime_stats"):
                return
            s = mgr.get_runtime_stats()
            healthy = s.get("healthy", True)
            color = "#00ff88" if healthy else "#ff5555"
            lines = [
                f"Status: <b style='color:{color}'>{'HEALTHY' if healthy else 'DEGRADED'}</b>"
                + (" (paused)" if s.get("paused") else ""),
                f"Cycles: {s.get('cycles', 0)} · "
                f"Jobs: {s.get('jobs_processed', 0)} · "
                f"Chats: {s.get('chats_handled', 0)} · "
                f"Tasks: {s.get('tasks_handled', 0)}",
                f"Throughput: {s.get('throughput_per_min', 0)} work/min · "
                f"last cycle: {s.get('last_cycle_ms', 0)} ms",
                f"Queued → tasks: {s.get('pending_tasks', 0)} · "
                f"chat: {s.get('pending_chat', 0)} · "
                f"jobs: {s.get('pending_jobs', 0)}",
                f"Errors: {s.get('errors', 0)} (streak {s.get('error_streak', 0)}) · "
                f"last ok {self._format_ago(s.get('last_success_ago_s', 0))}",
            ]
            self.stream_health_label.setText("<br>".join(lines))
        except Exception:
            pass  # never break the GUI timer

    def _memory_db(self):
        """Return the SummarizerDB behind the manager's memory, or None."""
        mgr = getattr(self, "manager", None)
        summ = getattr(mgr, "_summarizer", None)
        # SummarizerThread stores its DB as `summ_db` (not `db`).
        db = getattr(summ, "summ_db", None) or getattr(summ, "db", None)
        return db if hasattr(db, "get_role_memory") else None

    def _refresh_memory_panel(self):
        """v2.0.34ad (F7): render per-role memory + long-term notes into the panel."""
        try:
            db = self._memory_db()
            if db is None:
                self.memory_view.setPlainText("(memory store unavailable)")
                return
            parts = []
            for role in ("chat", "main"):
                rows = db.get_role_memory(role, limit=10)
                if rows:
                    head = "CHAT memory:" if role == "chat" else "CEO memory:"
                    parts.append(head)
                    for r in rows[-6:]:
                        parts.append(f"  - {r['text'][:160]}")
            notes = db.get_notes(limit=10)
            if notes:
                parts.append("Long-term notes:")
                for n in notes[-6:]:
                    parts.append(f"  [{n['topic']}] {n['text'][:160]}")
            self.memory_view.setPlainText("\n".join(parts) if parts else "(empty)")
        except Exception:
            pass  # never break the GUI timer

    def _clear_memory(self, what: str):
        """v2.0.34ad (F7): clear chat/CEO memory or long-term notes on operator click."""
        try:
            db = self._memory_db()
            if db is None:
                return
            if what == "chat":
                db.clear_role_memory("chat")
            elif what == "main":
                db.clear_role_memory("main")
            elif what == "notes":
                db.clear_notes()
            self._refresh_memory_panel()
        except Exception:
            pass

    def _apply_llm_budget(self, text: str):
        """A4: apply the daily LLM budget cap live (no restart)."""
        try:
            val = float(text or "0")
        except ValueError:
            val = 0.0
        os.environ["LLM_DAILY_BUDGET_USD"] = f"{val:.2f}"
        self.log_signal.emit(f"[Budget] daily LLM budget set to ${val:.2f}"
                             f"{' (OFF)' if val <= 0 else ''}")

    def _apply_winrate(self, text: str):
        """A5: apply the win-rate auto-decline threshold live (percent, no restart)."""
        try:
            pct = float(text or "0")
        except ValueError:
            pct = 20.0
        os.environ["WINRATE_DECLINE_BELOW"] = f"{pct:.0f}"
        self.log_signal.emit(f"[WinRate] auto-decline threshold set to {pct:.0f}%"
                             f"{' (OFF)' if pct <= 0 else ''}")

    def select_research_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Research Folder")
        if folder:
            self.worker.research_folder = folder
            self.research_folder_label.setText(f"Research folder: {folder}")
            self.log_signal.emit(f"Research folder set: {folder}")
            self.thought_panel.route(
                "System", f"Research folder set: {folder}")
            self.manager.invalidate_cache()
            self.manager._reviewed_files.clear()

    def force_safe_improve(self):
        self.manager.queue_task(
            "Self-improvement: review codebase and propose one concrete upgrade")
        self.log_signal.emit("Self-improvement task queued")

    def force_research_rescan(self):
        self.manager.invalidate_cache()
        self.manager.queue_task(
            "Research re-scan: review all files and summarize key findings")
        self.log_signal.emit("Research re-scan queued")

    def clear_file_cache(self):
        reply = QMessageBox.question(
            self, "Clear Cache",
            "Delete all cached file contents?",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.db.clear_file_cache()
            self.log_signal.emit("File cache cleared")

    def refresh_db_stats(self):
        """Refresh DB Stats tab with data from database."""
        # Guard: new DB Stats tab uses table widgets
        if getattr(self, "_shutting_down", False) or not hasattr(self, "db_stat_calls"):
            return
        db = getattr(self, "db", None)
        if db is None or getattr(db, "_conn", None) is None:
            return
        try:
            stats = db.get_llm_stats()
            props = db.count_proposals()
            disc = {}
            if getattr(self.manager, "earning_pipeline", None) is not None:
                try:
                    disc = self.manager.get_discovery_summary()
                except Exception:
                    disc = {}
            
            # Update stat cards
            self.db_stat_calls.value_label.setText(str(stats.get("total_calls", 0)))
            self.db_stat_errors.value_label.setText(str(stats.get("errors", 0)))
            avg_lat = int(stats.get("avg_latency_ms") or 0)
            self.db_stat_avg_latency.value_label.setText(f"{avg_lat} ms")
            self.db_stat_chars.value_label.setText(f"{int(stats.get('total_chars', 0)):,}")
            self.db_stat_cost.value_label.setText(f"${stats.get('total_cost', 0):.2f}")
            self.db_stat_tokens_sec.value_label.setText(f"{stats.get('avg_tokens_per_second', 0):.1f}")
            self.db_stat_uptime.value_label.setText(f"{stats.get('uptime_hours', 0)}h")
            self.db_stat_db_size.value_label.setText(f"{stats.get('db_size_mb', 0)} MB")
            
            # Update provider table
            self.provider_table.setRowCount(0)
            provider_stats = stats.get("by_provider", {})
            for provider, pstats in provider_stats.items():
                row = self.provider_table.rowCount()
                self.provider_table.insertRow(row)
                self.provider_table.setItem(row, 0, QTableWidgetItem(str(provider)))
                self.provider_table.setItem(row, 1, QTableWidgetItem(str(pstats.get("calls", 0))))
                self.provider_table.setItem(row, 2, QTableWidgetItem(str(pstats.get("errors", 0))))
                self.provider_table.setItem(row, 3, QTableWidgetItem(f"{pstats.get('avg_ms', 0):.0f}"))
                self.provider_table.setItem(row, 4, QTableWidgetItem(f"{pstats.get('avg_tok_s', 0):.1f}"))
            
            # Update model table
            self.model_table.setRowCount(0)
            model_stats = stats.get("by_model", {})
            for model, mstats in model_stats.items():
                row = self.model_table.rowCount()
                self.model_table.insertRow(row)
                self.model_table.setItem(row, 0, QTableWidgetItem(str(model)))
                self.model_table.setItem(row, 1, QTableWidgetItem(str(mstats.get("calls", 0))))
                self.model_table.setItem(row, 2, QTableWidgetItem(str(mstats.get("tokens_in", 0))))
                self.model_table.setItem(row, 3, QTableWidgetItem(str(mstats.get("tokens_out", 0))))
                self.model_table.setItem(row, 4, QTableWidgetItem(f"{mstats.get('avg_tok_s', 0):.1f}"))
            
            # Update recent calls table
            self.db_calls_table.setRowCount(0)
            for c in db.get_recent_llm_calls(20):
                ts = db.ts_to_str(c["ts"])
                status = "OK" if not c["error"] else "ERR"
                row = self.db_calls_table.rowCount()
                self.db_calls_table.insertRow(row)
                self.db_calls_table.setItem(row, 0, QTableWidgetItem(ts))
                self.db_calls_table.setItem(row, 1, QTableWidgetItem(str(c.get("provider", ""))))
                self.db_calls_table.setItem(row, 2, QTableWidgetItem(str(c.get("model", ""))[:30]))
                self.db_calls_table.setItem(row, 3, QTableWidgetItem(str(c.get("prompt_tokens", 0))))
                self.db_calls_table.setItem(row, 4, QTableWidgetItem(str(c.get("completion_tokens", 0))))
                self.db_calls_table.setItem(row, 5, QTableWidgetItem(f"${c.get('cost_usd', 0):.4f}"))
                self.db_calls_table.setItem(row, 6, QTableWidgetItem(f"{c.get('tokens_per_second', 0):.1f}"))
            
            # Update event table
            self.event_table.setRowCount(0)
            recent_events = db.get_recent_events(100)
            for e in recent_events:
                ts = db.ts_to_str(e.get("ts", 0))
                row = self.event_table.rowCount()
                self.event_table.insertRow(row)
                self.event_table.setItem(row, 0, QTableWidgetItem(ts))
                self.event_table.setItem(row, 1, QTableWidgetItem(str(e.get("event_type", ""))))
                self.event_table.setItem(row, 2, QTableWidgetItem(str(e.get("source", ""))))
                self.event_table.setItem(row, 3, QTableWidgetItem(str(e.get("message", ""))[:100]))
            
            # Also update old widgets if they exist (back-compat)
            if hasattr(self, "db_stats_label"):
                parts = [
                    f"Calls: {stats.get('total_calls',0)}",
                    f"OK: {stats.get('successes',0)}",
                    f"Err: {stats.get('errors',0)}",
                    f"Avg: {avg_lat}ms",
                    f"Chars: {int(stats.get('total_chars') or 0):,}",
                    f"Proposals: {props}",
                ]
                self.db_stats_label.setText("  ".join(parts))
            
        except Exception as e:
            if hasattr(self, "db_stats_label"):
                self.db_stats_label.setText(f"DB error: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_review_queue(self):
        """Populate the review queue list + counts from the instruction gate."""
        try:
            gate = getattr(self, "instruction_gate", None)
            if gate is None:
                return
            counts = gate.counts()
            self.review_counts_label.setText(
                f"Pending: {counts.get('pending',0)}  "
                f"Allowed: {counts.get('allowed',0)}  "
                f"Blocked: {counts.get('blocked',0)}")
            self.review_list.clear()
            for it in gate.pending(50):
                title = it.get("title") or it.get("url")
                self.review_list.addItem(
                    f"[#{it['id']}] {title}  ({it.get('kind','skill.md')})")
        except Exception as e:
            self.review_counts_label.setText(f"Review queue error: {e}")

    def _review_selected(self, approve: bool):
        """Human-in-the-loop decision on the selected pending instruction."""
        gate = getattr(self, "instruction_gate", None)
        if gate is None:
            return
        item = self.review_list.currentItem()
        if not item:
            return
        # Parse the id from "[#ID] ..." 
        text = item.text()
        import re as _re
        m = _re.match(r"\[#(\d+)\]", text)
        if not m:
            return
        qid = int(m.group(1))
        # Resolve the quarantine row to get url + hash for the allow/blacklist.
        row = None
        for it in gate.pending(200):
            if it["id"] == qid:
                row = it
                break
        if row is None:
            return
        # related: persist url + skill.md + content_hash so it is ALWAYS ignored.
        related = f"{row.get('url','')} | skill.md | {row.get('content_hash','')}"
        try:
            status = gate.review(qid, approve, url=row.get("url", ""),
                                 content_hash=row.get("content_hash", ""),
                                 related=related)
            self.log_signal.emit(
                f"[Review] instruction #{qid} -> {status} "
                f"({'APPROVED' if approve else 'BLACKLISTED'})")
        except Exception as e:
            self.log_signal.emit(f"[Review] error: {e}")
        self._refresh_review_queue()

    def _run_http(self, method, url, tag, **kwargs):
        w = HttpWorker(method, url, tag, **kwargs)
        w.result.connect(self._on_http_result)
        self._http_workers.append(w)
        w.finished.connect(
            lambda: self._http_workers.remove(w)
            if w in self._http_workers else None)
        w.start()

    def _on_http_result(self, tag: str, response):
        if tag == "balance":
            if response and response.ok:
                try:
                    bal = response.json().get("available_usdc", 0)
                    if hasattr(self, "balance_label"):
                        self.balance_label.setText(f"Balance: ${bal:.2f} USDC")
                except Exception:
                    pass
            else:
                self.log_signal.emit("Failed to fetch balance")
        elif tag == "payout":
            ok = response and response.ok
            self.log_signal.emit(
                "Payout sent" if ok
                else f"Payout failed: {response.text if response else 'no response'}")
        elif tag == "register":
            if response and response.status_code == 201:
                try:
                    data = response.json()
                    self.worker.api_key  = data["api_key"]
                    self.manager.api_key = data["api_key"]
                    self.log_signal.emit("Registration SUCCESS")
                    self.status_label.setText("Agent status: Registered ✓")
                except Exception as e:
                    self.log_signal.emit(f"Register parse error: {e}")
            else:
                err = response.text if response else "no response"
                self.log_signal.emit(f"Registration failed: {err}")

    def refresh_balance(self):
        """Shows wallet address as balance display.

        Guarded against the lazy Payments tab: balance_label only exists once the
        Payments tab has been built. The balance timer can fire before that, so skip
        silently (v2.0.34an, fixes an AttributeError crash).
        """
        if not hasattr(self, "balance_label"):
            return
        wallet = os.getenv("ATOMIC_SOLANA_ADDRESS", "")
        if wallet:
            self.balance_label.setText(f"Wallet: {wallet[:8]}...{wallet[-4:] if len(wallet) > 8 else ''}")
        else:
            self.balance_label.setText("Balance: Wallet not set")

    def manual_payout(self):
        """SECURE: Requires triple confirmation for any payout action.
        
        Security Notes:
        - Does NOT auto-send money - requires explicit user confirmation
        - Logs all payout attempts for audit trail
        - Amount clamped to reasonable max to prevent accidental large transfers
        """
        if not self.worker.api_key and not os.getenv("ATOMIC_SOLANA_ADDRESS"):
            self.log_signal.emit("Cannot payout: No wallet configured")
            QMessageBox.warning(self, "Wallet Not Set", 
                "Please configure ATOMIC_SOLANA_ADDRESS in settings first.")
            return
        
        try:
            amount = float(self.amount_input.text().strip())
            if amount <= 0:
                raise ValueError("amount must be positive")
            # Security: Cap at $10,000 max to prevent accidental large transfers
            if amount > 10000:
                QMessageBox.warning(self, "Amount Too Large", 
                    "Maximum payout amount is $10,000. Please enter a smaller amount.")
                self.log_signal.emit(f"[SEC] Payout blocked: amount ${amount} exceeds cap")
                return
        except ValueError as e:
            self.log_signal.emit(f"Invalid amount: {e}")
            return
        
        # Security: Triple confirmation for payout
        wallet_prefix = (os.getenv("ATOMIC_SOLANA_ADDRESS") or "")[:8] + "..."
        reply = QMessageBox.question(
            self, "Confirm Payout",
            f"⚠️ SECURITY WARNING\n\n"
            f"Send ${amount:.2f} to wallet {wallet_prefix}?\n"
            f"This action cannot be easily reversed.\n\n"
            f"Type 'CONFIRM' to proceed:",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            self.log_signal.emit("[SEC] Payout cancelled by user")
            return
            
        confirm_text = self.amount_input.text()
        if confirm_text.strip().upper() != "CONFIRM":
            self.log_signal.emit("[SEC] Payout not confirmed (typing required)")
            return
        
        self.log_signal.emit(f"[PAYOUT] Processing ${amount:.2f} to {wallet_prefix}")
        self.history_list.addItem(
            f"{datetime.now().strftime('%H:%M')} → ${amount:.2f} PENDING MANUAL")
        QMessageBox.information(self, "Payout Submitted",
            f"${amount:.2f} payout request queued.\n"
            f"Agent will need to complete manual transfer.\n"
            f"Check logs for details.")

    # ── Earnings Pipeline ─────────────────────────────────────────────

    def _run_earning_cycle(self):
        source = self.pipeline_source_combo.currentText()
        max_risk = self.pipeline_max_risk_combo.currentText()
        sources = None if source == "all" else [source]
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "earning.db")

        tab = getattr(self, "_earning_tab", None)
        if tab and hasattr(tab, "run_full_cycle"):
            tab.run_full_cycle(sources=sources, max_risk=max_risk, db_path=db_path)
            return

        self.pipeline_status_label.setText("Running...")
        self.run_cycle_btn.setEnabled(False)
        self._pipeline_worker = PipelineWorker(
            sources=sources, max_risk=max_risk, db_path=db_path,
            log_fn=self.log_signal.emit)
        self._pipeline_worker.finished.connect(self._on_cycle_finished)
        self._pipeline_worker.errored.connect(self._on_cycle_error)
        self._pipeline_worker.start()

    def _on_cycle_finished(self, result):
        try:
            self.pipeline_status_label.setText(
                f"Done: {getattr(result, 'message', 'complete')}")
            self.last_cycle_label.setText(datetime.now().strftime("%H:%M:%S"))
            count = int(self.cycle_count_label.text() or "0")
            self.cycle_count_label.setText(str(count + 1))
            self._refresh_earnings_dashboard()
        except Exception as e:
            self.log_signal.emit(f"[Pipeline] Error: {e}")
        finally:
            tab = getattr(self, "_earning_tab", None)
            if tab and hasattr(tab, "run_cycle_btn"):
                tab.run_cycle_btn.setEnabled(True)
            elif hasattr(self, "run_cycle_btn"):
                self.run_cycle_btn.setEnabled(True)

    def _on_cycle_error(self, errmsg):
        self.log_signal.emit(f"[Pipeline] Error: {errmsg}")
        self.pipeline_status_label.setText(f"Error: {errmsg}")
        tab = getattr(self, "_earning_tab", None)
        if tab and hasattr(tab, "run_cycle_btn"):
            tab.run_cycle_btn.setEnabled(True)
        elif hasattr(self, "run_cycle_btn"):
            self.run_cycle_btn.setEnabled(True)

    def _refresh_earnings_dashboard(self):
        tab = getattr(self, "_earning_tab", None)
        if tab and hasattr(tab, "refresh_pipeline"):
            tab.refresh_pipeline()
            return

    def register_autonomous(self):
        name = self.name_edit.text().strip()
        user = self.user_edit.text().strip()
        if not name or not user:
            QMessageBox.warning(self, "Missing", "Name and Username required.")
            return
        QMessageBox.information(
            self,
            "Registration",
            "Local agent registration is active.\n"
            "Earning sources are discovered through Fiverr, social platforms, and content channels.",
        )
        self.status_label.setText("Agent status: Registered ✓")

    def test_api_connection(self):
        msgs = []
        # OpenAI
        openai_main, openai_chat = self._role_enabled(getattr(self, "openai_role", None))
        if openai_main or openai_chat:
            key = self.openai_key_edit.text().strip()
            if key:
                try:
                    if OPENAI_AVAILABLE:
                        client = openai.OpenAI(api_key=key)
                        client.chat.completions.create(
                            model=self.openai_model_combo.currentText().strip(),
                            messages=[{"role": "user", "content": "test"}],
                            max_tokens=5,
                        )
                        msgs.append("OpenAI: OK")
                    else:
                        msgs.append("OpenAI: package missing")
                except Exception as e:
                    msgs.append(f"OpenAI Error: {e}")
            else:
                msgs.append("OpenAI: no key set")
        # Anthropic
        anth_main, anth_chat = self._role_enabled(getattr(self, "anthropic_role", None))
        if anth_main or anth_chat:
            key = self.anthropic_key_edit.text().strip()
            if key:
                try:
                    if ANTHROPIC_AVAILABLE:
                        client = Anthropic(api_key=key)
                        client.messages.create(
                            model=self.anthropic_model_combo.currentText().strip(),
                            max_tokens=5,
                            messages=[{"role": "user", "content": "test"}],
                        )
                        msgs.append("Anthropic: OK")
                    else:
                        msgs.append("Anthropic: package missing")
                except Exception as e:
                    msgs.append(f"Anthropic Error: {e}")
            else:
                msgs.append("Anthropic: no key set")
        # Ollama
        ollama_main, ollama_chat = self._role_enabled(getattr(self, "ollama_role", None))
        if ollama_main or ollama_chat:
            try:
                model = self.ollama_model_combo.currentText().strip()
                ollama.chat(
                    model=model,
                    messages=[{"role": "user", "content": "test"}],
                )
                msgs.append(f"Ollama: OK ({model})")
            except Exception as e:
                msgs.append(f"Ollama Error: {e}")
        QMessageBox.information(self, "Connection Test", "\n".join(msgs))

    # ── v2.0.32: cloud-provider model discovery (Fetch button) ──────────────
    @staticmethod
    def _role_enabled(role_combo) -> tuple[bool, bool]:
        """Map a Role combo ('Both'/'Main only'/'Chat only'/'Disabled') to
        (main_enabled, chat_enabled)."""
        if role_combo is None:
            return (True, True)
        txt = role_combo.currentText().strip()
        if txt == "Disabled":
            return (False, False)
        if txt == "Main only":
            return (True, False)
        if txt == "Chat only":
            return (False, True)
        return (True, True)  # Both

    def _fetch_provider_models(self, provider: str, combos, key_edit, base_edit):
        """Fetch a cloud provider's models (w/ pricing) into the model combos.

        `combos` is a list: [main_combo, chat_combo]. Runs off the GUI thread so a
        slow/blocked network call never freezes the Settings tab. Falls back
        gracefully (status message) when there's no key, the provider is offline,
        or there's no models API.
        """
        if isinstance(combos, list):
            target_combos = combos
        else:
            target_combos = [combos]
        api_key = (key_edit.text().strip() if key_edit else "") or \
            os.getenv(f"{provider}_API_KEY", "")
        base_url = (base_edit.text().strip() if base_edit else "") or \
            os.getenv(f"{provider}_BASE_URL", "")
        if not api_key and provider != "ANTHROPIC":
            # Anthropic uses a curated list (no key needed).
            for c in target_combos:
                if c and hasattr(c, "setToolTip"):
                    c.setToolTip("Enter an API key, then click Fetch.")
            self.log_signal.emit(f"[Models] {provider}: no API key set")
            return
        for c in target_combos:
            c.setEnabled(False)
            if hasattr(c, "setToolTip"):
                c.setToolTip(f"Fetching {provider} models…")
        # IMPORTANT: keep a reference so the QThread isn't garbage-collected
        # while still running (deleting a live QThread crashes the app).
        worker = ModelFetchWorker(provider, api_key, base_url)
        worker.finished.connect(
            lambda models, p=provider, cs=target_combos: self._on_models_fetched(p, cs, models))
        # Drop the reference once it has finished to avoid leaking threads.
        worker.finished.connect(lambda *a, w=worker: self._drop_fetch_worker(w))
        self._model_fetch_worker = worker
        worker.start()

    def _drop_fetch_worker(self, worker):
        if getattr(self, "_model_fetch_worker", None) is worker:
            self._model_fetch_worker = None

    def _on_models_fetched(self, provider: str, combos, models):
        for combo in combos:
            combo.setEnabled(True)
        if not models:
            for combo in combos:
                combo.setToolTip(
                    f"No models returned for {provider} (offline, bad key, or no "
                    f"models API). You can still type a model name.")
            self.log_signal.emit(f"[Models] {provider}: no models (offline/empty)")
            return
        for combo in combos:
            prev = combo.currentText().strip()
            combo.clear()
            for m in models:
                combo.addItem(m.combo_text, m.id)
                combo.setItemData(combo.count() - 1, m.tooltip, Qt.ToolTipRole)
            if prev:
                idx = combo.findText(prev, Qt.MatchStartsWith)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setToolTip(
                f"{provider}: {len(models)} models. Showing id — price (per 1M tokens).")
        self.log_signal.emit(f"[Models] {provider}: loaded {len(models)} models")

    def _refresh_model_info(self, live=False):
        """v2.0.34ab (F6): populate the Model Info panel for the selected main + chat models.

        Uses `ollama show <model>` (live=True) so params/context are populated from
        the real model metadata when Ollama is running (H65 fix). The automatic
        Settings-tab refresh passes live=False so opening Settings never spawns
        an Ollama CLI probe; the explicit Refresh button still uses live metadata.
        Falls back to static hints if Ollama is offline. Never raises.
        """
        try:
            from provider_models import _price_for, get_arch_info
            def fmt(label, model):
                if not model:
                    return f"{label}: <i>(none selected)</i>"
                ai = get_arch_info(model, live=live)
                inn, out = _price_for(model)
                price = ("FREE" if (inn is None and out is None)
                         else f"${inn or 0:.2f} in / ${out or 0:.2f} out per 1M")
                typ = "MoE" if ai["moe"] else "dense"
                ex = f" · {ai['experts']} experts/{ai['active_experts']} active" if ai["moe"] and ai["experts"] else ""
                params = f"{ai['params_billion']:.1f}B" if ai.get("params_billion") else "?"
                ctx = f"{ai['context']:,}" if ai.get("context") else "?"
                return (f"<b>{label}:</b> {model}<br>"
                        f"&nbsp;&nbsp;type: {typ}{ex}<br>"
                        f"&nbsp;&nbsp;params: {params} · context: {ctx} tokens<br>"
                        f"&nbsp;&nbsp;price: {price}")
            main_model = self.ollama_model_combo.currentText().strip()
            chat_model = self.ollama_chat_model_combo.currentText().strip()
            lines = [fmt("Main", main_model), fmt("Chat", chat_model)]
            self.model_info_browser.setHtml("<br>".join(lines))
        except Exception as exc:  # never break the settings UI
            self.model_info_browser.setHtml(f"<i>Model info unavailable: {exc}</i>")

    def _fetch_ollama_models(self) -> list[str]:
        """Best-effort fetch of locally-installed Ollama models from the running
        server. Returns [] on any failure (server down, no network). Never raises.
        Used both for the silent startup population (Settings ease-of-switching) and
        for the manual Refresh button.

        NOTE: This is a blocking network call. Call from a QThread, not the GUI thread.
        """
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/tags",
                headers={"User-Agent": "MrBot1000"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def refresh_ollama_models(self):
        """Refresh Ollama models in a background thread to avoid GUI freeze."""
        self.refresh_ollama_btn.setEnabled(False)
        self.refresh_ollama_btn.setText("Refreshing...")
        QApplication.processEvents()

        # Run the blocking network call in a background thread
        class _OllamaRefreshThread(QThread):
            finished = Signal(list)
            def __init__(self, fetch_fn):
                super().__init__()
                self._fetch_fn = fetch_fn
            def run(self):
                models = self._fetch_fn()
                self.finished.emit(models)

        self._ollama_refresh_thread = _OllamaRefreshThread(self._fetch_ollama_models)
        self._ollama_refresh_thread.finished.connect(self._on_ollama_refreshed)
        self._ollama_refresh_thread.start()

    def _on_ollama_refreshed(self, models):
        """Handle Ollama model refresh completion (GUI thread)."""
        main_current = self.ollama_model_combo.currentText()
        chat_current = self.ollama_chat_model_combo.currentText()
        self.ollama_model_combo.clear()
        self.ollama_chat_model_combo.clear()
        if models:
            self.ollama_model_combo.addItems(models)
            self.ollama_chat_model_combo.addItems(models)
            self.ollama_model_combo.setCurrentText(
                main_current if main_current in models else models[0])
            self.ollama_chat_model_combo.setCurrentText(
                chat_current if chat_current in models else models[0])
            QMessageBox.information(self, "Ollama",
                                    f"Loaded {len(models)} model(s).")
        else:
            self.ollama_model_combo.addItem(main_current or "llama3.2")
            self.ollama_chat_model_combo.addItem(chat_current or "llama3.2")
            QMessageBox.warning(self, "Ollama",
                                "No models found on local Ollama server.")

        self.refresh_ollama_btn.setEnabled(True)
        self.refresh_ollama_btn.setText("Refresh")

    def populate_ollama_model_combos(self):
        """v2.0.34al: silently populate the Settings model dropdowns from the
        locally-found Ollama models (no dialog) so the operator can switch models
        with a click. Pre-selects the currently-active model; if none are found,
        leaves the existing (env-defaulted) selection untouched.

        v2.1 fix: runs the HTTP fetch on a background thread so the Settings
        tab never freezes when Ollama is down (the 5s urlopen timeout was
        blocking the GUI thread).
        """
        import threading
        self._ollama_fetch_done = False

        def _fetch_in_thread():
            models = self._fetch_ollama_models()
            self._ollama_fetch_result = models
            self._ollama_fetch_done = True

        t = threading.Thread(target=_fetch_in_thread, daemon=True)
        t.start()

        def _check_result():
            if not getattr(self, '_ollama_fetch_done', False):
                # Still fetching — check again in 100ms
                QTimer.singleShot(100, _check_result)
                return
            models = getattr(self, '_ollama_fetch_result', [])
            if not models:
                return
            active_main = getattr(self.worker, "_ollama_model_override", None) \
                or os.getenv("OLLAMA_MODEL", "").strip() or "llama3.2"
            active_chat = getattr(self.worker, "_chat_ollama_model_override", None) \
                or os.getenv("OLLAMA_CHAT_MODEL", "").strip()
            cur_main = self.ollama_model_combo.currentText()
            cur_chat = self.ollama_chat_model_combo.currentText()
            self.ollama_model_combo.clear()
            self.ollama_chat_model_combo.clear()
            self.ollama_model_combo.addItems(models)
            self.ollama_chat_model_combo.addItems(models)
            self.ollama_model_combo.setCurrentText(
                cur_main if cur_main in models else (active_main if active_main in models else models[0]))
            self.ollama_chat_model_combo.setCurrentText(
                cur_chat if cur_chat in models else (active_chat if active_chat in models else models[0]))

        # Start polling for result
        QTimer.singleShot(100, _check_result)

    def save_settings(self):
        # v2.0.25: snapshot provider-relevant settings BEFORE applying, so we can
        # detect whether a restart-requiring change was made.
        prev_snapshot = self._settings_snapshot()
        # v2.0.33: per-provider main/chat role control. For every provider we now
        # write DISABLE_<X> (legacy, = role "Disabled"), <X>_MAIN_ENABLED,
        # <X>_CHAT_ENABLED, and <X>_CHAT_MODEL, derived from the Role combo.
        values = {}

        def _safe_widget_text(name, env_key=""):
            """Read a lazily-built widget without trusting its C++ lifetime."""
            widget = getattr(self, name, None)
            try:
                if widget is not None:
                    return widget.currentText().strip() if hasattr(widget, "currentText") else widget.text().strip()
            except RuntimeError:
                pass
            return os.getenv(env_key, "") if env_key else ""

        def _safe_widget_checked(name, env_key=""):
            widget = getattr(self, name, None)
            try:
                if widget is not None:
                    return bool(widget.isChecked())
            except RuntimeError:
                pass
            return os.getenv(env_key, "false").lower() == "true"

        def _save_provider(prefix, role_combo, model_combo, chat_combo, key="", base="",
                          model="", hide_cb=None):
            try:
                main_on, chat_on = self._role_enabled(role_combo)
            except RuntimeError:
                main_on = os.getenv(f"{prefix}_MAIN_ENABLED", "true").lower() == "true"
                chat_on = os.getenv(f"{prefix}_CHAT_ENABLED", "true").lower() == "true"
            disabled = not (main_on or chat_on)
            try:
                if model_combo is not None:
                    values[f"{prefix}_MODEL"] = model_combo.currentText().strip()
            except RuntimeError:
                values[f"{prefix}_MODEL"] = os.getenv(f"{prefix}_MODEL", model)
            try:
                if chat_combo is not None:
                    values[f"{prefix}_CHAT_MODEL"] = chat_combo.currentText().strip()
            except RuntimeError:
                values[f"{prefix}_CHAT_MODEL"] = os.getenv(f"{prefix}_CHAT_MODEL", "")
            values[f"DISABLE_{prefix}"] = str(disabled)
            values[f"{prefix}_MAIN_ENABLED"] = str(main_on)
            values[f"{prefix}_CHAT_ENABLED"] = str(chat_on)
            if hide_cb is not None:
                try:
                    values[f"{prefix}_HIDE"] = str(bool(hide_cb.isChecked()))
                except RuntimeError:
                    values[f"{prefix}_HIDE"] = os.getenv(f"{prefix}_HIDE", "false")
            if key != "":
                values[f"{prefix}_API_KEY"] = key
            if base != "":
                values[f"{prefix}_BASE_URL"] = base.strip()

        _save_provider("OPENAI", getattr(self, "openai_role", None), getattr(self, "openai_model_combo", None),
                   getattr(self, "openai_chat_combo", None), _safe_widget_text("openai_key_edit", "OPENAI_API_KEY"), hide_cb=getattr(self, "openai_hide", None))
        _save_provider("ANTHROPIC", getattr(self, "anthropic_role", None), getattr(self, "anthropic_model_combo", None),
                   getattr(self, "anthropic_chat_combo", None), _safe_widget_text("anthropic_key_edit", "ANTHROPIC_API_KEY"), hide_cb=getattr(self, "anthropic_hide", None))
        _save_provider("OLLAMA", self.ollama_role, self.ollama_model_combo,
                       self.ollama_chat_model_combo, hide_cb=self.ollama_hide)
        # The Ollama adapter's `model_env` (from settings.json) must match the env
        # vars the runtime actually reads: OLLAMA_MAIN_MODEL for main, OLLAMA_CHAT_MODEL
        # for chat. Previously only OLLAMA_MODEL was written, leaving the adapter's
        # model_env stale and the choice ambiguous when .env had MAIN/CHAT vars empty.
        values["OLLAMA_MAIN_MODEL"] = self.ollama_model_combo.currentText().strip()
        values["OLLAMA_CHAT_MODEL"] = self.ollama_chat_model_combo.currentText().strip()
        # v2.0.34aa (F5): per-role GPU offload layers.
        # Defensive: the spinners live on the lazily-built "Model & GPU" tab, which
        # may not be constructed yet when Settings is saved. Read them only if they
        # exist, otherwise fall back to the current env value (so we never clobber
        # an explicit setting and never raise AttributeError).
        chat_gpu_spin = getattr(self, "ollama_chat_gpu_spin", None)
        main_gpu_spin = getattr(self, "ollama_main_gpu_spin", None)
        values["OLLAMA_CHAT_GPU"] = str(
            chat_gpu_spin.value() if chat_gpu_spin is not None
            else os.getenv("OLLAMA_CHAT_GPU", "-1"))
        values["OLLAMA_MAIN_GPU"] = str(
            main_gpu_spin.value() if main_gpu_spin is not None
            else os.getenv("OLLAMA_MAIN_GPU", "-1"))
        _save_provider("OPENROUTER", getattr(self, "openrouter_role", None), getattr(self, "openrouter_model", None),
                   getattr(self, "openrouter_chat", None), _safe_widget_text("openrouter_key", "OPENROUTER_API_KEY"),
                   _safe_widget_text("openrouter_base", "OPENROUTER_BASE_URL"), hide_cb=getattr(self, "openrouter_hide", None))
        _save_provider("GEMINI", getattr(self, "gemini_role", None), getattr(self, "gemini_model", None),
                   getattr(self, "gemini_chat", None), _safe_widget_text("gemini_key", "GEMINI_API_KEY"),
                   _safe_widget_text("gemini_base", "GEMINI_BASE_URL"), hide_cb=getattr(self, "gemini_hide", None))
        _save_provider("GROQ", getattr(self, "groq_role", None), getattr(self, "groq_model", None), getattr(self, "groq_chat", None),
                   _safe_widget_text("groq_key", "GROQ_API_KEY"), _safe_widget_text("groq_base", "GROQ_BASE_URL"), hide_cb=getattr(self, "groq_hide", None))
        _save_provider("DEEPSEEK", getattr(self, "deepseek_role", None), getattr(self, "deepseek_model", None),
                   getattr(self, "deepseek_chat", None), _safe_widget_text("deepseek_key", "DEEPSEEK_API_KEY"),
                   _safe_widget_text("deepseek_base", "DEEPSEEK_BASE_URL"), hide_cb=getattr(self, "deepseek_hide", None))
        _save_provider("MISTRAL", getattr(self, "mistral_role", None), getattr(self, "mistral_model", None),
                   getattr(self, "mistral_chat", None), _safe_widget_text("mistral_key", "MISTRAL_API_KEY"),
                   _safe_widget_text("mistral_base", "MISTRAL_BASE_URL"), hide_cb=getattr(self, "mistral_hide", None))
        _save_provider("TOGETHER", getattr(self, "together_role", None), getattr(self, "together_model", None),
                   getattr(self, "together_chat", None), _safe_widget_text("together_key", "TOGETHER_API_KEY"),
                   _safe_widget_text("together_base", "TOGETHER_BASE_URL"), hide_cb=getattr(self, "together_hide", None))
        # v2.0.34ap (H70): NVIDIA NIM cloud provider.
        _save_provider("NVIDIA", getattr(self, "nvidia_role", None), getattr(self, "nvidia_model", None),
                   getattr(self, "nvidia_chat", None), _safe_widget_text("nvidia_key", "NVIDIA_API_KEY"),
                   _safe_widget_text("nvidia_base", "NVIDIA_BASE_URL"), hide_cb=getattr(self, "nvidia_hide", None))
        _save_provider("VLLM", getattr(self, "vllm_role", None), getattr(self, "vllm_model", None), getattr(self, "vllm_chat", None),
                   _safe_widget_text("vllm_key", "VLLM_API_KEY"), _safe_widget_text("vllm_base", "VLLM_BASE_URL"), hide_cb=getattr(self, "vllm_hide", None))
        _save_provider("LM_STUDIO", getattr(self, "lmstudio_role", None), getattr(self, "lmstudio_model", None),
                   getattr(self, "lmstudio_chat", None), _safe_widget_text("lmstudio_key", "LM_STUDIO_API_KEY"),
                   _safe_widget_text("lmstudio_base", "LM_STUDIO_BASE_URL"), hide_cb=getattr(self, "lmstudio_hide", None))
        _save_provider("KOBOLDCPP", getattr(self, "koboldcpp_role", None), getattr(self, "koboldcpp_model", None),
                   getattr(self, "koboldcpp_chat", None), _safe_widget_text("koboldcpp_key", "KOBOLDCPP_API_KEY"),
                   _safe_widget_text("koboldcpp_base", "KOBOLDCPP_BASE_URL"), hide_cb=getattr(self, "koboldcpp_hide", None))

        # v2.0.26: persist effect toggles (Quality/Performance + individual).
        try:
            values["MRBOT_FX_ANTIALIASING"] = str(self.fx_antialias.isChecked())
            values["MRBOT_FX_SOFT_SHADOWS"] = str(self.fx_shadows.isChecked())
            values["MRBOT_FX_HOVER_GLOW"] = str(self.fx_glow.isChecked())
            values["MRBOT_FX_TRANSITIONS"] = str(self.fx_trans.isChecked())
            values["MRBOT_FX_ANIMATIONS"] = str(self.fx_anim.isChecked())
            values["MRBOT_FX_QUALITY"] = self.fx_quality.currentText()
            # v2.0.34ap (H67): persist the new render-quality + density toggles.
            values["MRBOT_FX_RENDER_QUALITY"] = self.fx_render_quality.currentText()
            values["MRBOT_FX_COMPACT_DENSITY"] = str(self.fx_compact.isChecked())
            values["MRBOT_FX_ROUNDED_CORNERS"] = str(self.fx_rounded.isChecked())
            values["MRBOT_FX_BUTTON_STYLE"] = self.fx_button_style.currentText()
        except Exception as e:
            self.log_signal.emit(f"[FX] save failed: {e}")
        values["PIPELINE_ENABLED"] = str(self.pipeline_enabled_check.isChecked())
        values["PIPELINE_ALLOW_WRITE"] = str(self.pipeline_allow_write_check.isChecked())
        values["PIPELINE_ALLOW_SELF_IMPROVE"] = str(self.pipeline_allow_selfimprove_check.isChecked())
        values["MRBOT_THEME"] = getattr(self, "theme_combo", None).currentText() \
            if getattr(self, "theme_combo", None) is not None \
            else os.getenv("MRBOT_THEME", "Dark")

        # v2.1 llama.cpp dual-brain customization — persist from the (possibly
        # lazily-built) Providers & GPU tab so Settings Save captures them too.
        # Defensive getattr: never crash when the tab isn't constructed yet.
        try:
            dbtab = getattr(self, "providers_gpu_tab", None)
            if dbtab is not None:
                def _db(key, small=True):
                    attr = ("sb_" if small else "bb_")
                    mapping = {
                        "CONTEXT": "ctx_spin", "GPU_LAYERS": "gpu_layers_spin",
                        "SPLIT_MODE": "split_combo", "THREADS": "threads_spin",
                        "BATCH": "batch_spin", "KV_CACHE": "kv_combo",
                    }
                    w = getattr(dbtab, attr + mapping[key], None)
                    if w is None:
                        return None
                    if hasattr(w, "value"):
                        return str(w.value())
                    return w.currentText()
                pairs = [("SMALL_BRAIN", True), ("BIG_BRAIN", False)]
                for prefix, small in pairs:
                    for key in ("CONTEXT", "GPU_LAYERS", "SPLIT_MODE", "THREADS", "BATCH", "KV_CACHE"):
                        v = _db(key, small)
                        if v is not None:
                            values[f"{prefix}_{key}"] = v
        except Exception as e:
            self.log_signal.emit(f"[llama.cpp] dual-brain settings read failed: {e}")

        # Settings owns llama.cpp role enablement only while llama.cpp is the
        # selected backend. Do not let Save All Settings silently overwrite an
        # Ollama/vLLM/LM Studio route selected in Provider Configuration.
        if os.getenv("BIG_BRAIN_PROVIDER", "llamacpp").lower() == "llamacpp":
            values["BIG_BRAIN_PROVIDER"] = "llamacpp"
            values["BIG_BRAIN_ENABLED"] = str(
                getattr(self, "llamacpp_big_enabled", None) is not None
                and self.llamacpp_big_enabled.isChecked())
        if os.getenv("SMALL_BRAIN_PROVIDER", "llamacpp").lower() == "llamacpp":
            values["SMALL_BRAIN_PROVIDER"] = "llamacpp"
            values["SMALL_BRAIN_ENABLED"] = str(
                getattr(self, "llamacpp_small_enabled", None) is not None
                and self.llamacpp_small_enabled.isChecked())

        # v2.0.34aj: single lock-resilient atomic write (replaces ~40 set_key calls
        # that each spawned a .tmp_* temp vulnerable to WinError 32/5 lock races).
        set_env_values(values)

        # Reload env so newly saved keys are visible to os.getenv() in this process
        try:
            load_dotenv(override=True)
        except Exception:
            pass

        # ── Live model switch (no restart required) ──────────────────────────
        new_chat = self.ollama_chat_model_combo.currentText().strip()
        new_main = self.ollama_model_combo.currentText().strip()
        old_chat = getattr(self.worker, "_chat_ollama_model_override", None) or ""
        old_main = getattr(self.worker, "_ollama_model_override", None) or ""
        # registry cache is invalidated so the new <PREFIX>_MODEL/_CHAT_MODEL from
        # .env takes effect on the next llm() call (no restart needed).
        if OLLAMA_AVAILABLE and ollama:
            # H54 (v2.0.34al): unload the previously-active model(s) from VRAM so the
            # new model loads cleanly. Only attempt this when the Ollama server is
            # actually reachable — a dead/unreachable server must NOT block the Save.
            # (The blocking ollama.chat call can pin the GIL and starve the GUI, so we
            # guard with a 1s raw-socket reachability check; the unload itself is a
            # best-effort fire-and-forget daemon thread.)
            def _ollama_reachable():
                import socket
                try:
                    with socket.create_connection(("127.0.0.1", 11434), timeout=1):
                        return True
                except Exception:
                    return False
            if _ollama_reachable():
                import threading
                def _unload(old):
                    try:
                        ollama.chat(model=old, messages=[], keep_alive=0)
                    except Exception:
                        pass
                for old in (old_chat, old_main):
                    if old:
                        threading.Thread(target=_unload, args=(old,), daemon=True).start()
        if new_chat and new_chat != old_chat:
            self.worker._chat_ollama_model_override = new_chat
            if hasattr(self.manager, "_chat_ollama_model_override"):
                self.manager._chat_ollama_model_override = new_chat
            if hasattr(self.summarizer, "_chat_ollama_model_override"):
                self.summarizer._chat_ollama_model_override = new_chat
            self.log_signal.emit(f"[Ollama] chat model now live: {new_chat}")
        if new_main and new_main != old_main:
            self.worker._ollama_model_override = new_main
            if hasattr(self.manager, "_ollama_model_override"):
                self.manager._ollama_model_override = new_main
            if hasattr(self.summarizer, "_ollama_model_override"):
                self.summarizer._ollama_model_override = new_main
            self.log_signal.emit(f"[Ollama] main model now live: {new_main}")
        # Make cloud/local provider model changes live without a restart: rebuild
        # the cached provider registry from the just-written .env on next llm() call.
        for obj in (self.worker, self.manager, self.summarizer):
            if hasattr(obj, "invalidate_provider_registry"):
                obj.invalidate_provider_registry()
        self.log_signal.emit("[Models] provider registry refreshed — changes apply on next call (no restart)")

        # Update live objects
        self.worker.max_file_size = self.max_file_spin.value() * 1024 * 1024
        self.manager.HEARTBEAT_INTERVAL = self.polling_spin.value()
        self.manager._research_cache_ttl = self.research_cache_ttl_spin.value()
        # v2.0.36k: idle-directed heartbeat cooldown (LLM only when truly idle)
        try:
            self.manager._idle_heartbeat_cooldown = int(self.idle_cooldown_spin.value())
        except Exception:
            pass
        # v2.0.21 P3#6: apply Max Tokens knob live (no restart).
        try:
            self.worker._max_tokens = int(self.max_tokens_spin.value())
        except Exception:
            pass
        if hasattr(self, "agents_tab"):
            self.agents_tab.heartbeat_label.setText(
                f"Heartbeat every {self.polling_spin.value()}s")
        self.log_signal.emit("Settings saved")

        # v2.0.25: persist the provider list to settings.json (provider-agnostic,
        # user-driven order). settings.json stores ONLY the enable-state + the
        # api_key_env NAME + base_url + model — never the secret. The actual keys
        # live in .env (set_env_values above).
        try:
            self._save_provider_list()
        except Exception as e:
            self.log_signal.emit(f"[Settings] provider list save failed: {e}")

        # v2.0.34am: restart is only needed for non-model provider changes (new key,
        # base_url changed, enable/disable toggled). Model switches are live (H55:
        # env written + runtime override set + provider registry invalidated), so they
        # no longer trigger the restart prompt.
        if self._settings_require_restart(prev_snapshot):
            self._prompt_restart()

    # ── v2.0.25 provider list persistence ───────────────────────────────────
    def _save_provider_list(self):
        """Write providers.json-style provider config (no secrets)."""
        import json
        providers = []
        def add(name, env_prefix, default_model=""):
            role_combo = getattr(self, f"{env_prefix.lower()}_role", None)
            main_on, chat_on = self._role_enabled(role_combo)
            providers.append({
                "name": name,
                "enabled": main_on or chat_on,
                "main_enabled": main_on,
                "chat_enabled": chat_on,
                "api_key_env": f"{env_prefix}_API_KEY",
                "base_url_env": f"{env_prefix}_BASE_URL",
                "model_env": f"{env_prefix}_MODEL",
                "default_model": default_model,
            })
        add("ollama", "OLLAMA", os.getenv("OLLAMA_MAIN_MODEL", "llama3.2"))
        add("openai", "OPENAI", "gpt-4o-mini")
        add("anthropic", "ANTHROPIC", "claude-3-5-sonnet-20241022")
        add("openrouter", "OPENROUTER", "")
        add("gemini", "GEMINI", "gemini-1.5-pro")
        add("groq", "GROQ", "")
        add("deepseek", "DEEPSEEK", "deepseek-chat")
        add("mistral", "MISTRAL", "")
        add("together", "TOGETHER", "")
        add("vllm", "VLLM", "")
        add("lm-studio", "LM_STUDIO", "")
        add("koboldcpp", "KOBOLDCPP", "")
        # Order: Ollama first by default (user can reorder later via settings).
        settings = {"providers": providers}
        with open("settings.json", "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

    def _settings_snapshot(self) -> dict:
        """Capture provider-relevant env values for restart-diffing."""
        keys = [
            "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_CHAT_MODEL", "DISABLE_OPENAI",
            "OPENAI_MAIN_ENABLED", "OPENAI_CHAT_ENABLED",
            "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_CHAT_MODEL", "DISABLE_ANTHROPIC",
            "ANTHROPIC_MAIN_ENABLED", "ANTHROPIC_CHAT_ENABLED",
            "OLLAMA_MAIN_MODEL", "OLLAMA_CHAT_MODEL", "OLLAMA_MODEL", "DISABLE_OLLAMA",
            "OLLAMA_MAIN_ENABLED", "OLLAMA_CHAT_ENABLED",
            "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_CHAT_MODEL",
            "DISABLE_OPENROUTER", "OPENROUTER_MAIN_ENABLED", "OPENROUTER_CHAT_ENABLED",
            "GEMINI_API_KEY", "GEMINI_BASE_URL", "GEMINI_MODEL", "GEMINI_CHAT_MODEL", "DISABLE_GEMINI",
            "GEMINI_MAIN_ENABLED", "GEMINI_CHAT_ENABLED",
            "GROQ_API_KEY", "GROQ_BASE_URL", "GROQ_MODEL", "GROQ_CHAT_MODEL", "DISABLE_GROQ",
            "GROQ_MAIN_ENABLED", "GROQ_CHAT_ENABLED",
            "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_CHAT_MODEL", "DISABLE_DEEPSEEK",
            "DEEPSEEK_MAIN_ENABLED", "DEEPSEEK_CHAT_ENABLED",
            "MISTRAL_API_KEY", "MISTRAL_BASE_URL", "MISTRAL_MODEL", "MISTRAL_CHAT_MODEL", "DISABLE_MISTRAL",
            "MISTRAL_MAIN_ENABLED", "MISTRAL_CHAT_ENABLED",
            "TOGETHER_API_KEY", "TOGETHER_BASE_URL", "TOGETHER_MODEL", "TOGETHER_CHAT_MODEL", "DISABLE_TOGETHER",
            "TOGETHER_MAIN_ENABLED", "TOGETHER_CHAT_ENABLED",
            "VLLM_BASE_URL", "VLLM_API_KEY", "VLLM_MODEL", "VLLM_CHAT_MODEL", "DISABLE_VLLM",
            "VLLM_MAIN_ENABLED", "VLLM_CHAT_ENABLED",
            "LM_STUDIO_BASE_URL", "LM_STUDIO_API_KEY", "LM_STUDIO_MODEL", "LM_STUDIO_CHAT_MODEL", "DISABLE_LM_STUDIO",
            "LM_STUDIO_MAIN_ENABLED", "LM_STUDIO_CHAT_ENABLED",
            "KOBOLDCPP_BASE_URL", "KOBOLDCPP_API_KEY", "KOBOLDCPP_MODEL", "KOBOLDCPP_CHAT_MODEL", "DISABLE_KOBOLDCPP",
            "KOBOLDCPP_MAIN_ENABLED", "KOBOLDCPP_CHAT_ENABLED",
        ]
        return {k: os.getenv(k, "") for k in keys}

    def _settings_require_restart(self, prev: dict) -> bool:
        cur = self._settings_snapshot()
        for k in prev:
            # Model-name changes are live (Settings writes the env value AND sets the
            # runtime override / invalidates the provider registry — see H55), so they
            # must NOT trigger a restart prompt. Only key/base-url/enable-state changes
            # still require a restart.
            if k.endswith("_MODEL"):
                continue
            if prev[k] != cur.get(k, ""):
                return True
        return False

    def _prompt_restart(self):
        """Warn that a restart is required and offer to restart now."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Restart Required")
        box.setText(
            "A provider or API setting changed that requires a restart to take "
            "effect (new key, base URL, or enable/disable state).\n\n"
            "Restart MrBot1000 now to apply the change?")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        box.button(QMessageBox.Yes).setText("Restart Now")
        box.button(QMessageBox.No).setText("Later")
        if box.exec() == QMessageBox.Yes:
            self.restart_app()

    def restart_app(self):
        """Cleanly relaunch the application in-place."""
        try:
            self.log_signal.emit("[Restart] restarting application...")
        except Exception:
            pass
        # v2.1: relaunch as a detached, no-console process (no python window
        # flash on restart), then quit this instance. os.execv re-launched
        # python.exe under a visible console, so a window popped and vanished.
        import subprocess as _sp
        import sys
        _flags = (getattr(_sp, "CREATE_NO_WINDOW", 0)
                  | getattr(_sp, "DETACHED_PROCESS", 0))
        try:
            _sp.Popen([sys.executable] + sys.argv, cwd=ROOT_FOLDER,
                      close_fds=True, creationflags=_flags)
        except Exception:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        app = QApplication.instance()
        if app is not None:
            app.quit()
        raise SystemExit(0)


    def _on_pipeline_validated(self, action, result):
        status = "PASS" if result.passed else "FAIL"
        self.log_signal.emit(
            f"[Pipeline] {status} score={result.score:.2f} "
            f"| {action.proposer} → {action.action_type} "
            f"| {result.summary}")
        if hasattr(self, "thought_panel"):
            self.thought_panel.route(
                "System",
                f"Pipeline {status}: {action.description} | {result.summary}")

    def _on_pipeline_executed(self, action, result):
        status = "✓" if result.success else "✗"
        self.log_signal.emit(
            f"[Pipeline] {status} EXECUTED {action.action_type} "
            f"by {action.proposer}: {result.message}")

    def _on_pipeline_rejected(self, action, reason):
        self.log_signal.emit(
            f"[Pipeline] REJECTED {action.action_type} "
            f"by {action.proposer}: {reason}")
        if hasattr(self, "thought_panel"):
            self.thought_panel.route(
                "System",
                f"⚠ Rejected: {action.description} | {reason}")

    def _validate_clipboard_code(self):
        """Quick-validate whatever code is in the clipboard."""
        try:
            code = QApplication.clipboard().text()
            if not code.strip():
                self.pipeline_result_label.setText("Clipboard is empty.")
                return
            ok, summary = self.pipeline.quick_check(code)
            icon = "✓" if ok else "✗"
            color = "#22c55e" if ok else "#ef4444"
            self.pipeline_result_label.setText(f"{icon} {summary}")
            self.pipeline_result_label.setStyleSheet(f"font-size:10px;color:{color};")
        except Exception as e:
            self.pipeline_result_label.setText(f"Error: {e}")





    def apply_theme(self, theme_name: str, fx_override=None):
        self._last_theme = theme_name
        if theme_name == "Auto":
            is_dark = (QApplication.instance()
                       .palette().color(QPalette.Window).lightness() < 128)
            self.apply_theme("Dark" if is_dark else "Light")
            return
        theme = resolve_theme_definition(theme_name)
        # v2.0.27: keep the resolved palette available to widget-level styling
        # (self._t) so static labels/notes follow the active theme (no bleed).
        self._theme = theme
        pal = QPalette()
        for role, key in [
            (QPalette.Window,        "bg"),
            (QPalette.WindowText,    "fg"),
            (QPalette.Base,          "bg"),
            (QPalette.AlternateBase, "bg"),
            (QPalette.Text,          "fg"),
            (QPalette.Button,        "bg"),
            (QPalette.ButtonText,    "fg"),
            (QPalette.Highlight,     "highlight"),
        ]:
            pal.setColor(role, QColor(theme[key]))
        pal.setColor(QPalette.Disabled, QPalette.WindowText,
                     QColor(theme["disabled"]))
        pal.setColor(QPalette.Disabled, QPalette.ButtonText,
                     QColor(theme["disabled"]))
        app = QApplication.instance()
        app.setPalette(pal)
        # v2.0.26: per-window independent backgrounds (explicit tokens, no bleed)
        # + effects engine (antialiasing / soft shadows / hover glow / transitions).
        fx, style_hints_qss, apply_antialiasing = self._build_effect_settings(fx_override)
        apply_antialiasing(app)
        hint_qss = style_hints_qss(fx, theme)
        qss = f"""
            QWidget{{background:{theme['bg']};color:{theme['fg']};}}
            /* Leaf widgets stay transparent so text/checkboxes blend into the
               panel instead of painting a full-row background block. Only
               containers (window, tabs, group boxes, inputs) keep a fill. */
            QLabel,QCheckBox,QRadioButton,QAbstractButton{{
                background:transparent;}}
            /* v2.0.34ap (H68): checkboxes/radios were invisible on the panel
               background (transparent leaf + no indicator styling). Give the
               text the fg color and draw a visible bordered indicator that
               fills with the accent when checked. */
            QCheckBox,QRadioButton{{color:{theme['fg']};spacing:6px;}}
            QCheckBox::indicator,QRadioButton::indicator{{
                width:16px;height:16px;border:1px solid {theme['border']};
                border-radius:3px;background:{theme['surface2']};}}
            QCheckBox::indicator:checked,QRadioButton::indicator:checked{{
                background:{theme['accent']};border:1px solid {theme['accent']};}}
            QCheckBox::indicator:unchecked:hover,QRadioButton::indicator:hover{{
                border:1px solid {theme['accent']};}}
            QMainWindow,QWidget#tab-content{{background:{theme['bg']};}}
            QTabWidget::pane{{border:1px solid {theme['border']};
                background:{theme['panel']};}}
            QTabBar::tab{{background:{theme['panel']};color:{theme['muted']};
                padding:8px;border-top-left-radius:{theme['radius']}px;
                border-top-right-radius:{theme['radius']}px;}}
            QTabBar::tab:selected{{background:{theme['accent']};color:{theme['bg']};}}
            QPushButton{{background:{theme['surface']};color:{theme['fg']};
                border:1px solid {theme['border']};padding:6px;
                border-radius:{theme['radius']}px;}}
            QPushButton:hover{{background:{theme['accent']};color:{theme['bg']};}}
            QPushButton:checked{{background:{theme['highlight']};color:{theme['bg']};}}
            QLineEdit,QPlainTextEdit,QSpinBox,QComboBox,QTextEdit{{
                background:{theme['surface2']};color:{theme['fg']};
                border:1px solid {theme['border']};
                border-radius:{theme['radius']}px;}}
            QGroupBox{{background:{theme['surface']};border:1px solid {theme['border']};
                border-radius:{theme['radius']}px;
                margin-top:10px;padding-top:10px;}}
            /* v2.0.34an: provider sections (one per cloud/local/Ollama provider in
               Settings) get a stronger, clearly-independent outline + accent bar so
               they read as separate boxes, not one blurred list. */
            QGroupBox#prov-section{{background:{theme['surface']};
                border:1px solid {theme['accent']};border-left:4px solid {theme['accent']};
                border-radius:{theme['radius']}px;margin-top:12px;padding-top:12px;}}
            QGroupBox::title{{color:{theme['accent']};subcontrol-origin:margin;
                left:10px;padding:0 4px;}}
            QLabel{{color:{theme['fg']};}}
            QScrollArea{{border:none;background:{theme['panel']};}}
            QTableWidget,QListWidget,QTreeWidget{{background:{theme['surface2']};
                color:{theme['fg']};border:1px solid {theme['border']};
                border-radius:{theme['radius']}px;}}
            QTableWidget::item,QListWidget::item,QTreeWidget::item{{
                background:transparent;padding:2px 4px;}}
            QListWidget::item:selected{{background:{theme['highlight']};
                color:{theme['bg']};}}
            QProgressBar{{background:{theme['surface2']};border:1px solid {theme['border']};
                border-radius:{theme['radius']}px;}}
            {hint_qss}
            {theme['qss_extra']}
        """
        app.setStyleSheet(qss)
        self._restyle_themeable()
        self._apply_shadow_effects(theme, fx)
        # v2.0.27: push the resolved theme to ui.py so chat/HTML colors follow it.
        try:
            import ui
            ui.set_ui_theme(theme)
            # v2.0.34ap (H67): Animations toggle now actually gates ui particle/gear FX.
            ui.set_effects(animations=bool(fx.animations))
        except Exception:
            pass
        self.log_signal.emit(f"Theme: {theme_name}")

    def _t(self, key: str, fallback: str = "#888888") -> str:
        """Resolve a theme color token for widget-level styling (Phase E).

        Lets static labels/notes/buttons follow the active theme instead of a
        hardcoded hex, so changing the theme never leaves bleeding colors.
        """
        return str((getattr(self, "_theme", None) or {}).get(key, fallback))

    def _restyle_themeable(self):
        """Re-apply theme tokens to statically-styled widgets on theme change.

        Widgets that used _t() at creation keep their initial color; this walks
        the registered themeable widgets and re-applies so a live theme switch
        propagates everywhere (no bleed).
        """
        theme = getattr(self, "_theme", None) or {}
        for w, role, extra in getattr(self, "_themeable", []):
            try:
                w.setStyleSheet(f"color:{theme.get(role, '#888888')};{extra}")
            except Exception:
                pass

    def _apply_shadow_effects(self, theme: dict, fx):
        """Apply or clear the soft-shadow effect on container widgets.

        `fx.soft_shadows` drives this; every call re-applies (so toggling the
        checkbox on/off takes visible effect immediately). No-ops gracefully.
        """
        try:
            from PySide6.QtWidgets import QGroupBox, QTabWidget

            from effects import apply_shadow
            containers = []
            cw = self.centralWidget()
            if cw is not None:
                containers.append(cw)
                for child in cw.findChildren(QGroupBox):
                    containers.append(child)
                tw = cw.findChild(QTabWidget)
                if tw is not None:
                    containers.append(tw)
            for w in containers:
                if fx.soft_shadows:
                    apply_shadow(w, theme, fx)
                else:
                    try:
                        w.setGraphicsEffect(None)
                    except Exception:
                        pass
        except Exception:
            pass

    def _open_theme_customizer(self, current_theme: str):
        """Open per-area color pickers for the Custom theme, with live preview.

        Each swatch pick + the radius spinbox applies the theme immediately (the
        app behind repaints AND this dialog's own preview panel recolors), so the
        user sees the change as they go — no separate Save step required.
        """
        try:
            from PySide6.QtWidgets import (
                QColorDialog,
                QDialog,
                QDialogButtonBox,
                QFormLayout,
                QFrame,
                QHBoxLayout,
                QLabel,
                QPushButton,
                QSpinBox,
            )

            from theme_config import resolve_theme_definition, save_custom_theme
            base = resolve_theme_definition("Custom")
            # Every customizable surface / line / text area.
            areas = [
                ("bg",       "Window background"),
                ("panel",    "Panel background (tabs/sections)"),
                ("surface",  "Surface (cards / inputs)"),
                ("surface2", "Surface 2 (nested panels)"),
                ("fg",       "Text color"),
                ("muted",    "Muted text (notes / captions)"),
                ("caption",  "Helper text (brighter than muted)"),
                ("accent",   "Accent (buttons / highlights)"),
                ("highlight", "Highlight (selected / active)"),
                ("border",   "Border / line color"),
                ("shadow",   "Shadow color (rgba)"),
                ("success",  "Success (green)"),
                ("warning",  "Warning (amber)"),
                ("error",    "Error (red)"),
            ]
            vals = dict(base)

            dlg = QDialog(self)
            dlg.setWindowTitle("Customize Theme — pick each area")
            dlg.setMinimumWidth(460)
            form = QFormLayout(dlg)

            # Live preview panel — recolors on every pick so the change is obvious
            # even without looking at the app behind the dialog.
            preview = QFrame()
            preview.setMinimumHeight(34)
            preview.setFrameShape(QFrame.StyledPanel)
            preview_lbl = QLabel("Live preview — this panel follows your picks")
            preview_lbl.setWordWrap(True)
            pprev_lay = QHBoxLayout(preview)
            pprev_lay.addWidget(preview_lbl)
            form.addRow("Preview:", preview)

            swatches = {}

            def _restyle_preview():
                bg = vals.get("bg", "#121212")
                fg = vals.get("fg", "#e0e0e0")
                acc = vals.get("accent", "#4fc3f7")
                preview.setStyleSheet(
                    f"background:{bg};color:{fg};border:1px solid {acc};"
                    f"border-radius:6px;")
                preview_lbl.setStyleSheet(f"color:{fg};font-weight:bold;")

            for key, label in areas:
                cur = vals.get(key, "#121212")
                btn = QPushButton()
                btn.setMinimumWidth(120)
                btn.setFixedHeight(26)
                btn.setText(cur)
                btn.setStyleSheet(
                    f"background:{cur};color:{_contrast(cur)};"
                    f"border:1px solid #555;border-radius:4px;padding:2px 6px;")
                btn.setToolTip(f"Click to pick {label}")

                def _mk(*_args, key=key, btn=btn, vals=vals, dlg=dlg):
                    col = QColorDialog.getColor(QColor(vals.get(key, "#121212")),
                                                dlg, f"Pick {key}")
                    if col.isValid():
                        vals[key] = col.name()
                        btn.setText(col.name())
                        btn.setStyleSheet(
                            f"background:{col.name()};color:{_contrast(col.name())};"
                            f"border:1px solid #555;border-radius:4px;padding:2px 6px;")
                        # Live preview: repaint this dialog's preview AND the app.
                        _restyle_preview()
                        self._apply_custom_live(vals)
                btn.clicked.connect(_mk)
                swatches[key] = btn
                form.addRow(QLabel(label), btn)

            _restyle_preview()

            # Corner radius control (smoothness of surfaces) — live preview too.
            rad = QSpinBox()
            rad.setRange(0, 24)
            rad.setValue(int(str(vals.get("radius", "6")).strip() or 6))
            rad.valueChanged.connect(
                lambda v, vals=vals: self._apply_custom_live(
                    {**vals, "radius": str(v)}))
            form.addRow("Corner radius (px):", rad)

            btns = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            form.addRow(btns)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)

            if dlg.exec() == QDialog.Accepted:
                vals["radius"] = str(rad.value())
                save_custom_theme(vals)
                self.apply_theme("Custom")
        except Exception as e:
            self.log_signal.emit(f"[Theme] customizer error: {e}")

    def _apply_custom_live(self, vals: dict):
        """Persist + apply a custom-theme preview immediately (real-time).

        Called on every swatch pick / radius change so the user sees the change
        live, and the values are already saved to .env (no separate Save step
        needed, though the dialog's OK re-saves the full set).
        """
        try:
            from theme_config import save_custom_theme
            save_custom_theme(vals)
            self.apply_theme("Custom")
        except Exception as e:
            self.log_signal.emit(f"[Theme] live preview error: {e}")

    def _apply_effects_now(self):
        """Re-apply theme using the LIVE effect-toggle state (not the persisted
        MRBOT_FX_* env), so unchecking/rechecking takes effect immediately.

        Also mirrors the live state into the process env so a subsequent Save or
        restart sees the same setting (the user-driven choice shouldn't silently
        revert to the on-disk value).
        """
        try:
            from effects import EffectSettings
            fx = EffectSettings(
                antialiasing=self.fx_antialias.isChecked(),
                soft_shadows=self.fx_shadows.isChecked(),
                hover_glow=self.fx_glow.isChecked(),
                transitions=self.fx_trans.isChecked(),
                animations=self.fx_anim.isChecked(),
                quality_mode=self.fx_quality.currentText(),
                # v2.0.34ap (H67): new render-quality + density controls.
                render_quality=self.fx_render_quality.currentText(),
                compact_density=self.fx_compact.isChecked(),
                rounded_corners=self.fx_rounded.isChecked(),
                button_style=self.fx_button_style.currentText(),
            )
            for name, val in fx.to_env_dict().items():
                os.environ[name] = val
            theme_name = getattr(self, "_last_theme", "Dark")
            # _build_effect_settings lets apply_theme use an explicit fx snapshot
            # instead of re-reading (possibly stale) env vars.
            self.apply_theme(theme_name, fx_override=fx)
        except Exception:
            pass

    def _build_effect_settings(self, fx_override=None):
        from effects import EffectSettings, apply_antialiasing, style_hints_qss
        if fx_override is not None:
            return fx_override.effective(), style_hints_qss, apply_antialiasing
        return EffectSettings.from_env().effective(), style_hints_qss, apply_antialiasing

    def _summarizer_human_send(self, text: str):
        self.summarizer.send_human_message(text)

    def _on_summarizer_chat_reply(self, label: str, text: str, thinking: str = ""):
        """Handle chat reply from summarizer - update tab display."""
        try:
            # Use the agents tab's built-in chat display (same as Manager thoughts)
            if hasattr(self, 'agents_tab') and hasattr(self.agents_tab, 'append_reply'):
                self.agents_tab.append_reply(label, text, thinking)
                # Switch to the Agents tab (index 1) using the real QTabWidget.
                if getattr(self, "tabs", None) is not None:
                    self.tabs.setCurrentIndex(1)
        except Exception as e:
            self.log_signal.emit(f"Chat display error: {e}")

    def _on_strategy_change(self, strategy: str):
        self.summarizer.set_strategy(strategy)

    def _on_summary_ready(self, text: str):
        if hasattr(self, "thought_panel"):
            self.thought_panel.route_summary(text)



    def _show_manager_win(self):
        self.thought_panel._win("Manager").show()
        self.thought_panel._win("Manager").raise_()

    def _show_agent_win(self):
        self.thought_panel._win("Agent").show()
        self.thought_panel._win("Agent").raise_()

    def _show_comms_win(self):
        self.thought_panel._win("Comms").show()
        self.thought_panel._win("Comms").raise_()

    def _show_summary_win(self):
        self.thought_panel._win("Summary").show()
        self.thought_panel._win("Summary").raise_()


if __name__ == "__main__":
    try:
        _qt_crash_log = Path(tempfile.gettempdir()) / "mrbot-qt.log"
        def _qt_message_handler(mode, context, message):
            try:
                with open(_qt_crash_log, "a", encoding="utf-8", errors="replace") as _f:
                    _f.write(f"[{datetime.now().isoformat()}] Qt {mode}: {message}\n")
            except Exception:
                pass
        qInstallMessageHandler(_qt_message_handler)
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception:
        import traceback as _tb
        _crash_dir = Path.home() / ".local" / "share" / "mrbot1000"
        _crash_dir.mkdir(parents=True, exist_ok=True)
        _crash_path = _crash_dir / "crash.log"
        with open(_crash_path, "w", encoding="utf-8") as f:
            f.write(_tb.format_exc())
        print(_tb.format_exc())
        print(f"\n[CRASH] Log written to: {_crash_path}")
        input("Press Enter to exit…")