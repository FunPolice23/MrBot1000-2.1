"""ARCH-ENG-263..270 — the low-tier findings that needed behaviour, not deletion.

Each class pins one finding from the 11B-11X depth sweeps:

  263 AU-01 / AX-03  skill matching used substrings ("ai" in "email")
  264 AI-01          POSIX shell-escaping applied to an argv list
  265 AM-02          approval-log writes were truncate-in-place and silent
  266 AP-01          discovery observability was 15 bare print() calls
  267 AR-01          the CLI docstring named a module path that does not exist
  268 AA-01          handler capability convention (with its one exception)
  269 AZ-01          "approved but not routed" was invisible
  270 X-01           the chat-template fallback decision was silent
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.AST:
    return ast.parse(_read(rel))


def _function(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ── ARCH-ENG-263 (AU-01 / AX-03) — word-boundary skill matching -------------

class TestSkillMatchingUsesWordBoundaries(unittest.TestCase):
    """AU-01: `"ai" in "email"` credited a skill the posting never named."""

    def setUp(self):
        from agents.earning.freelance_finder import FreelanceFinder
        self.extract = FreelanceFinder._extract_skills

    def test_a_short_token_does_not_fire_inside_a_word(self):
        self.assertEqual(
            self.extract("Maintain the email campaign and the domain registry"),
            [],
            "'ai' / 'sql' / 'ios' must not fire inside email/domain/opinions")

    def test_the_real_token_still_fires(self):
        self.assertIn("ai", self.extract("We need AI automation"))

    def test_a_phrase_entry_still_matches_as_a_phrase(self):
        self.assertIn("data analysis", self.extract("Data analysis for a client"))

    def test_node_still_matches_the_dotted_form(self):
        self.assertIn("node", self.extract("Build a Node.js service"))

    def test_the_heuristic_evaluator_uses_the_same_contract(self):
        """AX-03: the fallback path repeated the substring bug."""
        from agents.earning import evaluation

        def _stub_opportunity():
            return SimpleNamespace(
                id="opp-1", title="Maintain the email metadata",
                description="domain registry upkeep", source="api",
                platform="test", payment_amount=10, payment_currency="USD",
                min_amount=10, type="gig", skill_match=0.0, effort_score=0.0,
                risk_level="", urgency=0.0, status="new",
            )

        memory = SimpleNamespace(get_opportunity_history=lambda _id: None)
        logs = []
        with patch("httpx.post", side_effect=OSError("no model")):
            opportunity = evaluation.evaluate_opportunity(
                _stub_opportunity(), memory=memory, log_fn=logs.append,
                normalize_keep_alive=lambda value: value)
        # No listed skill is actually present: base 0.2, zero matches.
        self.assertEqual(opportunity.skill_match, 0.2)

        with patch("httpx.post", side_effect=OSError("no model")):
            opportunity = evaluation.evaluate_opportunity(
                _stub_opportunity(), memory=memory, log_fn=logs.append,
                normalize_keep_alive=lambda value: value)
        self.assertTrue(logs, "the fallback path must say why it was used")


# ── ARCH-ENG-264 (AI-01) — no shell escaping on an argv list ----------------

class TestLeadRoutinePassesThePromptUnchanged(unittest.TestCase):
    """AI-01: argv is not a shell; escaping only corrupted the prompt."""

    def setUp(self):
        self.tree = _tree("run_lead_routine.py")

    def test_the_prompt_is_not_shell_escaped(self):
        src = _read("run_lead_routine.py")
        self.assertNotIn("escaped_prompt", src)

    def test_the_command_list_carries_the_raw_prompt(self):
        cmds = [n for n in ast.walk(self.tree)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "cmd"
                        for t in n.targets)
                and isinstance(n.value, ast.List)]
        self.assertTrue(cmds, "the hermes command list is gone")
        values = [ast.literal_eval(el) if isinstance(el, ast.Constant) else None
                  for el in cmds[-1].value.elts]
        self.assertIn("-q", values)
        prompt_element = cmds[-1].value.elts[values.index("-q") + 1]
        self.assertIsInstance(prompt_element, ast.Name)
        self.assertEqual(prompt_element.id, "prompt",
                         "the -q argument must be the unmodified prompt")


# ── ARCH-ENG-265 (AM-02) — atomic, announced approval-log persistence ------

class TestApprovalLogPersistenceIsAtomicAndAnnounced(unittest.TestCase):
    """AM-02: truncate-in-place + `except Exception: pass` is not best-effort."""

    def setUp(self):
        from agents.safety.approval import HumanApprovalQueue
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "approvals.json")
        self.queue = object.__new__(HumanApprovalQueue)
        self.queue._log_path = self.path
        self.queue._items = []
        self.queue._decided_in_process = set()
        self.queue._restored_decided = set()

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_log_is_replaced_not_truncated(self):
        with patch("agents.safety.approval.os.replace",
                   wraps=os.replace) as replace:
            self.queue._maybe_persist()
        self.assertTrue(replace.called, "the log was written in place")
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])

    def test_a_failed_write_is_reported_not_swallowed(self):
        with patch("agents.safety.approval.os.replace",
                   side_effect=OSError("read-only filesystem")):
            with self.assertLogs("agents.safety.approval", level="WARNING") as logs:
                self.queue._maybe_persist()
        self.assertTrue(
            any("persistence failed" in line.lower() for line in logs.output),
            f"the failure was invisible: {logs.output}")
        self.assertTrue(
            any("in memory only" in line for line in logs.output),
            "the operator must be told the decisions will not survive a restart")


# ── ARCH-ENG-266 (AP-01) — discovery reports through logging ----------------

class TestDiscoveryObservabilityIsNotPrint(unittest.TestCase):
    """AP-01: 15 bare print() calls and no logging/notification import."""

    def test_the_module_has_no_print_calls(self):
        tree = _tree("agents/earning/discoverer.py")
        prints = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            prints.extend(
                call.lineno for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "print")
        self.assertEqual(prints, [], f"discovery still prints at lines {prints}")

    def test_counts_go_through_the_logger(self):
        src = _read("agents/earning/discoverer.py")
        self.assertIn("logger.info", src)
        self.assertIn("logger.warning", src)

    def test_the_off_opt_in_is_announced_once(self):
        from agents.earning import discoverer

        announced = []
        fake = SimpleNamespace(
            info=lambda title, message: announced.append((title, message)),
            warning=lambda title, message: announced.append((title, message)),
        )
        discoverer._ANNOUNCED_OPT_IN.clear()
        with patch("agents.core.notifications.NotificationService.instance",
                   return_value=fake):
            discoverer._announce_opt_in("Referral", "ALLOW_REFERRAL_DISCOVERY")
            discoverer._announce_opt_in("Referral", "ALLOW_REFERRAL_DISCOVERY")
        self.assertEqual(len(announced), 1,
                         "the operator is told once, not once per scan")
        title, message = announced[0]
        self.assertIn("Reference", title.replace("Referral", "Reference"))
        self.assertIn("ALLOW_REFERRAL_DISCOVERY", message)

    def test_a_notification_failure_never_breaks_discovery(self):
        from agents.earning import discoverer

        discoverer._ANNOUNCED_OPT_IN.clear()
        with patch("agents.core.notifications.NotificationService.instance",
                   side_effect=RuntimeError("no GUI")):
            discoverer._announce_opt_in("Faucet", "ALLOW_FAUCET_DISCOVERY")


# ── ARCH-ENG-267 (AR-01) — the documented invocations actually work --------

class TestCliDocstringNamesTheRealModule(unittest.TestCase):
    """AR-01: `python -m agents.mrbot_cli` raised ModuleNotFoundError."""

    def setUp(self):
        self.src = _read("agents/services/mrbot_cli.py")
        self.tree = ast.parse(self.src)
        self.doc = ast.get_docstring(self.tree) or ""

    def test_every_documented_invocation_uses_the_services_path(self):
        for line in self.doc.splitlines():
            if line.strip().startswith("#"):
                continue  # the comment explains the OLD, broken form
            if "python -m" in line:
                with self.subTest(line=line.strip()):
                    self.assertIn("python -m agents.services.mrbot_cli", line)
                    self.assertNotIn("python -m agents.mrbot_cli", line)

    def test_every_documented_subcommand_exists(self):
        from agents.services import mrbot_cli
        for line in self.doc.splitlines():
            if line.strip().startswith("#"):
                continue
            if "python -m agents.services.mrbot_cli" not in line:
                continue
            words = line.split()
            index = words.index("agents.services.mrbot_cli")
            if index + 1 >= len(words):
                continue
            command = words[index + 1]
            if command.startswith("#") or command.startswith("-"):
                continue
            with self.subTest(command=command):
                self.assertIn(command, mrbot_cli.SUBCOMMANDS)

    def test_the_module_is_importable_as_documented(self):
        import importlib
        self.assertTrue(importlib.import_module("agents.services.mrbot_cli"))


# ── ARCH-ENG-268 (AA-01) — capability convention on the handler surface ----

class TestHandlerCapabilityConvention(unittest.TestCase):
    """AA-01: mutating handlers declare the dispatch capability; read-only
    handlers must not, and `propose_code_patch` is the single documented
    exception (it routes through CodePatchService, which owns approval)."""

    EXCEPTION = "propose_code_patch"

    def setUp(self):
        from agents.safety import gate
        self.mutating = set(gate.MUTATING_TOOL_NAMES)
        self.readonly = set(gate.READONLY_TOOL_NAMES)
        self.tree = _tree("agents/safety/handlers.py")

    def _handlers(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_tool_"):
                yield node.name[len("_tool_"):], node

    def test_every_handler_is_classified(self):
        for tool, _ in self._handlers():
            with self.subTest(tool=tool):
                self.assertIn(tool, self.mutating | self.readonly,
                              f"{tool} is dispatched but absent from the gate")

    def test_mutating_handlers_declare_authorization(self):
        for tool, node in self._handlers():
            if tool not in self.mutating or tool == self.EXCEPTION:
                continue
            with self.subTest(tool=tool):
                kwonly = {arg.arg for arg in node.args.kwonlyargs}
                self.assertIn(
                    "authorization", kwonly,
                    f"{tool} mutates without the dispatch capability; the "
                    f"shared dispatcher can be bypassed")
                src = ast.get_source_segment(_read("agents/safety/handlers.py"),
                                             node) or ""
                self.assertIn("_require_mutation_capability", src)

    def test_read_only_handlers_do_not_demand_a_capability(self):
        for tool, node in self._handlers():
            if tool not in self.readonly:
                continue
            with self.subTest(tool=tool):
                self.assertNotIn(
                    "authorization", {arg.arg for arg in node.args.kwonlyargs},
                    f"{tool} is READONLY; requiring a capability it never "
                    f"receives would refuse every call")

    def test_the_patch_tool_keeps_its_documented_exception(self):
        node = _function(self.tree, "_tool_" + self.EXCEPTION)
        self.assertIsNotNone(node)
        self.assertNotIn("authorization",
                         {arg.arg for arg in node.args.kwonlyargs},
                         "ARCH-ENG-227's tool owns its approval path; adding "
                         "the gate kwarg here would double-gate it")


# ── ARCH-ENG-269 (AZ-01) — an approved decision is never silently lost -----

class TestUnroutedApprovalsAreVisible(unittest.TestCase):
    """AZ-01: both failure paths of `_route_decision` returned without a trace."""

    def test_report_unrouted_logs_and_notifies(self):
        from gui.tabs.safety_tools_tab import SafetyTab

        notices = []
        fake = SimpleNamespace(
            warning=lambda title, message: notices.append((title, message)))
        stub = SimpleNamespace()
        with patch("agents.core.notifications.NotificationService.instance",
                   return_value=fake):
            with self.assertLogs("gui.tabs.safety_tools_tab",
                                 level="WARNING") as logs:
                SafetyTab._report_unrouted(stub, "req-9", "routing raised: boom")
        self.assertTrue(any("recorded but not routed" in line
                            for line in logs.output))
        self.assertEqual(len(notices), 1)
        self.assertIn("req-9", notices[0][1])
        self.assertIn("routing raised: boom", notices[0][1])

    def test_both_failure_paths_call_it(self):
        tree = _tree("gui/tabs/safety_tools_tab.py")
        fn = _function(tree, "_route_decision")
        self.assertIsNotNone(fn)
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_report_unrouted"]
        self.assertGreaterEqual(
            len(calls), 3,
            "no-handler, not-approved and routing-exception must all report")


# ── ARCH-ENG-270 (X-01) — the template fallback is logged when it happens ---

class TestTemplateFallbackIsLogged(unittest.TestCase):
    """X-01: `get_template_info` reported the decision; nobody called it."""

    def _config(self):
        from agents.runtime.dual_brain import BrainConfig, BrainRole
        return BrainConfig(role=BrainRole.BIG, model="qwen-test.gguf")

    def test_the_dead_reporter_is_gone(self):
        tree = _tree("agents/runtime/dual_brain.py")
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn("get_template_info", names)

    def test_a_raise_exception_template_is_left_to_the_jinja_engine(self):
        """ARCH-ENG-311: by default NO substitution and no --chat-template flag.

        Modern llama.cpp runs the model's own embedded template through its
        Jinja (minja) engine, which implements raise_exception(). Substituting
        a bare builtin (e.g. chatml for a Qwen3.5) drops the embedded
        template's tool-call rendering the Dialogue tab depends on."""
        config = self._config()
        with patch.object(type(config), "_model_needs_raise_exception",
                          return_value=True):
            with self.assertLogs("agents.runtime.dual_brain", level="INFO") as logs:
                command = config.build_llama_command()
        self.assertNotIn("--chat-template", command,
                         "the legacy substitution ran without the opt-in")
        self.assertTrue(any("raise_exception" in line.lower()
                            for line in logs.output))
        self.assertTrue(any("jinja" in line.lower()
                            for line in logs.output))

    def test_the_legacy_opt_in_still_substitutes(self):
        """MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK=1 restores the old behaviour."""
        config = self._config()
        env = patch.dict(os.environ,
                         {"MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK": "1"})
        with env, \
                patch.object(type(config), "_model_needs_raise_exception",
                             return_value=True), \
                patch.object(type(config), "_get_fallback_template",
                             return_value="<fallback-template>"):
            with self.assertLogs("agents.runtime.dual_brain", level="INFO") as logs:
                command = config.build_llama_command()
        self.assertIn("--chat-template", command)
        self.assertIn("<fallback-template>", command)
        self.assertTrue(any("fallback template" in line.lower()
                            for line in logs.output))

    def test_a_missing_legacy_fallback_warns_instead_of_failing_silently(self):
        config = self._config()
        env = patch.dict(os.environ,
                         {"MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK": "1"})
        with env, \
                patch.object(type(config), "_model_needs_raise_exception",
                             return_value=True), \
                patch.object(type(config), "_get_fallback_template",
                             return_value=None):
            with self.assertLogs("agents.runtime.dual_brain", level="WARNING") as logs:
                command = config.build_llama_command()
        self.assertNotIn("--chat-template", command)
        self.assertTrue(any("fallback template" in line.lower()
                            for line in logs.output))

    def test_a_clean_template_adds_no_flag_and_no_warning(self):
        config = self._config()
        with patch.object(type(config), "_model_needs_raise_exception",
                          return_value=False):
            command = config.build_llama_command()
        self.assertNotIn("--chat-template", command)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
