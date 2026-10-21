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
    - MainWindow: Main application window with tabbed interface
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

# Route Python `logging` to stderr so diagnostics (e.g. ARCH-ENG-109 brain
# chat-failure logging) are visible in the launch console. Without a handler
# the root logger drops records, which is why those diagnostics were invisible.
import logging as _logging  # noqa: E402

# ARCH-ENG-305 (R-02): shared collector for non-fatal settings failures.
from gui.error_collector import record_gui_error  # noqa: E402
if not _logging.getLogger().handlers:
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

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
#
# ARCH-ENG-114: this parser must only consume argv when main.py is the
# ENTRYPOINT. It used to run unconditionally at import, and `parse_known_args`
# happily ate flags belonging to whatever host process imported the module:
# pytest's `-s` (no capture) parses as the short-option cluster `-s` + `m`,
# which argparse expands to `-sm`, so `python -m pytest -s` silently turned
# MRBOT_SAFE_MODE on for the entire test session. Every ActionPipeline built
# afterwards then skipped its file writes, and 3 tests in
# tests/safety/test_safe_mode_pipeline.py failed purely because the operator
# (or CI) added `-s` to the pytest command line.
#
# Guard on __main__: only the real entrypoint parses argv.
import argparse

_parser = argparse.ArgumentParser(description="MrBot1000 desktop application", add_help=True)
_parser.add_argument("-sm", "--safe-mode", action="store_true",
                     help="Run in safe mode (alias for MRBOT_SAFE_MODE=true)")
if __name__ == "__main__":
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

from agents.brains.base_worker import ROOT_FOLDER, WorkerAgent

# Phase 6: unified event logger, notification service, human-approval queue,
# alerting rule engine. (ARCH-ENG-243: the survival-tier alert rule is gone
# with the legacy heartbeat event it filtered -- its emitter was retired and
# the rule could not even be constructed after the enum member went.)
from agents.core.event_logger import StructuredEventLogger, Event, EventLevel, EventType
from agents.core.notifications import NotificationService, NotifLevel, notify
from agents.safety.approval import HumanApprovalQueue, ApprovalKind, ApprovalStatus
from agents.providers.provider_manager import ProviderManager, ProviderStatus
from agents.core.feature_flags import feature_enabled
from agents.providers.provider_hot_reload import ProviderHotReload
from agents.core.alerting import (
    AlertRuleEngine, add_default_rules,
    llm_spend_threshold_rule, safety_block_rule,
    pending_approval_aging_rule,
)
from app.database import AgentDB
from gui.builders.tab_builders import TabBuildersMixin

# Theme system — single source of truth lives in theme_config.py
# (preset definitions + env-driven "Custom" theme via MRBOT_THEME_*).
from app.theme_config import (
    CUSTOM_THEME_NAME,
    THEME_PRESETS,
    resolve_theme_definition,
)

try:
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)
except Exception:
    # A locked/locked-temp .env shouldn't crash startup; env vars are read lazily.
    pass

from app.environment import EnvWriteRefused, env_file_path, set_env_values

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
            from app.earning_pipeline import EarningPipeline
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
            import app.provider_models as pm
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

def _log_shutdown_warning(worker) -> None:
    """Note a worker that did not stop within the grace period.

    Deliberately does NOT fall back to QThread.terminate(): killing a thread
    blocked in a socket read corrupts the process. A lingering daemon thread is
    far less harmful than a hard crash, so it is logged and left to be reaped at
    interpreter exit.
    """
    try:
        import sys
        name = type(worker).__name__
        print(f"[shutdown] {name} did not stop within 10s; leaving it to exit with the process",
              file=sys.stderr)
    except Exception:
        pass


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
        from app.action_pipeline import ActionPipeline
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
            from agents.services.application_services import build_earning_services
            earning_services = build_earning_services(
                ROOT_FOLDER,
                log_fn=lambda msg: self.log_signal.emit(f"[Earning] {msg}"),
            )
            self._earning_services = earning_services
            self._composition_root = earning_services.root
            self.earning_pipeline = earning_services.pipeline
            self.opportunity_portfolio = earning_services.portfolio
            self.autonomous_run_store = earning_services.run_store
        except Exception as _ep_err:
            self.log_signal.emit(f"[Startup] EarningPipeline unavailable: {_ep_err}")

        # v2.0.22 S1: Instruction Provenance Gate — single trust anchor for any
        # external playbook/SKILL.md fetched by platform adapters.
        try:
            from agents.safety.instructions import InstructionGate
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

        # Consumed-once ledger for approved ACTION execution. A decided queue
        # item stays APPROVED forever, and two GUI surfaces route the same
        # human decision to `_execute_approved_action` (ApprovalPanel's
        # `item_decided` and SafetyTab's `_route_decision`), so the id set —
        # not the queue status — is what makes one approval run an irreversible
        # action at most once.
        self._executed_approval_ids: set = set()

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

        ollama_chat  = os.getenv("OLLAMA_CHAT_MODEL", "").strip() or None
        ollama_main  = os.getenv("OLLAMA_MAIN_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or None
        self.log_signal.emit(f"[Startup] OLLAMA_CHAT_MODEL from env: {ollama_chat}")
        self.log_signal.emit(f"[Startup] OLLAMA_MAIN_MODEL from env: {ollama_main}")
        api_key      = os.getenv("OPENAI_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
        self.worker  = WorkerAgent(api_key, self.log_signal, db=self.db,
                                   chat_ollama_model=ollama_chat,
                                   primary_ollama_model=ollama_main)

        # ── Phase 6: heartbeat + bridges ────────────────────────────────────
        # (legacy ManagerThread/SummarizerThread removed — N-device peer council
        #  in Dialogue is the decision authority; see docs/LEGACY_AUDIT.md)

        # Bridge: approval queue → notification service
        self.approval_queue.on_change = self._on_approval_queue_change

        # Bridge: event logger → alerting engine
        self.event_logger.on_log = self._on_event_logged

        # Provider hot-reload: monitor .env for changes and update providers at runtime
        try:
            from agents.providers.provider_hot_reload import ProviderHotReload
            self.provider_hot_reload = ProviderHotReload.instance()
            self.provider_hot_reload.register_callback(self._on_provider_config_changed)
            self.provider_hot_reload.start_monitoring(interval=2.0)
            self.log_signal.emit("[Startup] Provider hot-reload monitoring started")
        except Exception as e:
            self.log_signal.emit(f"[Startup] Provider hot-reload unavailable: {e}")
            self.provider_hot_reload = None

        # (legacy worker registration + Manager/Summarizer signal wiring removed —
        #  N-device peer council in Dialogue is the decision authority)

        self.log_signal.connect(self._safe_log)

        # Kick off provider/GPU detection on a BACKGROUND thread before the UI
        # builds. The eager Providers & GPU tab build calls get_gpus()/…
        # get_providers(); without this, the first such call would run the full
        # detect_providers() (~2.4s of sequential HTTP probes to down local
        # servers) synchronously on the GUI thread and freeze the window.
        # warm_up() is idempotent and non-blocking; the tab re-renders from the
        # populated cache via its provider_detection_ready signal.
        try:
            from agents.providers.provider_manager import ProviderManager
            ProviderManager.instance().warm_up()
        except Exception as _wu_err:
            self.log_signal.emit(f"[Startup] Provider warm-up skipped: {_wu_err}")

        # Create UI first, then start threads
        self.create_ui()
        self.apply_theme("Dark")

        # (legacy summarizer/manager thread start removed)

        # P4 (comms redesign): bridge the EventBus into the GUI thread so the
        # dashboard observes OPPORTUNITY/EVIDENCE/NOTIFICATION events without
        # sniffing arbitrary chat strings or reading a JSON mirror.
        try:
            from agents.core.comms import QtEventBridge
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

        # v2.0.34ag (A5): status_label is created here (top-level) so it exists
        # before the lazy Management tab is built; create_management_tab reuses it.
        self.status_label = QLabel("Agent status: Not registered")

        if api_key:
            self.status_label.setText("Agent status: Registered ✓")

        # v2.0.21 P1#1: verify runtime deps at boot so a missing package (e.g.
        # feedparser in a different Python env) shows a clear warning instead of
        # silently killing discovery mid-run.
        self._check_dependencies()
        # v2.0.21 P1#3: surface model-config issues at startup (no crash).
        self._validate_model_config(ollama_main, ollama_chat)

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
            self.log_signal.emit("[Startup] WARN: requirements.txt not found")
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
            self.log_signal.emit(msg)
            print(msg)
        else:
            self.log_signal.emit("[Startup] Dependencies OK")

    # ── v2.0.21 P1#3: startup model-config validation ────────────────────────
    def _validate_model_config(self, main_model: str | None, chat_model: str | None):
        """Emit clear startup warnings about model configuration problems.
        Never crashes — purely advisory so the operator can fix config."""
        def warn(msg):
            full = f"[Startup] MODEL WARN: {msg}"
            self.log_signal.emit(full)
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
        # ARCH-ENG-225: THE SAME HAZARD, AND IT HAD BEEN MISSED FROM THIS LIST.
        #
        # The provider hot-reload thread is started at :543, polls `.env` every
        # 2 s, and `stop_monitoring()` had ZERO callers in the codebase -- so it
        # was only ever ended by the interpreter killing a daemon thread during
        # finalisation. A full-suite run on this machine died with "Windows fatal
        # exception: access violation" with `_monitor_loop` as the faulting
        # thread.
        #
        # The callbacks are bound methods of this window; `unregister_all` also
        # drops them, so the singleton does not keep the whole window alive.
        try:
            hr = getattr(self, "provider_hot_reload", None)
            if hr is not None:
                hr.stop_monitoring(unregister_all=True)
        except Exception:
            pass
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
        # (legacy manager/summarizer thread-stop loop removed)
        try:
            if getattr(self, "db", None) is not None:
                self.db.close()
        except Exception:
            pass

    def _disconnect_worker_signals(self, worker):
        """Disconnect every signal on a stopping worker from its GUI receivers.

        A QThread that has stopped may still have queued cross-thread signal
        deliveries in the GUI event queue. If those land after the receiving
        widgets are destroyed, Qt dereferences a dead C++ object and the process
        dies with an access violation (python.exe Qt6Core.dll 0xc0000409).
        Disconnecting here makes teardown safe.

        v2.1.61 (ARCH-ENG-074): this was a silent no-op. It tested
        ``method.isSignal()``, but this PySide6 (6.11) has no
        ``QMetaMethod.isSignal()`` — it raises ``AttributeError`` on the first
        signal, which the outer ``except: pass`` swallowed, so the loop aborted
        and NOT ONE signal was ever disconnected. The "disconnect before wait"
        protection for the manager/summarizer threads (and, until now, every
        orphaned tab worker) never actually ran. Detect signals via
        ``methodType() == MethodType.Signal`` (with an isSignal() fallback for
        other PySide builds). Iterate by relativeMethodIndex so a failure on one
        method cannot abort the rest.

        v2.1.77 (ARCH-ENG-096): disconnecting a signal on a worker whose C++
        object is already torn down emits a noisy ``RuntimeWarning: Failed to
        disconnect (None) from signal ...`` on exit. That is a WARNING, not an
        exception, so the ``except`` never caught it. Guard with
        ``shiboken6.isValid`` (skip a dead object entirely) and suppress the
        residual warning so exit is clean and silent.
        """
        try:
            from PySide6.QtCore import QObject, QMetaMethod
            signal_type = QMetaMethod.MethodType.Signal
        except Exception:
            try:
                from PySide6.QtCore import QObject
            except Exception:
                return
            signal_type = None
        # A worker whose C++ object is already gone can't be disconnected from;
        # calling .disconnect() on it only warns. Skip it.
        try:
            import shiboken6
            if not shiboken6.isValid(worker):
                return
        except Exception:
            pass
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                meta = worker.metaObject()
                for i in range(meta.methodCount()):
                    method = meta.method(i)
                    is_signal = False
                    if signal_type is not None:
                        try:
                            is_signal = method.methodType() == signal_type
                        except Exception:
                            is_signal = False
                    else:
                        try:
                            is_signal = bool(method.isSignal())
                        except Exception:
                            is_signal = False
                    if not is_signal:
                        continue
                    name = bytes(method.name()).decode("utf-8", "ignore")
                    try:
                        sig = getattr(worker, name, None)
                        if sig is not None:
                            sig.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass

    def _stop_tab_background_threads(self):
        """Stop QThread/QTimer resources owned by lazily-built tab widgets.

        Each tab is wrapped in a QScrollArea once built. Any widget exposing a
        ``cleanup()`` method (DualBrainControl, SafetyToolsTab, ...) is asked to
        stop its background work. Idempotent and never raises.

        After the explicit cleanup calls, the widget tree is swept for any
        QThread still running. A tab that keeps a *reference* to a poller which
        is not the widget's current attribute (e.g. after a model restart
        replaced it) would otherwise survive teardown and abort the process with
        an access violation at exit.
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
        self._stop_orphan_tab_threads(tabs)

    def _stop_orphan_tab_threads(self, tabs):
        """Stop any QThread still running inside a tab widget's subtree.

        v2.1.61 (ARCH-ENG-074): disconnect each worker's signals BEFORE waiting.
        A worker still mid-generation (blocked in a long provider HTTP read, e.g.
        the 27B Big Brain) cannot finish inside the wait() grace period, so it
        survives teardown. Any queued cross-thread emission it delivers after its
        receiving widgets are destroyed dereferences a dead C++ object and aborts
        the interpreter with an access violation (observed: python.exe
        Qt6Core.dll 0xc0000409, constant fault offset, every session). This is the
        same disconnect-before-wait treatment `_disconnect_worker_signals` already
        gives the manager/summarizer threads; extend it to every orphaned tab
        worker (Chat/Dialogue InferenceWorker / EscalationWorker / DialogueWorker,
        which have no cleanup() of their own).
        """
        try:
            from PySide6.QtCore import QThread
        except Exception:
            return
        seen = set()
        for index in range(tabs.count()):
            outer = tabs.widget(index)
            if outer is None:
                continue
            for thread in outer.findChildren(QThread):
                if id(thread) in seen:
                    continue
                seen.add(id(thread))
                try:
                    import shiboken6
                    if not shiboken6.isValid(thread):
                        continue
                except Exception:
                    pass
                try:
                    if not thread.isRunning():
                        continue
                    # Disconnect BEFORE the graceful wait so a worker that
                    # outlives the wait cannot deliver a signal into a widget
                    # that is about to be destroyed.
                    self._disconnect_worker_signals(thread)
                    if hasattr(thread, "stop"):
                        thread.stop()
                    elif hasattr(thread, "requestInterruption"):
                        thread.requestInterruption()
                    thread.wait(5000)
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

    # ── EventBus bridge (P4 comms redesign) ──────────────────────────────────
    def _on_bus_event(self, msg):
        """Surface structured bus events in the GUI."""
        try:
            from agents.core.comms import MessageType
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
            QTimer.singleShot(0, self._refresh_approval_panel_and_alert)
        except Exception:
            pass

    def _refresh_approval_panel_and_alert(self):
        """Refresh the approval list and its tab-level alert on the GUI thread."""
        approval_panel = getattr(self, "_approval_panel", None)
        if approval_panel and hasattr(approval_panel, "refresh_now"):
            approval_panel.refresh_now()
        self._refresh_approval_alert()

    def _on_approval_decided(self, item_id, status, notes):
        """Refresh the approval tab alert after a human decision.

        When the human APPROVES an ``ACTION`` approval whose payload names a
        tool, the queued action must actually run. Before this the payload was
        stored and never read, so an approved mutating tool was terminal: the
        operator approved it and nothing happened.

        The decision is re-read from the QUEUE, never taken from the signal
        argument: the argument is whatever the emitter passed, so trusting it
        would let a spurious/forged signal execute an action nobody approved.
        Only an item the queue itself records as APPROVED runs, and only when
        its kind is ACTION. ``approved=True`` still cannot unblock a BLOCKED
        tool, and nothing self-approves.

        A ``SUBMISSION`` approval is handled the same way: the decision is
        re-read from the queue and the Earning tab's submitter is asked to
        send it. Before this an approved freelance submission was also
        terminal — the request was queued, the operator approved it, and it
        was never submitted.
        """
        self._refresh_approval_alert()
        try:
            queue = getattr(self, "approval_queue", None)
            item = queue.find_by_id(item_id) if queue is not None else None
            if item is None:
                return
            if item.status != ApprovalStatus.APPROVED:
                return
            if item.kind == ApprovalKind.ACTION:
                # ARCH-ENG-283 (G-05): a live-trading order is an ACTION item
                # whose payload names the exact TradeIntent. It must not fall
                # through to the generic tool dispatcher, which has no
                # `live_trade` tool and would silently drop the approval.
                payload = getattr(item, "payload", None) or {}
                if (getattr(item, "requested_by", "") == "live_trading"
                        and isinstance(payload.get("intent"), dict)):
                    self._execute_approved_live_order(item)
                else:
                    self._execute_approved_action(item)
            elif item.kind == ApprovalKind.SUBMISSION:
                self._execute_approved_submission(item)
        except Exception as e:
            self.log_signal.emit(f"[Approval] Approved action failed to execute: {e}")

    def _execute_approved_live_order(self, item):
        """ARCH-ENG-283 (G-05): submit the live order the human approved.

        This is the production caller of `LiveTradingService.execute_order`.
        The service re-reads the queue item by id, verifies that its payload
        names exactly this order, re-assesses against live exchange state, and
        refuses if the market moved or the approval was already consumed. This
        handler adds no trust of its own: it reconstructs the intent from the
        item the human decided, then lets the service's gates run.
        """
        executed = getattr(self, "_executed_approval_ids", None)
        if executed is None:
            executed = set()
            self._executed_approval_ids = executed
        item_id = getattr(item, "id", "") or ""
        if item_id and item_id in executed:
            self.log_signal.emit(
                "[LiveTrading] Ignored duplicate approval decision for "
                f"{item_id}; one approval submits at most one order.")
            return

        service = getattr(self, "live_trading_service", None)
        if service is None:
            self.log_signal.emit(
                "[LiveTrading] Approved order could not be executed: the "
                "Live Portfolio tab/service is not initialized; no order was "
                "submitted.")
            return
        payload = getattr(item, "payload", None) or {}
        data = payload.get("intent")
        if not isinstance(data, dict):
            self.log_signal.emit(
                "[LiveTrading] Approved order has no intent payload; no order "
                "was submitted.")
            return
        details = getattr(item, "details", None) or {}
        try:
            # Keep the optional ccxt adapter out of the application bootstrap
            # (the architecture-boundary test forbids main.py importing it).
            # This helper lives in services/ and imports the live-trading types
            # only on an actual approved execution.
            from agents.services.live_order_execution import (
                reconstruct_approved_order,
            )
            intent, assessment = reconstruct_approved_order(data, details)
            result = service.execute_order(
                intent, assessment, approval_id=item_id)
        except Exception as exc:
            # The service consumes an approval only after every gate, but a
            # transport failure during create_order is ambiguous: the order may
            # or may not have reached the exchange, and the service's ledger may
            # already hold the id. Do not tell the operator to replay it.
            self.log_signal.emit(
                f"[LiveTrading] Approved order FAILED; check the exchange "
                f"before re-approving (the approval may already be consumed): "
                f"{exc}")
            return
        if item_id:
            executed.add(item_id)
        self.log_signal.emit(
            f"[LiveTrading] Executed approved order: {result}")

    def _execute_approved_action(self, item):
        """Run an approved ACTION item's tool, re-reading the queue decision.

        A decided queue item stays APPROVED forever, and TWO surfaces route the
        same human decision here (``ApprovalPanel`` emits ``item_decided`` and
        ``SafetyTab._route_decision`` calls the handler directly), so the queue
        status alone cannot distinguish "first delivery of this approval" from
        "the same approval delivered again". Reproduced: one approval ran
        ``run_command`` twice — two irreversible executions, with the queue
        still reporting 1 item / 0 pending, so nothing looked wrong.

        The consumed-once ledger fixes that the same way
        ``PlatformSubmitter.submit_if_approved`` does for submissions: an
        approval id may execute at most once per process. A SECOND, distinct
        approval (a different id, for a different item) still runs — only a
        re-delivery of an id that already executed is refused. The check lives
        AFTER the caller's queue re-read, so the approval must still be genuine
        and still valid before the ledger is even consulted; this guard can
        only ever refuse an execution, never cause one. A re-emission is
        logged, because from the operator's side the click simply appears to
        do nothing and that must be explainable.
        """
        executed = getattr(self, "_executed_approval_ids", None)
        if executed is None:
            executed = set()
            self._executed_approval_ids = executed
        item_id = getattr(item, "id", "") or ""
        if item_id and item_id in executed:
            self.log_signal.emit(
                "[Approval] Ignored duplicate decision for approval "
                f"{item_id}: the approved action was already executed once "
                "(one human approval executes an irreversible action at most "
                "once).")
            return
        payload = getattr(item, "payload", None) or {}
        tool = payload.get("tool")
        arguments = payload.get("arguments")
        if not tool or not isinstance(arguments, dict):
            return
        # ARCH-ENG-129: stamp THIS approval's id into the arguments. The model
        # cannot know an approval id before the item exists, so the queued
        # arguments carry either no `approval_id` or a placeholder — and the
        # HIGH-TRUST tools then refuse a call that a human genuinely approved.
        # Re-stamping here makes the executed call provably the one the
        # operator approved (same id the queue recorded), and it is the only
        # place an id could legitimately enter the call.
        arguments = dict(arguments)
        if item_id:
            arguments["approval_id"] = item_id
        from agents.safety.dispatch import execute_tool
        try:
            # ARCH-ENG-165: pass the approval id as well as the boolean. The
            # boolean alone is a caller assertion; with the id, the dispatcher
            # verifies against the shared queue via `assert_approval_covers`, so
            # the executed call must be the exact tool + arguments the operator
            # approved. The id was just re-stamped into `arguments` above from
            # the item the operator actually decided, so this binds the two.
            result = execute_tool(tool, arguments, approved=True,
                                  approval_id=item_id or None)
        except Exception:
            # NOT consumed. The id is deliberately left out of the ledger: an
            # execution that raised may not have taken effect (a network
            # timeout leaves the outcome unknown), so the operator must be
            # able to re-deliver the same approval. Consuming it here would
            # make a transient failure permanently unretryable, and the log
            # would then claim the action "was already executed once" when it
            # never ran. Failing to consume is the safe direction: the worst
            # case is a duplicate delivery, which the caller's own
            # once-per-emission contract already bounds.
            self.log_signal.emit(
                f"[Approval] Approved action {tool} FAILED to execute; the "
                f"approval was NOT consumed and may be retried: see the "
                f"error above.")
            raise
        if item_id:
            executed.add(item_id)
        self.log_signal.emit(
            f"[Approval] Executed approved action {tool}: {result}")

    def _execute_approved_submission(self, item):
        """Send an approved SUBMISSION via the Earning tab's submitter.

        The record id travels in the queued payload; the decision itself is
        re-read by ``PlatformSubmitter.submit_if_approved`` from the queue,
        so this method cannot cause a submission on its own.

        No idempotency guard is added here ON PURPOSE: the submitter already
        refuses to send a record twice (it checks ``record.status`` and
        ``record.submitted_at``), so the submission path is consumed-once by
        construction. Adding a second ledger would guard the same invariant
        twice and, worse, would refuse a legitimate resend the submitter
        itself would still accept. The ACTION path has no equivalent guard at
        its sink, which is why ``_execute_approved_action`` needs one.
        """
        details = getattr(item, "details", None) or {}
        arguments = details.get("arguments")
        record_id = None
        if isinstance(arguments, dict):
            record_id = arguments.get("record_id")
        tab = getattr(self, "_earning_tab", None)
        submitter = getattr(tab, "platform_submitter", None) if tab else None
        if submitter is None or not record_id:
            self.log_signal.emit(
                "[Approval] Approved submission could not be routed: "
                f"record_id={record_id!r}, submitter="
                f"{'present' if submitter else 'missing'}")
            return
        record = submitter.get_record(record_id)
        if record is None:
            self.log_signal.emit(
                f"[Approval] Approved submission record {record_id} not found")
            return
        result = submitter.submit_if_approved(record)
        self.log_signal.emit(
            f"[Approval] Submission {record_id}: {result}")

    def _refresh_approval_alert(self):
        """Update the Approvals tab label, color, and pending-count tooltip."""
        try:
            queue = getattr(self, "approval_queue", None)
            pending_count = len(queue.pending()) if queue is not None else 0
            index = self._tab_index_by_label("Approvals")
            if index < 0:
                return
            label = "Approvals" if pending_count == 0 else f"Approvals ({pending_count})"
            self.tabs.setTabText(index, label)
            if pending_count:
                self.tabs.setTabToolTip(
                    index, f"{pending_count} approval request(s) awaiting human review")
                self.tabs.tabBar().setTabTextColor(index, QColor("#ffb300"))
            else:
                self.tabs.setTabToolTip(index, "No pending approval requests")
                self.tabs.tabBar().setTabTextColor(index, QColor("#e0e0e0"))
            self.tabs.tabBar().update()
        except Exception:
            pass

    def _tab_index_by_label(self, label):
        """Find a tab by its stable base label, ignoring an alert count suffix."""
        if not hasattr(self, "tabs"):
            return -1
        for index in range(self.tabs.count()):
            text = self.tabs.tabText(index)
            if text == label or text.startswith(f"{label} ("):
                return index
        return -1

    def _on_event_logged(self, event):
        """Called when an event is logged. Evaluate alerting rules and feed
        the goal tracker."""
        try:
            engine = getattr(self, "alerting_engine", None)
            if engine:
                engine.process_event(event)
        except Exception:
            pass
        # ARCH-ENG-244 (BF-01): the goal tracker is the event stream's other
        # live consumer. Credits go through its verified-guard (add_evidence
        # -- BF-02's single credit path), so an event can never move a
        # goal's money by an unverified amount; guarded so telemetry-side
        # failures cannot break the logging path itself.
        try:
            from agents.earning.goal_system import GoalTracker
            GoalTracker.instance().process_event(event)
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
            
            # Apply the changes to the running process. ProviderHotReload.apply_changes
            # pushes the new values into os.environ (the actual "apply" — previously the
            # handler re-detected providers but never updated os.environ, so it logged
            # "changes applied" while the running app kept the stale config) and
            # re-detects. instance() is the fixed singleton.
            ProviderHotReload.instance().apply_changes(changes)

            self.log_signal.emit("[Provider] Configuration updated - changes applied")
        except Exception as e:
            self.log_signal.emit(f"[Provider] Error applying config changes: {e}")

    def _safe_log(self, msg: str):
        # v2.0.34an: always buffer, even if log_edit isn't built yet (Live Logs is a
        # lazy tab). This keeps pre-tab-build logs from being dropped; the buffer
        # is replayed into the widget when the tab is first built (_replay_log_buffer).
        if not hasattr(self, "_log_buffer"):
            self._log_buffer = []
        self._append_log(msg)

    def _current_log_filters(self):
        """ARCH-ENG-319: live appends, replays and filter rebuilds must agree
        on what is displayed, or the table (a view) and the buffer disagree.
        All three roads now read the filters from this one accessor."""
        filter_text = (self.log_filter.text().lower()
                       if getattr(self, "log_filter", None) is not None else "")
        severity_filter = (self.log_severity_combo.currentText()
                           if getattr(self, "log_severity_combo", None) is not None
                           else "All")
        category_filter = (self.log_category_combo.currentText()
                           if getattr(self, "log_category_combo", None) is not None
                           else "All")
        return filter_text, severity_filter, category_filter

    def _entry_passes_filters(self, e):
        filter_text, severity_filter, category_filter = self._current_log_filters()
        if severity_filter != "All" and e.get("severity") != severity_filter:
            return False
        if category_filter != "All" and e.get("category") != category_filter:
            return False
        if filter_text and filter_text not in e.get("msg", "").lower():
            return False
        return True

    def _replay_log_view(self):
        """Rebuild the visible table from the buffer under the current filters
        and record exactly which buffered entries the rows map to."""
        if not hasattr(self, "log_table") or self.log_table is None:
            return
        self.log_table.setRowCount(0)
        self._view_entries = []
        for e in self._log_buffer:
            self._append_log_to_table(e)  # applies the filters itself
        if getattr(self, "auto_scroll_logs", None) and self.auto_scroll_logs.isChecked():
            self.log_table.scrollToBottom()

    def _replay_log_buffer(self):
        """Rebuild the (now shown) log table from the authoritative buffer.

        ARCH-ENG-319: this used to run at build time, while the freshly built
        widget was still hidden, so every row was "deferred" by the hidden-tab
        guard and the operator opened an empty Live Logs tab until they poked
        the filter. The deferred model is kept (buffer stays authoritative,
        hidden tabs stay untouched); the rebuild is now triggered by the shell
        widget's showEvent, so every view opens complete.
        """
        if not hasattr(self, "log_table") or self.log_table is None:
            return
        self._replay_log_view()

    def _append_log_to_table(self, entry):
        """Append a single log entry to the log table widget.

        ARCH-ENG-223: THIS RAN FOR EVERY LOG LINE, VISIBLE OR NOT.

        Each call did an `insertRow`, six `setItem` calls, and then
        `resizeRowToContents(row)` -- the canonical Qt table trap: it
        invalidates the view layout and forces a size-hint pass over the item's
        text, per line. Against a styled table capped at 5000 rows, and with
        every bus event and every worker log going through here, that is
        sustained layout churn for the life of the session, on the GUI thread,
        whether or not anyone is looking at the Live Logs tab.

        Now: nothing touches the widget while the tab is hidden. That is safe
        because every entry is already appended to `self._log_buffer` by
        `_log_emit`, and both `_replay_log_buffer` (on tab build/show) and
        `_do_apply_log_filter` (on filter change) rebuild the table from that
        buffer. Nothing is lost by deferring the widget work.

        ARCH-ENG-319: the table is a filtered VIEW of the buffer. This method
        is the only thing that ever adds a row, so it now also (a) applies the
        current filters for LIVE appends — previously a new line that did not
        match the active filter still landed on the table, polluting a
        filtered view — and (b) records the entry in `self._view_entries`,
        the row↔entry mapping the details panel reads. `_show_log_details`
        previously indexed `self._log_buffer[row]`, which only agreed with
        the table when no filter was active.

        `resizeRowToContents` is kept for the visible case, where wrapped
        details genuinely need the row height, but it now runs only for rows
        the operator can actually see.
        """
        if not hasattr(self, "log_table") or self.log_table is None:
            return
        if not self.log_table.isVisible():
            return        # deferred: the buffer is authoritative, the table is a view
        if not self._entry_passes_filters(entry):
            return        # filtered out: stays in the buffer, not on the view
        if not hasattr(self, "_view_entries"):
            self._view_entries = []
        self._view_entries.append(entry)
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
        
        # Details (category + extra context) — show full text, not truncated
        details = entry.get("category", "") or ""
        if entry.get("details"):
            details = f"{details} | {entry['details']}" if details else entry["details"]
        det_item = QTableWidgetItem(details)
        det_item.setForeground(QColor("#888888"))
        self.log_table.setItem(row, 5, det_item)
        
        # Resize row height to fit wrapped content
        self.log_table.resizeRowToContents(row)
        
        # Limit rows
        if self.log_table.rowCount() > 5000:
            self.log_table.removeRow(0)
        
        # Auto-scroll if enabled
        if getattr(self, "auto_scroll_logs", None) and self.auto_scroll_logs.isChecked():
            self.log_table.scrollToBottom()

    def _show_log_details(self):
        """Show full details of the selected log entry in the details panel."""
        if not hasattr(self, "log_details") or self.log_details is None:
            return
        selected = self.log_table.selectedItems()
        if not selected:
            self.log_details.clear()
            return
        row = selected[0].row()
        # ARCH-ENG-319: the table shows a FILTERED view; the row maps to
        # `self._view_entries`. The old `self._log_buffer[row]` only agreed
        # with the visible rows when no filter was active — with a filter on,
        # clicking a row showed the details of the WRONG entry.
        view = getattr(self, "_view_entries", None)
        if view is None:
            view = self._log_buffer
        if row < len(view):
            entry = view[row]
            lines = [
                f"Time: {entry.get('ts', 'N/A')}",
                f"Severity: {entry.get('severity', 'N/A')}",
                f"Source: {entry.get('source', 'N/A')}",
                f"Category: {entry.get('category', 'N/A')}",
                f"Message: {entry.get('msg', 'N/A')}",
            ]
            if entry.get("tokens_sec"):
                lines.append(f"Tokens/s: {entry['tokens_sec']}")
            if entry.get("details"):
                lines.append(f"Details: {entry['details']}")
            self.log_details.setText("\n".join(lines))

    def _export_logs(self):
        """Export the current log buffer to a text file."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            None, "Export Logs", "mrbot1000_logs.txt", "Text Files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for e in self._log_buffer:
                    f.write(f"[{e.get('ts','')}] {e.get('severity','INFO')} {e.get('source','')} | {e.get('msg','')}\n")
            self.log_signal.emit(f"[System] Logs exported to {path}")
        except Exception as ex:
            self.log_signal.emit(f"[System] Export failed: {ex}")

    def _append_log(self, msg: str, source: str = "", category: str = "", details: str = ""):
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Auto-detect severity from message content
        severity = "INFO"
        if "BLOCKED" in msg or "block" in msg.lower():
            severity = "BLOCKED"
        elif "ERROR" in msg or "❌" in msg or "fail" in msg.lower():
            severity = "ERROR"
        elif "Ollama" in msg or "OLLAMA" in msg:
            severity = "OLLAMA"
        elif "llama.cpp" in msg.lower() or "llamacpp" in msg.lower():
            severity = "LLAMA.CPP"
        elif "Manager" in msg or "Action" in msg or "Manager" in source:
            severity = "MANAGER"
        elif "warning" in msg.lower() or "⚠️" in msg:
            severity = "WARNING"
        elif "success" in msg.lower() or "✅" in msg or "ready" in msg.lower():
            severity = "SUCCESS"
        
        # Auto-detect category if not provided
        if not category:
            cat_lower = msg.lower()
            if "[llm]" in cat_lower or "provider" in cat_lower or "ollama" in cat_lower or "llama" in cat_lower:
                category = "LLM"
            elif "[pipeline]" in cat_lower or "validation" in cat_lower or "validate" in cat_lower:
                category = "Safety"
            elif "[earning]" in cat_lower or "revenue" in cat_lower or "cost" in cat_lower:
                category = "Earning"
            elif "[gpu]" in cat_lower or "cuda" in cat_lower or "vram" in cat_lower:
                category = "GPU"
            elif "[manager]" in cat_lower or "[agent]" in cat_lower or "heartbeat" in cat_lower:
                category = "System"
            else:
                category = "System"
        
        color = {
            "BLOCKED": "#ffcc00",
            "ERROR": "#ff4444",
            "OLLAMA": "#00b0ff",
            "LLAMA.CPP": "#42a5f5",
            "MANAGER": "#00ccff",
            "INFO": "#aaaaaa",
            "WARNING": "#ff9800",
            "SUCCESS": "#4caf50",
        }.get(severity, "#aaaaaa")
        
        # Extract tokens/sec if present in message
        tokens_sec = ""
        import re
        if "tokens/s" in msg or "tok/s" in msg:
            match = re.search(r'([\d.]+)\s*(?:tokens|tok)/s', msg)
            if match:
                tokens_sec = f"{match.group(1)} tok/s"
        
        # Extract latency info if present
        if not details:
            lat_match = re.search(r'(\d+)\s*ms', msg)
            if lat_match:
                details = f"latency={lat_match.group(1)}ms"

        entry = {
            "ts": ts,
            "msg": msg,
            "source": source or "system",
            "category": category,
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
        # ARCH-ENG-319: one rebuild path shared with the replay — the table is
        # always "the filtered buffer", no separate block logic to drift.
        self._replay_log_view()

    def _clear_log(self):
        self._log_buffer.clear()
        if hasattr(self, "_view_entries"):
            self._view_entries = []
        if hasattr(self, "log_table"):
            self.log_table.setRowCount(0)

    def create_ui(self):
        # Centered title header at the top of the program
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        try:
            from app.version import __version__
        except Exception:
            # Last-resort literal. app/version.py has no dependencies, so this
            # should be unreachable; if it ever fires, the title would silently
            # claim an old release. Keep it in step with app/version.py — the
            # single authority — and prefer fixing the import over bumping this.
            __version__ = "2.1.135"
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
                    ("Collaboration",  self.create_collaboration_tab),
                    ("Approvals",      self.create_approval_tab),
                    ("Registration",   self.create_registration_tab),
                    ("Web Browser",   self.create_file_browser_tab),
                    ("Payments",       self.create_payments_tab),
                    ("Earnings",       self.create_earnings_tab),
                    ("Insights",       self.create_insights_tab),
                    ("Opportunities",  self.create_opportunities_tab),
                    ("Social Activity", self.create_social_activity_tab),
                    ("Self-Improvement", self.create_self_improvement_tab),
                    ("Autonomous Learning", self.create_autonomous_learning_tab),
                    ("Live Portfolio", self.create_live_portfolio_tab),
                    ("Strategy Simulator", self.create_paper_trading_tab),
                    ("Analytics",      self.create_analytics_tab),
                    ("Reputation",     self.create_reputation_tab),
                    ("Data Explorer",  self.create_data_explorer_tab),
                    ("Settings",       self.create_settings_tab),
                    ("Live Logs",      self.create_logs_tab),
                    ("DB Stats",       self.create_db_stats_tab),
                ]
        optional_tabs = {
            "Social Activity": "social_automation",
            "Self-Improvement": "self_improvement",
            "Autonomous Learning": "autonomous_learning",
            "Live Portfolio": "live_trading",
            "Strategy Simulator": "live_trading",
        }
        tab_specs = [
            (label, builder)
            for label, builder in tab_specs
            if label not in optional_tabs
            or feature_enabled(optional_tabs[label])
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
        self._refresh_approval_alert()

        # Auto-populate the Ollama model dropdowns the first time the Settings
        # tab is opened, so you don't have to click Refresh manually (v2.0.20h).
        self._ollama_autorefresh_done = False
        self._settings_tab_index = next(
            i for i, (lbl, _) in enumerate(tab_specs) if lbl == "Settings")
        tabs.currentChanged.connect(self._on_tab_changed)

        # ── Auto-start llama-server on app launch ─────────────────────────────
        # v2.1.1: Auto-start is OFF by default but user-controllable. When
        # AUTO_START_SERVERS=1 (toggled via the Providers & GPU → Quick Actions
        # checkbox and persisted to .env), both llama-server instances launch
        # after the window is shown using the per-brain settings configured in
        # the Providers & GPU tab. Purely deferred + non-blocking so startup
        # stays responsive; the probes/launch run on background threads.
        self._auto_start_timer = None
        try:
            if os.getenv("AUTO_START_SERVERS", "1").strip().lower() in (
                    "1", "true", "yes", "on"):
                QTimer.singleShot(700, self._maybe_auto_start_servers)
        except Exception:
            pass  # never let auto-start scheduling break startup

        # Self-improvement post-apply monitor: re-verify applied patches on a
        # configurable cadence (MRBOT_SELF_IMPROVE_MONITOR_MINUTES). Gated by
        # the self-improvement feature flag; no-op when disabled.
        self._self_improve_monitor_timer = None
        self._start_self_improve_monitor()

    def _maybe_auto_start_servers(self):
        """Deferred hook: delegate to the Providers & GPU tab's auto-start."""
        try:
            providers_tab = getattr(self, "providers_gpu_tab", None)
            if providers_tab is not None and hasattr(providers_tab, "maybe_auto_start"):
                providers_tab.maybe_auto_start()
        except Exception as exc:
            # Auto-start is best-effort; a failure must not crash the app.
            print(f"[auto-start] deferred server launch failed: {exc}")

        # Apply the saved presentation mode after the menu actions exist.
        QTimer.singleShot(0, lambda: self._set_window_mode(self._window_mode, persist=False))

    def _start_self_improve_monitor(self):
        """Start the background post-apply monitor for self-improvement.

        Re-verifies applied patches every MRBOT_SELF_IMPROVE_MONITOR_MINUTES
        (default 30). Gated by the self-improvement feature flag — when disabled
        the timer is not started and nothing runs. Runs even when the
        Self-Improvement tab is hidden (unlike the visibility-aware refresh
        coordinator).
        """
        try:
            from agents.core.feature_flags import feature_enabled
            if not feature_enabled("self_improvement"):
                return
            minutes = int(os.getenv("MRBOT_SELF_IMPROVE_MONITOR_MINUTES", "30"))
            minutes = max(1, min(minutes, 1440))
            timer = QTimer(self)
            timer.setInterval(minutes * 60 * 1000)
            timer.timeout.connect(self._run_self_improve_monitor)
            timer.start()
            self._self_improve_monitor_timer = timer
            self.log_signal.emit(
                f"[Self-Improve] post-apply monitor every {minutes} min")
        except Exception as exc:
            self.log_signal.emit(f"[Self-Improve] monitor start failed: {exc}")

    def _run_self_improve_monitor(self):
        """Re-verify applied patches; queue new gated proposals on regression."""
        try:
            services = getattr(self, "_earning_services", None)
            if services is None:
                return
            svc = getattr(services, "code_patch_service", None)
            if svc is None or not hasattr(svc, "monitor_applied"):
                return
            # ARCH-ENG-227: PICK UP DEFERRED PATCHES ON THE SAME TICK.
            #
            # `apply_approved` queues an approved patch when its target is in
            # use, and `drain()` applies queued patches once the target frees.
            # Nothing ever called `drain()`, so an approved change could sit
            # queued indefinitely -- the operator would see it approved and
            # reasonably believe it had landed.
            #
            # The self-improvement monitor is the right place: it already runs
            # on a configurable cadence, it is already gated on the same feature
            # flag, and it is already the component responsible for keeping the
            # applied-patch set honest.
            try:
                from agents.services.self_improvement_commands import apply_deferred
                deferred = apply_deferred(svc)
                if deferred:
                    self.log_signal.emit(
                        f"[Self-Improve] applied {len(deferred)} deferred patch(es) "
                        f"whose target became available.")
            except Exception as exc:
                self.log_signal.emit(f"[Self-Improve] deferred apply failed: {exc}")

            proposals = svc.monitor_applied()
            if proposals:
                self.log_signal.emit(
                    f"[Self-Improve] monitor flagged {len(proposals)} regression(s); "
                    f"new approval-gated revert proposal(s) queued.")
        except Exception as exc:
            self.log_signal.emit(f"[Self-Improve] monitor check failed: {exc}")

    def _size_for_screen(self):
        """Choose a usable initial size on the current display.

        Use the available work area rather than physical monitor size: a
        15-inch laptop and a large monitor can have the same logical desktop,
        while Windows display scaling changes the usable pixel dimensions.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        available = screen.availableGeometry()
        dpi_scale = max(screen.logicalDotsPerInch(), 96.0) / 96.0
        compact = available.width() < 1200 or available.height() < 720
        width_ratio = 0.98 if compact else 0.92
        height_ratio = 0.96 if compact else 0.90
        preferred_width = int(2200 * min(dpi_scale, 1.25))
        preferred_height = int(1300 * min(dpi_scale, 1.15))
        width = min(preferred_width, int(available.width() * width_ratio))
        height = min(preferred_height, int(available.height() * height_ratio))
        minimum_width = min(960, max(720, available.width() - 24))
        minimum_height = min(640, max(480, available.height() - 48))
        width = max(minimum_width, width)
        height = max(minimum_height, height)
        self.setProperty("compactLayout", compact)
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

    def _toggle_pause(self, checked):
        # legacy manager heartbeat removed — no-op (control removed in Management tab)
        pass

    def _human_send(self, text: str):
        # Legacy AgentsTab send-box callback (control removed). The Chat tab /
        # N-device Dialogue is the chat authority.
        pass

    # ── A2: Verify-then-mark-paid ──────────────────────────────────────────────
    def _build_payout_verifier(self):
        try:
            from agents.earning.payout_verifier import PayoutVerifier
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
                    from agents.integrations.wallet_manager import WalletManager, resolve_wallet_root
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
            # v2.1.37 (ARCH-ENG-043): use the same trust floor as the pipeline
            # path — status 'paid' alone is not proof of payment. A manual
            # (operator-typed) reference is L1 self-report, which must never
            # advance the win-rate that unlocks auto-submission.
            try:
                pipe = getattr(self, "earning_pipeline", None)
                if pipe is not None:
                    from agents.earning.evidence import is_affirmative_verification
                    if is_affirmative_verification(state):
                        from agents.earning.submission_ramp import get_ramp
                        opp = pipe.memory.get_opportunity_history(opp_id)
                        platform = (opp or {}).get("platform") or "unknown"
                        get_ramp(getattr(pipe, "memory", None)).record_accept(platform)
                    else:
                        self.log_signal.emit(
                            "[Payout] marked paid but verification is below the L3 "
                            "external-source floor — no ramp accept credited")
            except Exception:
                pass
        else:
            self.pay_status.setText("Payout: NOT verified — left as submitted (audit logged)")
        self.log_signal.emit(f"[Payout] {self.pay_status.text()}")

    def _reconcile_paid_evidence(self, opp_id: str, evidence_id: str,
                                 method: str, note: str):
        """ARCH-ENG-287 (Z-01): the live caller for `reconcile_evidence`.

        A manual/self-reported payout is recorded as pending evidence and is
        deliberately refused by the SUBMITTED->PAID gate. `reconcile_evidence`
        is the ONLY method that can promote such a record to independent
        verification, and it had no caller anywhere -- a disputed payment could
        never be resolved.

        This handler is operator-initiated and accepts only the evidence
        policy's independent-method allow-list. It never calls the reconcile
        path for an unverified ID, never reconciles another opportunity's
        evidence, and reports a refused promotion instead of claiming success.
        """
        opp_id = (opp_id or "").strip()
        evidence_id = (evidence_id or "").strip()
        method = (method or "").strip()
        if not opp_id:
            self.pay_status.setText("Reconcile: opportunity id required")
            return
        pipe = getattr(self, "earning_pipeline", None)
        lifecycle = getattr(pipe, "lifecycle", None) if pipe is not None else None
        store = getattr(lifecycle, "_evidence_store", None) if lifecycle else None
        if lifecycle is None or store is None:
            self.pay_status.setText(
                "Reconcile: lifecycle/evidence store unavailable")
            return
        from agents.evidence.evidence_policy import (
            _INDEPENDENT_RECONCILIATION_METHODS,
        )
        from agents.earning.payment_evidence import PAYMENT_EVIDENCE_TYPES
        if method not in _INDEPENDENT_RECONCILIATION_METHODS:
            self.pay_status.setText(
                f"Reconcile: '{method}' is not an independent method; "
                "refused")
            return
        try:
            if evidence_id:
                evidence = store.get(evidence_id)
                if evidence is None:
                    # An explicit id is a precise operator instruction. Never
                    # substitute a different record just because the id was
                    # mistyped or stale.
                    self.pay_status.setText(
                        f"Reconcile: evidence {evidence_id} not found; "
                        "nothing was changed")
                    return
            else:
                # No id supplied: choose the latest monetary evidence for THIS
                # opportunity that is not already independently verified.
                evidence = None
                candidates = []
                for ev in store.for_subject("opportunity", opp_id):
                    if ev.evidence_type not in PAYMENT_EVIDENCE_TYPES:
                        continue
                    status = str(getattr(ev.status, "value", ev.status)).upper()
                    level = int(getattr(
                        ev.verification_level, "value",
                        ev.verification_level) or 0)
                    if status in {"VERIFIED", "PARTIALLY_VERIFIED"} and level >= 3:
                        continue
                    candidates.append(ev)
                evidence = candidates[-1] if candidates else None
            if evidence is None:
                self.pay_status.setText(
                    "Reconcile: no unresolved payment evidence for "
                    f"{opp_id}")
                return
            if (str(getattr(evidence, "subject_type", "")) != "opportunity"
                    or str(getattr(evidence, "subject_id", "")) != opp_id):
                self.pay_status.setText(
                    "Reconcile: evidence does not belong to this opportunity")
                return
            reconciled = lifecycle.reconcile_evidence(
                opp_id, evidence.id, reconciler="operator",
                note=(note or "reconciled from Management payout review"),
                method=method)
        except Exception as exc:
            self.pay_status.setText(f"Reconcile: failed: {exc}")
            self.log_signal.emit(f"[Reconcile] error: {exc}")
            return
        if reconciled is None:
            self.pay_status.setText(
                "Reconcile: refused (no store or evidence not found)")
            self.log_signal.emit(
                f"[Reconcile] {opp_id}: refused; no evidence was changed")
            return
        status = str(getattr(reconciled.status, "value", reconciled.status)).upper()
        applied = (status in {"VERIFIED", "PARTIALLY_VERIFIED"}
                   and str(getattr(reconciled, "verification_method", "")) == method)
        state = lifecycle.get_state(opp_id)
        if not applied:
            self.pay_status.setText(
                f"Reconcile: REFUSED by evidence policy ({status})")
            self.log_signal.emit(
                f"[Reconcile] {opp_id}/{evidence.id}: refused; "
                "the evidence remains non-affirmative")
            return
        self.pay_status.setText(
            f"Reconcile: VERIFIED via {method}; lifecycle={state.get('status')}")
        # An independently reconciled payment is affirmative evidence; credit
        # the submission ramp exactly once, as the verify path does.
        if state.get("status") == "paid":
            try:
                level = int(getattr(
                    reconciled.verification_level, "value",
                    reconciled.verification_level) or 0)
                if getattr(reconciled.status, "is_affirmative", False) and level >= 3:
                    from agents.earning.submission_ramp import get_ramp
                    hist = (pipe.memory.get_opportunity_history(opp_id) or {})
                    get_ramp(getattr(pipe, "memory", None)).record_accept(
                        hist.get("platform") or "unknown")
            except Exception:
                pass
        self.log_signal.emit(f"[Payout] {self.pay_status.text()}")

    # ── A1: Gig proposal review + human-confirmed submission ──────────────────
    def _build_upwork_client(self):
        """Construct an UpworkClient from .env creds (or None if absent)."""
        try:
            import os

            from agents.integrations.upwork import UpworkClient
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
        # ARCH-ENG-294 (O-02): ProposalReviewer's optional AnalystWorker was
        # never supplied, so the quality half of the pre-submission gate was
        # structurally absent. AnalystWorker's proposal scoring is deterministic
        # and does not need a live model key; passing an empty key keeps this
        # path available offline. If the analyst cannot be built, fall back to
        # the rule-based reviewer rather than dropping the gate.
        try:
            from agents.knowledge.proposal_reviewer import ProposalReviewer
            from agents.services.analyst_worker import AnalystWorker
            analyst = AnalystWorker(
                api_key="",
                log_signal=self.log_signal,
                db=getattr(self, "db", None),
            )
            return ProposalReviewer(analyst=analyst)
        except Exception:
            try:
                from agents.knowledge.proposal_reviewer import ProposalReviewer
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

        import app.earning_pipeline as EP
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

    def force_safe_improve(self):
        # legacy manager queue removed — route intent to the N-device Dialogue
        self.log_signal.emit(
            "Self-improvement: use the Dialogue tab to direct the peer council")

    def force_research_rescan(self):
        """Actually re-scan the research folder (ARCH-ENG-271/272).

        This handler used to just print "use the Dialogue tab": the button,
        the worker's ``research_all()`` and both cache tables existed, but
        nothing ever called the scan. So the file cache was never written, the
        research-snapshot counter stayed 0, and the dialogue's research
        context always read "(not set)". The scan now runs here; the worker
        writes the file cache and the research snapshot as it reads.
        """
        worker = getattr(self, "worker", None)
        if worker is None or not hasattr(worker, "research_all"):
            self.log_signal.emit("Research re-scan: worker is not available")
            return
        self.log_signal.emit("Research re-scan started...")
        result = None
        error = None
        try:
            result = worker.research_all()
        except Exception as exc:
            error = exc

        if result is None:
            cached = None
            db = getattr(self, "db", None)
            folder = getattr(worker, "research_folder", "") or ""
            if db is not None and folder:
                try:
                    cached = db.load_latest_research_cache(folder)
                except Exception:
                    cached = None
            if cached is not None:
                self.log_signal.emit(
                    f"Research re-scan failed ({error}); showing the last "
                    f"cached snapshot from {cached.get('research_path')}")
            else:
                self.log_signal.emit(f"Research re-scan failed: {error}")
            self._refresh_cache_stats()
            return

        self.log_signal.emit(
            f"Research re-scan complete: "
            f"{result.get('research_file_count', 0)} research file(s) from "
            f"{result.get('research_path') or '(not set)'}")
        self._refresh_cache_stats()

    def clear_file_cache(self):
        reply = QMessageBox.question(
            self, "Clear Cache",
            "Delete all cached file contents?",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.db.clear_file_cache()
            self.log_signal.emit("File cache cleared")
            self._refresh_cache_stats()

    def _refresh_cache_stats(self):
        """Update the cache statistics label in the Settings tab."""
        if not hasattr(self, "cache_stats_label") or self.cache_stats_label is None:
            return
        try:
            db = getattr(self, "db", None)
            if db is None or getattr(db, "_conn", None) is None:
                return
            # File cache entries
            row = db._execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM file_cache").fetchone()
            cache_count = row[0] if row else 0
            cache_bytes = row[1] if row else 0
            cache_mb = cache_bytes / (1024 * 1024)
            
            # Research cache entries
            row2 = db._execute("SELECT COUNT(*) FROM research_cache").fetchone()
            research_count = row2[0] if row2 else 0
            
            self.cache_stats_label.setText(
                f"File cache: {cache_count:,} entries ({cache_mb:.1f} MB) | "
                f"Research cache: {research_count:,} entries"
            )
        except Exception as e:
            self.cache_stats_label.setText(f"Error: {e}")

    def refresh_db_stats(self):
        """Refresh DB Stats tab with data from app.database."""
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
            # (legacy manager.get_discovery_summary() removed)

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
            self.db_stat_prompt_tokens.value_label.setText(f"{int(stats.get('total_prompt_tokens', 0)):,}")
            self.db_stat_completion_tokens.value_label.setText(f"{int(stats.get('total_completion_tokens', 0)):,}")
            
            # Update provider table
            self.provider_table.setRowCount(0)
            provider_stats = stats.get("by_provider", {})
            for provider, pstats in provider_stats.items():
                row = self.provider_table.rowCount()
                self.provider_table.insertRow(row)
                self.provider_table.setItem(row, 0, QTableWidgetItem(str(provider)))
                self.provider_table.setItem(row, 1, QTableWidgetItem(str(pstats.get("calls", 0))))
                self.provider_table.setItem(row, 2, QTableWidgetItem(str(pstats.get("errors", 0))))
                self.provider_table.setItem(row, 3, QTableWidgetItem(f"{pstats.get('avg_ms', 0) or 0:.0f}"))
                self.provider_table.setItem(row, 4, QTableWidgetItem(f"{pstats.get('avg_tok_s', 0) or 0:.1f}"))
            
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
                self.model_table.setItem(row, 4, QTableWidgetItem(f"{mstats.get('avg_tok_s', 0) or 0:.1f}"))
            
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
            
            # Also refresh the merged diagnostics sections (health, perf, reconciliation)
            self.refresh_diagnostics()

        except Exception as e:
            if hasattr(self, "db_stats_label"):
                self.db_stats_label.setText(f"DB error: {e}")
            import traceback
            traceback.print_exc()

    # ARCH-ENG-250 (U-03) / ARCH-ENG-251 (U-04): the dead seconds-to-ago
    # formatter and `_run_http` (a leftover of the removed review queue) were
    # deleted here. Both had zero callers and zero tests.
    #
    # ARCH-ENG-284 (U-01): the review queue itself moved to the Safety &
    # Tools tab (`SafetyTab`), which now owns the widgets and the decision
    # handler. The old `_refresh_review_queue` / `_review_selected` read
    # `review_list` and `review_counts_label`, neither of which was ever
    # constructed; keeping a second, unwired copy here would recreate the
    # dead surface. The tab resolves this window's `instruction_gate`, so
    # there is still exactly one gate and one review queue.

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

    @staticmethod
    def _active_ollama_models() -> tuple[str, str]:
        """Return the persisted (main, chat) Ollama model names.

        ARCH-ENG-275 (AB-01): this value used to be read from the hidden
        Settings combo. `ProviderConfigWidget` writes OLLAMA_MAIN_MODEL /
        OLLAMA_CHAT_MODEL the moment the operator picks a model, so `.env` is
        the only trustworthy source of operator intent. OLLAMA_MODEL is the
        first-run fallback.
        """
        fallback = os.getenv("OLLAMA_MODEL", "").strip() or "llama3.2"
        main = os.getenv("OLLAMA_MAIN_MODEL", "").strip() or fallback
        chat = (os.getenv("OLLAMA_CHAT_MODEL", "").strip()
                or os.getenv("OLLAMA_MODEL", "").strip())
        return main, chat

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
        # ARCH-ENG-275 (AB-01): the role comes from the keys the visible
        # provider surface persists, not from the retired hidden combo.
        ollama_disabled = os.getenv("DISABLE_OLLAMA", "false").lower() == "true"
        ollama_main = (not ollama_disabled
                       and os.getenv("OLLAMA_MAIN_ENABLED", "true").lower() == "true")
        ollama_chat = (not ollama_disabled
                       and os.getenv("OLLAMA_CHAT_ENABLED", "true").lower() == "true")
        if ollama_main or ollama_chat:
            try:
                model = self._active_ollama_models()[0]
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
        # Settings can rebuild its provider rows while a queued connection test
        # is still running. The Python wrapper then outlives the Qt C++ widget.
        # Treat that stale row as disabled; the next Settings build supplies the
        # live controls and avoids dereferencing a deleted QObject.
        try:
            txt = role_combo.currentText().strip()
        except RuntimeError:
            return (False, False)
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
            from app.provider_models import _price_for, get_arch_info
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
            main_model, chat_model = self._active_ollama_models()
            
            # Also include currently-active provider/model from worker
            active_provider = getattr(self.worker, "last_provider", "N/A") if hasattr(self, "worker") else "N/A"
            
            lines = [fmt("Main", main_model), fmt("Chat", chat_model)]
            lines.append(f"<br><b>Active Provider:</b> {active_provider}")
            lines.append(f"<b>Daily Budget:</b> ${os.getenv('LLM_DAILY_BUDGET_USD', '0')} | <b>Max Tokens:</b> {os.getenv('MAX_TOKENS', '1024')} | <b>Temperature:</b> {os.getenv('LLM_TEMPERATURE', '0.7')}")
            
            self.model_info_browser.setHtml("<br>".join(lines))
        except Exception as exc:  # never break the settings UI
            self.model_info_browser.setHtml(f"<i>Model info unavailable: {exc}</i>")

    def _copy_model_info_to_clipboard(self):
        """Copy the model info text to clipboard."""
        text = self.model_info_browser.toPlainText()
        if text.strip():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.log_signal.emit("[System] Model info copied to clipboard")

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
            if env_key:
                from app.environment import clean_env_value
                return clean_env_value(os.getenv(env_key, ""))
            return ""

        def _safe_widget_checked(name, env_key=""):
            widget = getattr(self, name, None)
            try:
                if widget is not None:
                    return bool(widget.isChecked())
            except RuntimeError:
                pass
            return os.getenv(env_key, "false").lower() == "true"

        try:
            from agents.core.feature_flags import feature_env_key
            for feature_name, widget in getattr(self, "feature_flag_checks", {}).items():
                values[feature_env_key(feature_name)] = str(
                    bool(widget.isChecked())).lower()
        except RuntimeError:
            pass

        # Persist the self-improvement monitor cadence (minutes).
        try:
            spin = getattr(self, "self_improve_monitor_spin", None)
            if spin is not None:
                values["MRBOT_SELF_IMPROVE_MONITOR_MINUTES"] = str(spin.value())
        except RuntimeError:
            pass

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
        # ARCH-ENG-275 (AB-01): the Ollama model/role/hide keys are NOT written
        # here. `ProviderConfigWidget` is the only visible surface and it
        # persists the role (`_persist_provider_role`) and the model
        # (`_on_model_changed`) the moment the operator changes them. The
        # hidden combo that used to be a second writer -- the reason
        # ARCH-ENG-196 had to make the persisted value win -- is deleted.
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
        # Nous Research. Was registered by the adapter registry but never saved,
        # so DISABLE_NOUS was never written and the provider could not be turned
        # off — it was retried on every LLM call as a fallback.
        _save_provider("NOUS", getattr(self, "nous_role", None), getattr(self, "nous_model", None),
                   getattr(self, "nous_chat", None), _safe_widget_text("nous_key", "NOUS_API_KEY"),
                   _safe_widget_text("nous_base", "NOUS_BASE_URL"), hide_cb=getattr(self, "nous_hide", None))
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

        # Phase E (ARCH-ENG-087): web-discovery opt-in from the Settings tab
        # (mirrors the Opportunities-tab toggle; both write ALLOW_WEB_DISCOVERY).
        # Read defensively — the Settings tab is built lazily, so the checkbox
        # may not exist yet; fall back to the current env value so Save never
        # clobbers a choice made in the other tab.
        try:
            web_check = getattr(self, "settings_web_discovery_check", None)
            if web_check is not None:
                values["ALLOW_WEB_DISCOVERY"] = str(web_check.isChecked())
        except Exception as exc:
            record_gui_error("settings:web-discovery", exc)

        # Phase F (ARCH-ENG-091): persist per-provider rate + daily call caps.
        # Read defensively (Settings tab built lazily); only write a key the
        # operator actually set so we never clobber an env value with a blank.
        try:
            for up, edit in getattr(self, "_provider_rate_edits", {}).items():
                v = edit.text().strip()
                if v:
                    values[f"{up}_RATE_PER_SEC"] = v
            for up, edit in getattr(self, "_provider_cap_edits", {}).items():
                v = edit.text().strip()
                if v:
                    values[f"{up}_MAX_CALLS_PER_DAY"] = v
        except Exception as exc:
            record_gui_error("settings:provider-rate-caps", exc)

        # Persist payout destinations (wallet/cashApp) from the (possibly lazily-built) Settings tab
        try:
            cashapp_widget = getattr(self, "cashapp_payout_edit", None)
            if cashapp_widget is not None:
                values["CASHAPP_TAG"] = cashapp_widget.text().strip()
        except Exception as exc:
            record_gui_error("settings:cashapp-payout", exc)
        try:
            solana_widget = getattr(self, "solana_payout_edit", None)
            if solana_widget is not None:
                values["ATOMIC_SOLANA_ADDRESS"] = solana_widget.text().strip()
        except Exception as exc:
            record_gui_error("settings:solana-payout", exc)
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
        def _live_checkbox_value(name):
            """Read a lazily-built Qt checkbox without touching deleted C++ objects."""
            checkbox = getattr(self, name, None)
            if checkbox is None:
                return None
            try:
                import shiboken6
                if not shiboken6.isValid(checkbox):
                    return None
                return checkbox.isChecked()
            except (ImportError, RuntimeError):
                return None

        if os.getenv("BIG_BRAIN_PROVIDER", "llamacpp").lower() == "llamacpp":
            values["BIG_BRAIN_PROVIDER"] = "llamacpp"
            big_enabled = _live_checkbox_value("llamacpp_big_enabled")
            if big_enabled is not None:
                values["BIG_BRAIN_ENABLED"] = str(big_enabled)
        if os.getenv("SMALL_BRAIN_PROVIDER", "llamacpp").lower() == "llamacpp":
            values["SMALL_BRAIN_PROVIDER"] = "llamacpp"
            small_enabled = _live_checkbox_value("llamacpp_small_enabled")
            if small_enabled is not None:
                values["SMALL_BRAIN_ENABLED"] = str(small_enabled)

        # N-brain roster (Phase 4). The roster lives in settings.json (not .env),
        # and BOTH save handlers own that write (the two-handler rule) — this one
        # and DualBrainControl._snapshot_settings_values. Read the live panel off
        # the (lazily-built) Providers & GPU tab so a Settings Save captures the
        # operator's roster edits; with no panel the persisted roster is merged
        # back, which keeps the `roster` key present instead of letting this
        # handler's .env rewrite drop it.
        try:
            from gui.widgets.brain_roster_panel import save_roster_from
            _roster_panel = getattr(
                getattr(self, "providers_gpu_tab", None), "brain_roster_panel", None)
            save_roster_from(_roster_panel)
        except Exception as exc:
            record_gui_error("settings:brain-roster", exc)

        # ── ARCH-ENG-195: POPULATE `values` BEFORE THE SINGLE WRITE ──────────
        #
        # `set_env_values(values)` used to be called ~55 lines ABOVE this point,
        # while nine keys were inserted into `values` AFTER it. A dict passed to
        # a writer is a snapshot: those nine keys were therefore never written to
        # `.env` at all. This was the operator-visible "Save All does not fully
        # work".
        #
        # The six that were silently lost:
        #   MAX_TOKENS, LLM_TEMPERATURE, LLM_TOP_P
        #       -> not even os.environ was set, so the value died with the process
        #          and `_settings_snapshot()` never listed them, so the operator
        #          was not even prompted to restart.
        #   DIALOGUE_MAX_TOKENS_BIG / _SMALL, DIALOGUE_AUTO_TOKENS
        #       -> os.environ only, and `load_dotenv(override=True)` below
        #          immediately clobbered them back to the .env value.
        #
        # Plus nine CONTROLS the handler never read at all, so editing them did
        # nothing on any path. Several back real safety and spend controls.
        def _sval(name, default=""):
            """Read a QLineEdit/QSpinBox-ish control, tolerating absence."""
            widget = getattr(self, name, None)
            if widget is None:
                return default
            for getter in ("value", "currentText", "text"):
                fn = getattr(widget, getter, None)
                if callable(fn):
                    try:
                        return fn()
                    except Exception as exc:
                        record_gui_error(f"settings:control:{name}", exc)
                        continue
            return default

        try:
            # LLM sampling parameters (were added to `values` AFTER the write).
            values["MAX_TOKENS"] = str(_sval("max_tokens_spin"))
            values["LLM_TEMPERATURE"] = str(_sval("temperature_spin"))
            values["LLM_TOP_P"] = str(_sval("top_p_spin"))

            # Dialogue token limits + auto-scale toggle (same bug).
            values["DIALOGUE_MAX_TOKENS_BIG"] = str(
                _sval("dialogue_tokens_big_spin"))
            values["DIALOGUE_MAX_TOKENS_SMALL"] = str(
                _sval("dialogue_tokens_small_spin"))
            auto_cb = getattr(self, "dialogue_auto_tokens_cb", None)
            values["DIALOGUE_AUTO_TOKENS"] = (
                "true" if (auto_cb is not None and auto_cb.isChecked()) else "false")

            # ── ARCH-ENG-195: controls the handler never read ─────────────────
            # Each of these was shown in the Settings tab, editable, and simply
            # discarded on Save. Consumers are named so a future reader can see
            # what a regression would cost.
            values["MAX_FILE_SIZE_MB"] = str(_sval("max_file_spin"))
            values["RESEARCH_MAX_CHARS"] = str(_sval("research_max_chars"))
            values["DEEP_READ_MAX_CHARS"] = str(_sval("deep_read_chars"))
            values["FILENAME_BLOCKLIST"] = str(_sval("blocklist_edit"))
            values["BLOCKED_MIME_TYPES"] = str(_sval("blocked_mime_edit"))
            values["LLM_DAILY_BUDGET_USD"] = str(_sval("llm_budget_edit"))
            values["WINRATE_DECLINE_BELOW"] = str(_sval("winrate_edit"))
            # Provider base URLs: `_save_provider` is called WITHOUT `base=`
            # further down, so its `if base != ""` guard skipped them entirely.
            values["OPENAI_BASE_URL"] = str(_sval("openai_base_edit")).strip()
            values["ANTHROPIC_BASE_URL"] = str(
                _sval("anthropic_base_edit")).strip()
        except Exception as exc:
            # Never let one malformed control abort the whole save. Record it so
            # the operator is not left believing everything persisted.
            self.log_signal.emit(f"[Settings] some values not saved: {exc}")

        # Publish the dialogue keys to the environment as well. This must happen
        # BEFORE `load_dotenv(override=True)` below, which would otherwise restore
        # the stale .env values over them.
        for _k in ("DIALOGUE_MAX_TOKENS_BIG", "DIALOGUE_MAX_TOKENS_SMALL",
                   "DIALOGUE_AUTO_TOKENS"):
            try:
                os.environ[_k] = values[_k]
            except Exception as exc:
                record_gui_error(f"settings:env-publish:{_k}", exc)

        # v2.0.34aj: single lock-resilient atomic write (replaces ~40 set_key calls
        # that each spawned a .tmp_* temp vulnerable to WinError 32/5 lock races).
        set_env_values(values)

        # Reload env so newly saved keys are visible to os.getenv() in this process
        try:
            load_dotenv(override=True)
        except Exception as exc:
            record_gui_error("settings:dotenv-reload", exc)

        # ── Live model switch (no restart required) ──────────────────────────
        new_main, new_chat = self._active_ollama_models()
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
                    except Exception as exc:
                        record_gui_error(f"settings:unload-model:{old}", exc)
                for old in (old_chat, old_main):
                    if old:
                        threading.Thread(target=_unload, args=(old,), daemon=True).start()
        if new_chat and new_chat != old_chat:
            self.worker._chat_ollama_model_override = new_chat
            self.log_signal.emit(f"[Ollama] chat model now live: {new_chat}")
        if new_main and new_main != old_main:
            self.worker._ollama_model_override = new_main
            self.log_signal.emit(f"[Ollama] main model now live: {new_main}")
        # Make cloud/local provider model changes live without a restart: rebuild
        # the cached provider registry from the just-written .env on next llm() call.
        for obj in (self.worker,):
            if hasattr(obj, "invalidate_provider_registry"):
                obj.invalidate_provider_registry()
        self.log_signal.emit("[Models] provider registry refreshed — changes apply on next call (no restart)")

        # Update live objects
        self.worker.max_file_size = self.max_file_spin.value() * 1024 * 1024
        # (legacy manager HEARTBEAT_INTERVAL / research-cache-ttl / idle-cooldown removed)
        #
        # ARCH-ENG-195: the `values[...]` assignments that used to live here were
        # removed. They ran AFTER `set_env_values(values)`, so they mutated a dict
        # nobody read again -- the settings silently never reached `.env`. They
        # now happen once, before the single write, above. What remains here is
        # only the LIVE application, which must stay after the reload so it wins.
        try:
            self.worker._max_tokens = int(self.max_tokens_spin.value())
            self.worker._temperature = float(self.temperature_spin.value())
            self.worker._top_p = float(self.top_p_spin.value())
        except Exception as exc:
            record_gui_error("settings:apply-sampling", exc)
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
        # ARCH-ENG-070: this used to write `settings = {"providers": providers}` with a
        # bare whole-file open(...,"w"), which DESTROYED the entire `devices` block
        # that `device_registry.save_policy` maintains — every per-device model,
        # every llama.cpp setting, every device-disable, on a single Save click.
        # Merge instead, so sibling keys survive.
        try:
            from agents.runtime.device_registry import merge_settings_file
            merge_settings_file({"providers": providers})
        except Exception as e:
            self.log_signal.emit(f"[Settings] provider list merge failed: {e}")

    def _settings_snapshot(self) -> dict:
        """Capture provider-relevant env values for restart-diffing."""
        keys = [
            "MRBOT_ENABLE_LIVE_TRADING", "MRBOT_ENABLE_CRYPTO",
            "MRBOT_ENABLE_AIRDROPS", "MRBOT_ENABLE_DEFI",
            "MRBOT_ENABLE_SOCIAL_AUTOMATION", "MRBOT_ENABLE_SELF_IMPROVEMENT",
            "MRBOT_ENABLE_AUTONOMOUS_LEARNING",
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
            # must NOT trigger a restart prompt.
            if k.endswith("_MODEL"):
                continue
            # Enable/disable and per-role enable toggles are also live: the provider
            # gate reads DISABLE_<PREFIX>/<PREFIX>_ENABLED from env at call time
            # (base_worker.py:513) and the Settings save invalidates the provider
            # registry, so a toggled provider is excluded on the next llm() call. A
            # restart prompt here was a false positive that asked the user to relaunch
            # just to disable a cloud provider.
            if k.startswith("DISABLE_") or k.endswith("_ENABLED"):
                continue
            # Only key/base-url changes still require a restart (a built adapter holds
            # its key/base_url; the conservative default is to relaunch).
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

    def _on_pipeline_executed(self, action, result):
        status = "✓" if result.success else "✗"
        self.log_signal.emit(
            f"[Pipeline] {status} EXECUTED {action.action_type} "
            f"by {action.proposer}: {result.message}")

    def _on_pipeline_rejected(self, action, reason):
        self.log_signal.emit(
            f"[Pipeline] REJECTED {action.action_type} "
            f"by {action.proposer}: {reason}")

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
        # v2.0.27: push the resolved theme to the widget-style token store so
        # chat/HTML colors follow it.
        #
        # ARCH-ENG-192: this was `from app import ui`. That module lived in the
        # SERVICE layer and imported 39 PySide6 names at module level -- all of
        # them unused -- which broke the documented rule that `app/` is Qt-free so
        # it can be imported headless. It declared no classes and instantiated no
        # widgets, so it was misfiled rather than architecturally leaking, and it
        # now lives at `gui/theme_ui_state.py` with no Qt import at all.
        try:
            from gui import theme_ui_state
            theme_ui_state.set_ui_theme(theme)
            # ARCH-ENG-192: the old comment here claimed "Animations toggle now
            # actually gates ui particle/gear FX". It does not, and has not since
            # the flag was introduced: `UI_ANIMATIONS` has no readers anywhere in
            # the repository. The toggle DOES reach the renderer, but through
            # `fx` / `app.effects.EffectSettings.animations`, applied above via
            # `_apply_shadow_effects`. Kept for API compatibility; the false
            # claim is what was removed.
            theme_ui_state.set_effects(animations=bool(fx.animations))
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

            from app.effects import apply_shadow
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

            from app.theme_config import resolve_theme_definition, save_custom_theme
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
            from app.theme_config import save_custom_theme
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
            from app.effects import EffectSettings
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
        from app.effects import EffectSettings, apply_antialiasing, style_hints_qss
        if fx_override is not None:
            return fx_override.effective(), style_hints_qss, apply_antialiasing
        return EffectSettings.from_env().effective(), style_hints_qss, apply_antialiasing


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
        # PySide6/Qt6: an unhandled Python exception inside a Qt slot calls
        # qFatal -> abort() directly, which BYPASSES the outer try/except below
        # (that only catches exceptions that propagate out of app.exec()). So a
        # slot exception used to die silently with no traceback anywhere. Install
        # a sys.excepthook so every uncaught exception is written to a crash log
        # before the process aborts — turning silent CTDs into diagnosable ones.
        _python_crash_log = Path(tempfile.gettempdir()) / "mrbot-python-crash.log"
        def _excepthook(exc_type, exc_value, exc_tb):
            import traceback as _tb
            _text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
            try:
                with open(_python_crash_log, "a", encoding="utf-8", errors="replace") as _f:
                    _f.write(f"\n[{datetime.now().isoformat()}] UNHANDLED EXCEPTION\n{_text}")
            except Exception:
                pass
            try:
                _crash_dir = Path.home() / ".local" / "share" / "mrbot1000"
                _crash_dir.mkdir(parents=True, exist_ok=True)
                with open(_crash_dir / "crash.log", "a", encoding="utf-8") as _f:
                    _f.write(f"\n[{datetime.now().isoformat()}] UNHANDLED EXCEPTION\n{_text}")
            except Exception:
                pass
            _tb.print_exception(exc_type, exc_value, exc_tb)
        sys.excepthook = _excepthook
        # ARCH-ENG-293 (P-01): startup_validation.py was protected, shipped,
        # and never called. Run it once before the window exists so its
        # warnings/errors are visible in the console and retained on the
        # window for diagnostics, instead of being dead code.
        from app.startup_validation import validate_startup_environment
        _startup_report = validate_startup_environment(
            log_fn=lambda msg: print(f"[startup] {msg}", flush=True))
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = MainWindow()
        window.startup_validation_report = _startup_report
        if _startup_report.status == "error":
            print("[startup] validation reported errors; starting in degraded mode",
                  flush=True)
        window.show()
        from agents.runtime.performance import telemetry
        telemetry.mark_startup_complete()
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