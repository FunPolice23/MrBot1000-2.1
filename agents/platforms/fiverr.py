"""
agents/platforms/fiverr.py — Fiverr adapter stub (v2.0.22 S3)

Shows the adapter shape. Real auth/OAuth and gig submission are deferred
(need real credentials + UX). The security contract already holds:
  * instructions route through InstructionGate
  * submit_proposal / post are HIGH_TRUST and require human confirmation
"""

from .base import PlatformAdapter
from ..trust_boundary import HIGH_TRUST_ACTIONS


class FiverrAdapter(PlatformAdapter):
    platform = "fiverr"
    ai_policy = "ai_allowed"  # Fiverr permits AI-assisted work, but submission
                              # is a human commitment.
    base_url = "https://www.fiverr.com"

    def instruction_url(self):
        # Fiverr has no canonical SKILL.md; if a user attaches one in their
        # seller profile it would be resolved here and gated.
        return None

    def list_actions(self):
        return ["search_gigs", "read_gig", "draft_proposal", "submit_proposal"]

    def _do_action(self, action, payload, *, confirmed_by_human=False):
        # placeholder implementations; real ones need credentials + API/OAuth
        if action == "search_gigs":
            return {"ok": True, "note": "stub: would call Fiverr search"}
        if action == "read_gig":
            return {"ok": True, "note": "stub: would fetch gig details"}
        if action == "draft_proposal":
            return {"ok": True, "note": "stub: local draft only (not sent)"}
        if action == "submit_proposal":
            if not confirmed_by_human:
                return {"ok": False, "reason": "submit_proposal needs human confirmation"}
            return {"ok": True, "note": "stub: would submit to Fiverr (human-confirmed)"}
        return {"ok": False, "reason": f"unknown action {action}"}
