"""ARCH-ENG-248 / 11G's AY-01 -- the workshop's typed read/write surface is
WIRED, not deleted.

The finding (11G)
-----------------
`workshop.py` could create structured documents (proposal, research, script,
application, deliverable, note, account, payment) but a persona could not
read any of them back through the same contract. Twelve typed methods were
dead: `get_proposal`, `list_proposals`, `update_proposal_status`,
`get_account`, `remove_account`, `read_research`, `list_research`,
`read_script`, `list_scripts`, `list_applications`, `list_deliverables`,
`list_notes` -- and five typed WRITERS (`add_research`, `create_script`,
`create_application`, `add_deliverable`, `add_note`) were never exposed
either. The generic `workshop_list` / `workshop_read` tools could reach the
files, but the typed contract -- status transitions, structured listings, a
safe account view -- did not exist.

Operator disposition: wire the FULL typed surface (not delete, not the
generic-only compromise).

What this pins
--------------
1. Every AY-01 method is reachable from a dispatched tool (source scan of
   the handler layer + the dispatch table).
2. Every new schema is classified in the SafetyGate: reads ALLOWED,
   mutations NEED_APPROVAL (the registry-alignment contract).
3. Behavior through the TOOL layer against a temp workshop root:
   create -> list -> read -> re-status a proposal; research / script /
   application / deliverable / note round trips; account and payment
   enumeration with passwords masked (ARCH-ENG-134's boundary: the raw
   store is a refused secret file, so a typed reader must not hand the
   model what `workshop_read` refuses).
4. `workshop_account` / `workshop_payment` were dispatched and gated but
   absent from the model-facing registry -- now declared.

Vacuity: against the pre-fix sources the schema scan, the dispatch scan and
every behavioral call fail (no such tools, no such handlers).
"""

import json
import pathlib
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "agents" / "safety" / "handlers.py"
DISPATCH = REPO / "agents" / "safety" / "dispatch.py"

READ_TOOLS = {
    "workshop_proposal_list": "list_proposals",
    "workshop_proposal_get": "get_proposal",
    "workshop_research_read": "read_research",
    "workshop_research_list": "list_research",
    "workshop_script_read": "read_script",
    "workshop_script_list": "list_scripts",
    "workshop_application_list": "list_applications",
    "workshop_account_get": "get_account",
    "workshop_account_list": "list_accounts",
    "workshop_payment_get": "get_payment_method",
    "workshop_payment_list": "list_payment_methods",
    "workshop_deliverable_list": "list_deliverables",
    "workshop_note_list": "list_notes",
}

WRITE_TOOLS = {
    "workshop_proposal_status": "update_proposal_status",
    "workshop_research": "add_research",
    "workshop_script": "create_script",
    "workshop_application": "create_application",
    "workshop_account_remove": "remove_account",
    "workshop_deliverable": "add_deliverable",
    "workshop_note": "add_note",
}


class TheSurfaceIsReachable(unittest.TestCase):

    def test_every_ay01_method_has_a_handler(self):
        src = HANDLERS.read_text(encoding="utf-8")
        missing = [m for m in list(READ_TOOLS.values()) + list(WRITE_TOOLS.values())
                   if f".{m}(" not in src]
        self.assertEqual(missing, [],
                         f"AY-01 methods with no tool call: {missing}")

    def test_every_tool_is_dispatched_and_declared(self):
        from agents.safety.dispatch import execute_tool  # noqa: F401
        dispatch_src = DISPATCH.read_text(encoding="utf-8")
        from agents.safety.tools import get_all_tools
        declared = {t["function"]["name"] for t in get_all_tools()}
        for name in list(READ_TOOLS) + list(WRITE_TOOLS):
            with self.subTest(tool=name):
                self.assertIn(f'"{name}"', dispatch_src)
                self.assertIn(name, declared)

    def test_the_gate_classifies_the_surface(self):
        from agents.safety.gate import (
            MUTATING_TOOL_NAMES, READONLY_TOOL_NAMES, SafetyDecision, SafetyGate,
        )
        gate = SafetyGate()
        for name in READ_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, READONLY_TOOL_NAMES)
                allowed, _r, decision = gate.check(name, {})
                self.assertTrue(allowed)
                self.assertEqual(decision, SafetyDecision.ALLOWED)
        for name in WRITE_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, MUTATING_TOOL_NAMES)
                allowed, _r, decision = gate.check(name, {})
                self.assertFalse(allowed)
                self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL)

    def test_the_old_typed_writers_are_visible_to_models(self):
        """`workshop_account`/`workshop_payment` were dispatchable and gated
        but missing from the schema registry, so no model could call them."""
        from agents.safety.tools import get_all_tools
        declared = {t["function"]["name"] for t in get_all_tools()}
        for name in ("workshop_account", "workshop_payment"):
            self.assertIn(name, declared)


class TheTypedRoundTripsWork(unittest.TestCase):
    """Behavior through the tool layer against a temp workshop root."""

    def setUp(self):
        from agents.knowledge.workshop import Workshop
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workshop(root=self.tmp.name, max_bytes=10 ** 7)
        self.patch = mock.patch(
            "agents.knowledge.workshop.get_workshop", return_value=self.ws)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    # ── proposal lifecycle ──────────────────────────────────────────────
    def test_proposal_create_list_read_status(self):
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import (
            _tool_workshop_proposal, _tool_workshop_proposal_get,
            _tool_workshop_proposal_list, _tool_workshop_proposal_status,
        )
        created = _tool_workshop_proposal(
            {"title": "Acme Site", "client": "Acme", "description": "Build it"},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("Proposal created", created)
        filename = created.split("Proposal created: ", 1)[1].rstrip("]").replace(
            "proposals" + __import__("os").sep, "")

        listed = json.loads(_tool_workshop_proposal_list({}))
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], filename)

        body = _tool_workshop_proposal_get({"filename": filename})
        self.assertIn("Proposal: Acme Site", body)

        status = _tool_workshop_proposal_status(
            {"filename": filename, "status": "Sent"},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("Proposal status", status)
        updated = self.ws.get_proposal(filename)
        self.assertIn("## Status\n- Sent", updated)

    def test_mutating_typed_writers_require_the_dispatch_capability(self):
        from agents.safety.handlers import (
            _tool_workshop_note, _tool_workshop_proposal_status,
        )
        blocked = _tool_workshop_note({"title": "t", "content": "c"})
        self.assertIn("Authorization required", blocked)
        blocked = _tool_workshop_proposal_status(
            {"filename": "x.md", "status": "Sent"})
        self.assertIn("Authorization required", blocked)

    def test_research_script_application_deliverable_note(self):
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import (
            _tool_workshop_application, _tool_workshop_application_list,
            _tool_workshop_deliverable, _tool_workshop_deliverable_list,
            _tool_workshop_note, _tool_workshop_note_list,
            _tool_workshop_research, _tool_workshop_research_list,
            _tool_workshop_research_read, _tool_workshop_script,
            _tool_workshop_script_list, _tool_workshop_script_read,
        )
        r = _tool_workshop_research(
            {"title": "Rates", "content": "Upwork median $55/hr", "tags": ["pricing"]},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("Research note created", r)
        research_name = json.loads(_tool_workshop_research_list({}))[0]["name"]
        self.assertIn("$55/hr",
                      _tool_workshop_research_read({"filename": research_name}))

        s = _tool_workshop_script(
            {"name": "Invoices", "language": "python", "code": "print(1)"},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn(".py", s)
        script_name = json.loads(_tool_workshop_script_list({}))[0]["name"]
        self.assertIn("print(1)",
                      _tool_workshop_script_read({"filename": script_name}))

        self.assertIn("Application created", _tool_workshop_application(
            {"platform": "Upwork", "job_type": "automation",
             "details": {"rate": "55"}},
            authorization=_DISPATCH_CAPABILITY))
        self.assertEqual(len(json.loads(_tool_workshop_application_list({}))), 1)

        self.assertIn("Deliverable added", _tool_workshop_deliverable(
            {"title": "Bot", "content": "done", "client": "Acme"},
            authorization=_DISPATCH_CAPABILITY))
        self.assertEqual(len(json.loads(_tool_workshop_deliverable_list({}))), 1)

        self.assertIn("Note added", _tool_workshop_note(
            {"title": "Idea", "content": "try cold email"},
            authorization=_DISPATCH_CAPABILITY))
        self.assertEqual(len(json.loads(_tool_workshop_note_list({}))), 1)

    # ── secrets ─────────────────────────────────────────────────────────
    def test_accounts_are_enumerable_without_the_password(self):
        from agents.safety.handlers import (
            _tool_workshop_account_get, _tool_workshop_account_list,
        )
        self.assertTrue(self.ws.add_account(
            "upwork", "edward", "ed@example.com", password="hunter2"))
        listed = _tool_workshop_account_list({})
        self.assertIn("upwork", listed)
        self.assertIn("edward", listed)
        self.assertNotIn("hunter2", listed,
                         "the typed reader must not leak the store that "
                         "workshop_read refuses to open")
        one = _tool_workshop_account_get({"platform": "upwork"})
        self.assertIn("edward", one)
        self.assertNotIn("hunter2", one)
        self.assertIn("***", one)

    def test_account_removal_round_trip(self):
        from agents.safety.calling import _DISPATCH_CAPABILITY
        from agents.safety.handlers import (
            _tool_workshop_account_list, _tool_workshop_account_remove,
        )
        self.assertTrue(self.ws.add_account("fiverr", "ed", "e@x.com"))
        removed = _tool_workshop_account_remove(
            {"platform": "fiverr"}, authorization=_DISPATCH_CAPABILITY)
        self.assertIn("Account removed", removed)
        self.assertNotIn("fiverr", _tool_workshop_account_list({}))

    def test_payment_methods_round_trip(self):
        from agents.safety.handlers import _tool_workshop_payment_list
        self.assertTrue(self.ws.add_payment_method("paypal", "pay@example.com"))
        listed = _tool_workshop_payment_list({})
        self.assertIn("paypal", listed)
        self.assertIn("pay@example.com", listed)


if __name__ == "__main__":
    unittest.main()
