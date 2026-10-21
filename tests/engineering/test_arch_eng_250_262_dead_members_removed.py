"""ARCH-ENG-250..259, 262 — the low-tier dead members are gone, not parked.

The depth sweep's low tier was dominated by one class of defect: methods that
nothing calls. Keeping them is not neutral -- they are read as supported
surface, they drift from the live twin (BE-02 was a *less tolerant* copy of the
live extractor), and they make every future reader re-do the reachability
analysis.

Each test asserts two things:
  * the name is absent from the module's AST, and
  * no production module still references it as an identifier.

The second half matters: deleting a definition while a caller survives turns
dead code into a runtime AttributeError, which the first half alone would miss.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _tree(rel: str) -> ast.AST:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _defined_names(rel: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(_tree(rel))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _identifier_uses(rel: str) -> set[str]:
    """Names and attribute names actually used in code (not comments/strings)."""
    used: set[str] = set()
    for node in ast.walk(_tree(rel)):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    return used


# id -> (module, member, one-line reason)
REMOVED = {
    "ARCH-ENG-250 / U-03": ("main.py", "_format_ago",
                 "seconds-to-'5h 3m ago' formatter with no caller"),
    "ARCH-ENG-251 / U-04": ("main.py", "_run_http",
                 "leftover of the removed review-queue feature"),
    "ARCH-ENG-252 / V-01": ("gui/workers/provider_lifecycle_backend.py", "_on_temp_preset",
                 "six-entry temperature table with no UI"),
    "ARCH-ENG-253 / V-02": ("gui/workers/provider_lifecycle_backend.py", "_get_llama_model",
                 "best-effort model probe with no caller"),
    "ARCH-ENG-254 / W-04a": ("app/earning_pipeline.py", "get_opportunity_stats",
                  "unused stats accessor"),
    "ARCH-ENG-254 / W-04b": ("app/earning_pipeline.py", "_db_execute",
                  "unused private DB shim"),
    "ARCH-ENG-254 / W-04c": ("app/earning_pipeline.py", "load_memory",
                  "unused memory loader"),
    "ARCH-ENG-254 / W-04d": ("app/earning_pipeline.py", "build_workflow_plan",
                  "unused workflow-plan shim"),
    "ARCH-ENG-254 / W-04e": ("app/earning_pipeline.py", "_legacy_to_canonical",
                  "unused legacy-name converter"),
    "ARCH-ENG-254 / W-04f": ("app/earning_pipeline.py", "get_platform_reputations",
                  "unused reputation accessor"),
    "ARCH-ENG-255 / Y-02": ("agents/services/autonomous_loop.py", "_get_opp_from_facts",
                 "last method in the file, zero references"),
    "ARCH-ENG-256 / Z-03": ("agents/earning/opportunity_lifecycle.py", "get_top_opportunities",
                 "one reference: its own definition"),
    "ARCH-ENG-257 / AE-01a": ("agents/safety/guard.py", "add_to_denylist",
                   "runtime deny-list mutator with no caller"),
    "ARCH-ENG-257 / AE-01b": ("agents/safety/guard.py", "add_to_allowlist",
                   "runtime allow-list mutator with no caller"),
    "ARCH-ENG-257 / AE-01c": ("agents/safety/guard.py", "remove_from_denylist",
                   "runtime deny-list mutator with no caller"),
    "ARCH-ENG-257 / AE-01d": ("agents/safety/guard.py", "remove_from_allowlist",
                   "runtime allow-list mutator with no caller"),
    "ARCH-ENG-258 / AE-03": ("agents/safety/guard.py", "set_approval_callback",
                  "superseded by the shared HumanApprovalQueue"),
    "ARCH-ENG-259 / AE-04a": ("agents/safety/guard.py", "check_and_raise",
                   "raising wrapper with no caller"),
    "ARCH-ENG-259 / AE-04b": ("agents/safety/guard.py", "get_remaining",
                   "quota query with no caller"),
    "ARCH-ENG-262 / BE-02": ("agents/providers/model_profile.py",
                  "extract_thinking_from_content",
                  "superseded, less tolerant copy of the live extractor"),
}


class TestDeadMembersAreRemoved(unittest.TestCase):
    """ARCH-ENG-250..259, 262 — the definitions are gone."""

    def test_each_member_is_absent_from_its_module(self):
        for label, (rel, member, reason) in REMOVED.items():
            with self.subTest(finding=label, member=member):
                self.assertNotIn(
                    member, _defined_names(rel),
                    f"{label}: {member} is still defined in {rel} ({reason})")

    def test_no_production_module_uses_a_removed_member(self):
        production = [
            path for path in REPO.rglob("*.py")
            if "tests" not in path.parts
            and ".mrbot_backups" not in path.parts
            and "__pycache__" not in path.parts
        ]
        removed_names = {member for _, member, _ in REMOVED.values()}
        for path in production:
            rel = path.relative_to(REPO).as_posix()
            with self.subTest(module=rel):
                dangling = removed_names & _identifier_uses(rel)
                self.assertEqual(
                    dangling, set(),
                    f"{rel} still calls removed member(s): {sorted(dangling)}")


class TestSupersededCopyStaysSuperseded(unittest.TestCase):
    """ARCH-ENG-262 (BE-02) — the comment no longer claims a delegation."""

    def test_response_documents_the_inlined_stripper(self):
        src = (REPO / "agents/safety/response.py").read_text(encoding="utf-8")
        self.assertIn("ARCH-ENG-262", src)
        self.assertIn("inlined here on purpose", src,
                      "the docstring still implies it delegates to model_profile")

    def test_model_profile_no_longer_offers_the_copy(self):
        tree = _tree("agents/providers/model_profile.py")
        defined = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertNotIn("extract_thinking_from_content", defined)
        # The live implementation is still reachable where it is used.
        response = _tree("agents/safety/response.py")
        self.assertIn("_visible_response_content",
                      {n.name for n in ast.walk(response)
                       if isinstance(n, ast.FunctionDef)})


class TestTheLivingTwinStillWorks(unittest.TestCase):
    """Deleting a dead copy must not disturb the code that replaced it."""

    def test_the_visible_content_stripper_still_strips(self):
        from agents.safety.response import _visible_response_content

        message = type("M", (), {
            "content": "<|channel>thought plan<channel|>answer",
            "reasoning_content": None,
        })()
        visible = _visible_response_content(
            message, {"thinking": "channel_thought"})
        self.assertEqual(visible, "answer")

    def test_a_plain_message_is_returned_unchanged(self):
        from agents.safety.response import _visible_response_content

        message = type("M", (), {"content": "hello", "reasoning_content": None})()
        self.assertEqual(_visible_response_content(message), "hello")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
