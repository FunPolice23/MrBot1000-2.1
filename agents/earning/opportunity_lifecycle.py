"""
agents/earning/opportunity_lifecycle.py — Opportunity lifecycle automation

Automated state machine for tracking and progressing opportunities through:
  discovered → researched → queued → applied → in_progress → submitted → paid/failed

Includes:
  - Automated transitions based on scoring and availability
  - Scheduler for time-sensitive opportunities
  - Value/effort ranking for prioritization
  - Automatic queued→applied transitions
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
import json
import os

from agents.evidence.evidence import Evidence, VerificationLevel

# ── Job Status Constants ────────────────────────────────────────────────────
JOB_STATUSES = ("new", "evaluating", "queued", "assigned", "applied", 
                "in_progress", "submitted", "paid", "failed")

# ── Automatic Transition Thresholds ────────────────────────────────────────
AUTO_APPLY_THRESHOLD = float(os.getenv("AUTO_APPLY_THRESHOLD", "0.65"))
AUTO_SUBMIT_THRESHOLD = float(os.getenv("AUTO_SUBMIT_THRESHOLD", "0.70"))
MIN_PAYOUT_USD = float(os.getenv("MIN_PPLY_PAYOUT_USD", "50"))

# ── Timing Configuration ───────────────────────────────────────────────────
SCHEDULER_CHECK_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "300"))  # 5 min default
OPPORTUNITY_DISCOVERY_INTERVAL = int(os.getenv("OPPORTUNITY_DISCOVERY_INTERVAL", "5"))  # Heartbeats between checks
OPPORTUNITY_EXPIRY_HOURS = int(os.getenv("OPPORTUNITY_EXPIRY_HOURS", "72"))  # 72 hrs default


@dataclass
class LifecycleEvent:
    stage: str
    timestamp: float
    note: str = ""
    amount: float = 0.0
    source: str = "system"
    transition_ok: bool = True
    context: Dict = field(default_factory=dict)


@dataclass
class OpportunityState:
    opportunity_id: str
    current_stage: str = "discovered"
    status: str = "active"
    history: List[LifecycleEvent] = field(default_factory=list)
    last_amount: float = 0.0
    last_transition_error: str = ""
    score: float = 0.0  # Value/effort score
    deadline: float = 0.0  # Unix timestamp if applicable
    budget: float = 0.0  # Expected payout
    team_available: bool = True  # Is team ready to work?
    verification: Optional[Dict] = None  # A2: payout VerificationEvidence (if any)
    evidence_ids: List[str] = field(default_factory=list)  # v2.0.34aq: EvidenceStore ids


class OpportunityLifecycleTracker:
    """Automated lifecycle tracker with smart transitions and scheduling."""

    _ALLOWED_TRANSITIONS = {
            # `claimed` is the crypto/airdrop route to revenue: a payout that has no
            # application/submission stage (an on-chain claim) still has to pass
            # through an explicit stage before `paid` is reachable (ARCH-ENG-062).
            # The terminal stages (`paid`/`completed`/`failed`/`rejected`) have an
            # EMPTY set, so no path may be routed THROUGH them — a `failed`
            # opportunity can never be resurrected to `paid`.
            "discovered": {"researched", "queued", "applied", "claimed", "completed", "failed"},
            "researched": {"queued", "applied", "claimed", "completed", "failed"},
            "queued": {"applied", "claimed", "rejected", "completed", "failed"},
            "applied": {"in_progress", "submitted", "claimed", "rejected", "completed", "failed"},
            "in_progress": {"submitted", "completed", "failed"},
            "submitted": {"paid", "completed", "failed"},
            "claimed": {"paid", "completed", "failed"},
            "paid": set(),
            "completed": set(),
            "failed": set(),
            "rejected": set(),
        }

    def __init__(self, callback: Callable = None, evidence_store=None, learning_loop=None,
                 outcome_callback: Callable = None, state_path: str = None):
        self._states: Dict[str, OpportunityState] = {}
        self._callback = callback  # Called on lifecycle events
        self._evidence_store = evidence_store  # v2.0.34aq: EvidenceStore (optional; back-compat)
        self._learning_loop = learning_loop  # v2.0.36d: Opportunity Learning Loop (optional)
        self._outcome_callback = outcome_callback  # v2.0.36g: search-strategy outcome recorder
        self._last_scheduler_check = 0.0
        self._auto_transition_enabled = os.getenv("AUTO_LIFECYCLE_TRANSITIONS", "true").lower() == "true"
        # v2.0.36k Group 4 (M-1): persist lifecycle state across restarts.
        # The tracker previously kept all state in RAM only, so a restart lost
        # the authoritative lifecycle (the persistent portfolio could still
        # claim PAID) - a recovery/consistency hole. We now persist to a JSON
        # file and recover() it on construction when state_path is provided.
        self._state_path = state_path
        if self._state_path:
            self._recover_from_disk()

    # ── State Access ──────────────────────────────────────────────────────────

    def start(self, opportunity: Any) -> OpportunityState:
        """Start tracking a new opportunity."""
        state = self._ensure(opportunity.id)
        state.budget = getattr(opportunity, 'estimated_usd_value', 0.0) or 0.0
        state.deadline = getattr(opportunity, 'deadline', 0.0) or 0.0
        state.score = getattr(opportunity, 'score', 0.5)
        # Also check for budget attribute
        if hasattr(opportunity, 'budget'):
            state.budget = opportunity.budget
        self._append(state, "discovered", "Opportunity discovered", source="system")
        self._notify("start", opportunity.id, state)
        return state

    def get_state(self, opportunity_id: str) -> Dict:
        """Get current state as dict for serialization."""
        state = self._ensure(opportunity_id)
        # M-1 persistence fix: serialize verification safely. It may be a legacy
        # VerificationEvidence dict OR an Evidence object; json.dump(default=str)
        # would stringify an Evidence into garbage, so normalize it here.
        verification = state.verification
        if hasattr(verification, "to_dict"):
            verification = verification.to_dict()
        return {
            "opportunity_id": state.opportunity_id,
            "current_stage": state.current_stage,
            "status": state.status,
            "last_amount": state.last_amount,
            "score": state.score,
            "budget": state.budget,
            "deadline": state.deadline,
            "team_available": state.team_available,
            "evidence_ids": list(state.evidence_ids),
            "history": [self._event_to_dict(e) for e in state.history],
            "verification": verification,
            # ARCH-ENG-061: a refused transition's reason is the operator-visible
            # signal that a move was rejected. It was set on the state object but
            # never serialized, so the GUI/report could not show WHY an
            # opportunity refused to advance.
            "last_transition_error": state.last_transition_error,
        }

    def get_all_states(self) -> List[Dict]:
        """Get all opportunity states."""
        return [self.get_state(oid) for oid in self._states]

    def get_queued_opportunities(self) -> List[OpportunityState]:
        """Get opportunities ready for auto-application."""
        return [
            s for s in self._states.values()
            if s.current_stage == "queued" 
            and s.score >= AUTO_APPLY_THRESHOLD
            and s.budget >= MIN_PAYOUT_USD
            and s.team_available
        ]

    def get_active_opportunities(self) -> List[OpportunityState]:
        """Get opportunities that need attention."""
        return [
            s for s in self._states.values()
            if s.status == "active" and s.current_stage not in {"paid", "failed", "rejected"}
        ]

    # ── Automated Transitions ───────────────────────────────────────────────

    def promote_to_applied(self, opportunity_id: str, reason: str = "") -> OpportunityState:
        """Auto-transition from queued to applied."""
        state = self._ensure(opportunity_id)
        if state.current_stage != "queued":
            return state
        self._transition(state, "applied", reason or "Auto-promotion: score threshold met", source="scheduler")
        self._notify("applied", opportunity_id, state)
        return state

    def promote_to_submitted(self, opportunity_id: str, work_complete: bool = True) -> OpportunityState:
        """Auto-transition from applied/in_progress to submitted."""
        state = self._ensure(opportunity_id)
        if state.current_stage in ("applied", "in_progress"):
            self._transition(
                state, "submitted", 
                reason=f"Auto-promotion: work complete", 
                source="scheduler"
            )
            self._notify("submitted", opportunity_id, state)
        return state

    # ── Scheduler ───────────────────────────────────────────────────────────

    def scheduler_check(self, current_time: float = None) -> List[Dict]:
        """Run scheduler check - returns list of actions to take."""
        now = current_time or time.time()
        if now - self._last_scheduler_check < SCHEDULER_CHECK_INTERVAL:
            return []
        self._last_scheduler_check = now

        actions = []

        # 1. Auto-promote qualified queued opportunities
        queued = self.get_queued_opportunities()
        for state in queued:
            actions.append({
                "type": "promote_applied",
                "opportunity_id": state.opportunity_id,
                "reason": f"Auto-promotion: score={state.score:.2f} >= {AUTO_APPLY_THRESHOLD}, budget=${state.budget:.0f}"
            })

        # 2. Check for expired opportunities
        for oid, state in self._states.items():
            if state.deadline and state.deadline < now:
                if state.current_stage not in ("submitted", "paid", "failed", "rejected"):
                    actions.append({
                        "type": "expire",
                        "opportunity_id": oid,
                        "reason": "Opportunity past deadline"
                    })

        # 3. Check for stalled opportunities (in_progress > 24h)
        for oid, state in self._states.items():
            if state.current_stage == "in_progress":
                last_ts = state.history[-1].timestamp if state.history else 0
                if now - last_ts > 24 * 3600:  # 24 hours
                    actions.append({
                        "type": "follow_up",
                        "opportunity_id": oid,
                        "reason": "Stalled in_progress for 24h+"
                    })

        return actions

    def process_scheduled_actions(self, actions: List[Dict]) -> List[Dict]:
        """Execute scheduled actions and return results."""
        results = []
        for action in actions:
            if action["type"] == "promote_applied":
                state = self.promote_to_applied(action["opportunity_id"], action.get("reason", ""))
                results.append({"action": "applied", "id": action["opportunity_id"], "success": True})

            elif action["type"] == "expire":
                state = self._ensure(action["opportunity_id"])
                if state.current_stage not in ("submitted", "paid", "failed", "rejected"):
                    self._transition(state, "failed", "Opportunity expired", source="scheduler")
                    results.append({"action": "expire", "id": action["opportunity_id"], "success": True})

            elif action["type"] == "follow_up":
                # Log follow-up needed
                results.append({"action": "follow_up", "id": action["opportunity_id"], "success": True})

        return results

    # ── Ranking & Prioritization ────────────────────────────────────────────

    def rank_by_value_effort(self, limit: int = 10) -> List[tuple]:
        """Rank opportunities by value/effort ratio. Returns [(state, score), ...]."""
        scored = []
        for state in self._states.values():
            if state.status != "active":
                continue
            if state.current_stage in ("paid", "failed", "rejected"):
                continue

            # Calculate value/effort score
            # Higher is better
            value_score = state.score  # 0-1 fit score
            effort_factor = min(1.0, state.budget / 1000)  # Normalize to 0-1
            
            # Urgency bonus
            urgency_bonus = 0
            if state.deadline:
                hours_left = (state.deadline - time.time()) / 3600
                if hours_left < 24:
                    urgency_bonus = 0.3
                elif hours_left < 72:
                    urgency_bonus = 0.1

            total_score = (value_score * 0.6 + effort_factor * 0.3 + urgency_bonus * 0.1)
            scored.append((state, total_score))

        return sorted(scored, key=lambda x: x[1], reverse=True)[:limit]

    def get_top_opportunities(self, k: int = 3) -> List[OpportunityState]:
        """Get top K opportunities by value/effort ratio."""
        ranked = self.rank_by_value_effort(limit=k)
        return [state for state, score in ranked]

    # ── State Transitions ───────────────────────────────────────────────────

    def mark_researched(self, opportunity_id: str, note: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        self._transition(state, "researched", note or "Opportunity researched", source="user")
        return state

    def mark_queued(self, opportunity_id: str, score: float = 0.5, note: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        state.score = score
        state.team_available = True  # Mark as ready for auto-promotion
        self._transition(state, "queued", note or "Opportunity queued for action", source="user")
        return state

    def mark_applied(self, opportunity_id: str, note: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        state.team_available = False
        self._transition(state, "applied", note or "Application submitted", source="user")
        return state

    def mark_in_progress(self, opportunity_id: str, note: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        self._transition(state, "in_progress", note or "Work started", source="user")
        return state

    def mark_submitted(self, opportunity_id: str, note: str = "", amount: float = 0.0,
                      evidence=None) -> OpportunityState:
        """v2.0.34aq: if an Evidence is supplied (e.g. platform_submission), record it in the
        EvidenceStore and gate the transition on the policy. Without a store/evidence the
        behaviour matches the prior local belief (back-compat)."""
        state = self._ensure(opportunity_id)
        state.last_amount = amount
        if evidence is not None and self._evidence_store is not None:
            self._evidence_store.record(evidence)
            state.evidence_ids.append(evidence.id)
            # IN_PROGRESS->SUBMITTED requires a VERIFIED external platform_submission.
            from agents.evidence.evidence_policy import is_transition_eligible
            all_ev = self._evidence_store.for_subject("opportunity", opportunity_id)
            if not is_transition_eligible("IN_PROGRESS->SUBMITTED", all_ev):
                self._append(state, "submitted",
                             f"Submission recorded but not externally confirmed: {note}",
                             amount=amount, source="verifier")
                return state
        self._transition(state, "submitted", note or "Delivery submitted", amount=amount, source="user")
        return state

    def mark_paid_verified(self, opportunity_id: str, amount: float = 0.0,
                           evidence=None) -> OpportunityState:
        """v2.0.34aq: accepts a legacy VerificationEvidence dict OR a new Evidence.

        When an EvidenceStore is attached, the SUBMITTED->PAID transition is gated by
        EvidencePolicy (requires submission + completion + payment evidence at the right
        level). Without a store, falls back to the prior behaviour: verified dict -> paid.
        """
        state = self._ensure(opportunity_id)
        # v2.0.34aq: the payout verifier returns a legacy `VerificationEvidence`
        # dataclass (not an `Evidence`). Convert it to the common Evidence vocabulary
        # before any policy gating so the rest of the method only handles Evidence.
        if (evidence is not None and not hasattr(evidence, "status")
                and hasattr(evidence, "verified") and hasattr(evidence, "method")):
            try:
                from agents.evidence.evidence_factory import from_verification_evidence
                evidence = from_verification_evidence(evidence, subject_id=opportunity_id)
            except Exception:
                evidence = None
        if evidence is not None and not hasattr(evidence, "status"):
            if not evidence or not evidence.get("verified"):
                self._append(state, "submitted",
                             f"Payment NOT verified: {evidence.get('note','no evidence') if evidence else 'no evidence'}",
                             amount=amount, source="verifier")
                state.last_amount = max(state.last_amount, 0.0)
                state.verification = evidence
                return state
            if amount <= 0.0:
                self._append(state, "submitted",
                             "Payment verified but amount is not positive; not treated as realized revenue",
                             amount=amount, source="verifier")
                state.last_amount = max(state.last_amount, 0.0)
                state.verification = evidence
                return state
            state.last_amount = max(state.last_amount, amount)
            self._mark_paid(state,
                            f"Payment verified: {evidence.get('summary','')}",
                            amount=amount, verification=evidence)
            return state
        # New Evidence path
        if evidence is not None and self._evidence_store is not None:
            self._evidence_store.record(evidence)
            state.evidence_ids.append(evidence.id)
            from agents.evidence.evidence_policy import is_transition_eligible
            all_ev = self._evidence_store.for_subject("opportunity", opportunity_id)
            # A payment is eligible to flip to "paid" if EITHER a freelance-style chain
            # (submission+completion+payment) OR a crypto/airdrop chain (L5 on-chain balance
            # delta) is satisfied. This avoids blocking cryptographically-proven revenue just
            # because there was no Upwork-style submission stage.
            eligible = (
                is_transition_eligible("SUBMITTED->PAID", all_ev)
                or is_transition_eligible("CLAIMED->REVENUE_REALIZED", all_ev)
            )
            if not eligible:
                self._append(state, "submitted",
                             f"Payment evidence present but transition not eligible: {evidence.status.value}",
                             amount=amount, source="verifier")
                state.last_amount = max(state.last_amount, 0.0)
                state.verification = evidence.to_dict()
                return state
            state.last_amount = max(state.last_amount, amount)
            self._mark_paid(state,
                            f"Payment verified via {evidence.verification_method} ({evidence.verification_level.name})",
                            amount=amount, verification=evidence.to_dict())
            return state
        # No store + Evidence: there is no EvidenceStore to consult, so the
        # policy gate (`is_transition_eligible`) cannot run. Trusting an
        # affirmative *status* alone here is what let an L1 manual_attestation
        # (an operator-typed transaction reference, the lowest trust level)
        # flip the lifecycle to "paid" — and the caller then credited a
        # submission-ramp WIN from it, advancing the win-rate that unlocks
        # auto-submission (v2.1.37, ARCH-ENG-043).
        #
        # Without a store we cannot prove an external payment, so apply the same
        # trust floor the policy gate would: affirmative status AND level >= L3,
        # plus a positive amount (the with-store path enforces that too).
        if (getattr(evidence, "status", None) is not None
                and evidence.status.is_affirmative
                and getattr(evidence, "verification_level", None) is not None
                and evidence.verification_level
                >= VerificationLevel.L3_EXTERNAL_SOURCE):
            if amount <= 0.0:
                self._append(state, "submitted",
                             ("Payment evidence present but amount is not positive; "
                              "not treated as realized revenue (no store)"),
                             amount=amount, source="verifier")
                state.last_amount = max(state.last_amount, 0.0)
                state.verification = evidence.to_dict()
                return state
            state.last_amount = max(state.last_amount, amount)
            self._mark_paid(state,
                            (f"Payment verified via {evidence.verification_method} "
                             f"({evidence.verification_level.name}, no store)"),
                            amount=amount, verification=evidence.to_dict())
            return state
        # Fail closed: an unproven or low-trust payment is NOT a paid lifecycle.
        # `evidence` may legitimately be None here (a caller reported a payout
        # with nothing attached) — the original code tolerated that via the
        # `if evidence else None` guard on the line below, so do the same here.
        _status = getattr(evidence, "status", None)
        _lvl = getattr(evidence, "verification_level", None)
        if _status is None:
            _detail = "no evidence attached"
        else:
            # getattr-guard the level name too: a duck-typed evidence may carry a
            # status but a None level, and this audit path must never raise.
            _lvl_name = getattr(_lvl, "name", None) or "no level"
            _detail = f"{_status.value} at {_lvl_name}"
        self._append(state, "submitted",
                     (f"Payment NOT verified (no store): {_detail} does not meet the "
                      "L3 external-source floor; an attested balance is not proof "
                      "of payment"),
                     amount=amount, source="verifier")
        state.last_amount = max(state.last_amount, 0.0)
        state.verification = evidence.to_dict() if evidence else None
        return state

    def reconcile_evidence(self, opportunity_id: str, evidence_id: str,
                           reconciler: str = "operator", note: str = "",
                           method: str = "external_reconciliation") -> Optional[Evidence]:
        """v2.0.34au: promote a non-affirmative (CONFLICTED/REJECTED/UNVERIFIED) evidence to
        VERIFIED via INDEPENDENT external reconciliation (never an LLM assertion). Re-records the
        reconciled Evidence and returns it. Requires an EvidenceStore; back-compat safe (returns
        None when no store). The escalate path lives in `agents.evidence_policy.reconcile`, which
        refuses manual/local re-assertion (only independent methods may flip to affirmative).
        """
        if self._evidence_store is None:
            return None
        ev = self._evidence_store.get(evidence_id)
        if ev is None:
            return None
        from agents.evidence.evidence_policy import reconcile as _reconcile, is_transition_eligible
        reconciled = _reconcile(ev, reconciler, note=note, method=method)
        self._evidence_store.record(reconciled)
        # If this was a payment/balance record, re-evaluate the SUBMITTED->PAID eligibility.
        all_ev = self._evidence_store.for_subject("opportunity", opportunity_id)
        if is_transition_eligible("SUBMITTED->PAID", all_ev) or \
           is_transition_eligible("CLAIMED->REVENUE_REALIZED", all_ev):
            state = self._ensure(opportunity_id)
            # ARCH-ENG-065: book the RECONCILED amount, not the claimed one. The old
            # code used `state.last_amount`, which `mark_submitted` had set to the
            # caller-supplied claim — so a $5000 claim settled for $25 booked $5000
            # of verified revenue while `EconomicAccounting` on the same subject said
            # $25. Two authorities disagreed by the whole difference. The reconciled
            # evidence is the external truth; fall back to the claim only when the
            # evidence itself carries no amount at all.
            reconciled_amount = float(getattr(reconciled, "amount", 0.0) or 0.0)
            if reconciled_amount > 0.0:
                # ARCH-ENG-065: the reconciled amount IS the externally established
                # payment, so it REPLACES the claim rather than being max'd with it.
                # `max()` preserved a $5000 claim that had settled for $25.
                state.last_amount = reconciled_amount
            else:
                # The reconciled record carries no amount of its own (e.g. a
                # completion confirmation) — keep the recorded claim.
                reconciled_amount = state.last_amount
            if reconciled_amount <= 0.0:
                self._append(state, "submitted",
                             "Reconciled evidence present but no positive amount; not treated as realized revenue",
                             amount=0.0, source="verifier")
            else:
                self._mark_paid(state,
                                f"Reconciled to paid via {method} ({reconciler})",
                                amount=reconciled_amount,
                                verification=reconciled.to_dict())
        return reconciled

    def mark_paid(self, opportunity_id: str, amount: float = 0.0, note: str = "") -> OpportunityState:
        """DEPRECATED (A2): self-reported payout. Now delegates to the verifier
        with an UNVERIFIED evidence so unverified payouts are visibly flagged and
        excluded from verified revenue. Prefer `mark_paid_verified`.
        """
        unverified = {
            "method": "legacy_self_report",
            "verified": False,
            "expected_usd": amount,
            "observed_usd": 0.0,
            "note": "legacy self-reported payout (unverified)",
            "verified_at": time.time(),
        }
        return self.mark_paid_verified(opportunity_id, amount, unverified)

    def mark_failed(self, opportunity_id: str, note: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        # ARCH-ENG-061: only commit the status when the transition is actually
        # allowed. Setting it before the gate let `mark_failed` demote a
        # revenue-booked `paid` opportunity to status="failed" even though the
        # stage itself was correctly refused.
        if self._transition(state, "failed", note or "Opportunity failed", source="user"):
            state.status = "failed"
        return state

    def mark_rejected(self, opportunity_id: str, reason: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        if self._transition(state, "rejected", reason or "Opportunity rejected", source="user"):
            state.status = "rejected"
        return state

    def mark_final_outcome(self, opportunity_id: str, *, outcome_state: str,
                           platform: str = "", category: str = "", task_type: str = "",
                           revenue: float = 0.0, cost: float = 0.0,
                           effort_hours: float = 0.0, time_spent_hours: float = 0.0,
                           strategy_used: str = "", proposal_variant: str = "",
                           failure_cause: str = "", success_cause: str = "",
                           predicted: Optional[Dict[str, float]] = None,
                           evidence_ids: Optional[List[str]] = None,
                           note: str = "") -> Optional["LearningDelta"]:
        """v2.0.36d: feed a final outcome into the Opportunity Learning Loop.

        Back-compat safe: if no learning_loop was injected, this is a no-op (returns None) and
        the plain lifecycle transition still happens. When a loop IS present, it runs the
        10-step feedback pipeline (record -> associate evidence -> compute economics ->
        compare predicted/actual -> update reputation/strategy/metrics -> governed ranking
        proposals) so FUTURE evaluations reflect what was learned. The loop itself enforces
        that security policy is never modified and ranking adjustments stay within bounds.
        """
        # Still record the plain lifecycle transition for state bookkeeping.
        # H-4 fix: a `paid` outcome without *verified payment evidence* must NOT flip
        # the lifecycle to paid nor feed reputation as a win. `mark_paid_verified`
        # already requires affirmative evidence to flip status -> "paid"; if it does not
        # (unverified self-report), we record an honest non-win terminal outcome
        # (`completed`) instead of silently writing a "paid"/revenue reputation event.
        effective_state = outcome_state
        # ARCH-ENG-068: the H-4 guard below correctly refuses to book an unverified
        # "paid" as revenue, but `revenue` was still passed verbatim to the learning
        # loop, which treats "completed" as `is_success=True`. The result: an
        # unverified $5000 claim was recorded as a successful $5000 revenue event
        # across the category / task-type / strategy priors — the same collapse of
        # states the guard exists to prevent, one layer down. When the effective
        # outcome is downgraded, its revenue must be zeroed with it.
        effective_revenue = revenue
        if outcome_state in ("paid",):
            state = self.mark_paid_verified(opportunity_id, amount=revenue)
            if getattr(state, "status", "") != "paid":
                # Payment was NOT verified — do not credit a paid win. Record as a
                # completed (non-revenue) terminal state so reputation/revenue stay honest.
                s = self._ensure(opportunity_id)
                s.status = "completed"
                self._transition(s, "completed",
                                note or "paid reported but payment not verified",
                                source="system")
                effective_state = "completed"
                effective_revenue = 0.0
        elif outcome_state == "failed":
            self.mark_failed(opportunity_id, note or "failed")
        elif outcome_state in ("rejected", "rejected_apply", "rejected_pay"):
            self.mark_rejected(opportunity_id, note or "rejected")
        else:
            # generic terminal transition (e.g. completed/submitted/abandoned)
            state = self._ensure(opportunity_id)
            # ARCH-ENG-061: commit the status only if the stage transition was
            # allowed, otherwise a refused move would still change the status.
            if self._transition(state, outcome_state, note or outcome_state, source="system"):
                state.status = outcome_state

        # v2.0.36g: record search-strategy economic outcome (if a recorder was wired). The
        # pipeline extracts the strategy:<id> from the opportunity's provenance and updates
        # Search Strategy Memory so the discovery scheduler learns which searches pay off.
        if self._outcome_callback is not None:
            try:
                self._outcome_callback(opportunity_id, effective_state,
                                       revenue=effective_revenue, cost=cost, effort_hours=effort_hours)
            except Exception:
                pass  # recorder failure must never break the lifecycle transition

        if self._learning_loop is None:
            return None
        return self._learning_loop.process_outcome(
            opportunity_id, outcome_state=effective_state,
            platform=platform, category=category, task_type=task_type,
            revenue=effective_revenue, cost=cost, effort_hours=effort_hours,
            time_spent_hours=time_spent_hours, strategy_used=strategy_used,
            proposal_variant=proposal_variant, failure_cause=failure_cause,
            success_cause=success_cause, predicted=predicted, evidence_ids=evidence_ids,
        )

    # ── Internal Helpers ────────────────────────────────────────────────────

    def _ensure(self, opportunity_id: str) -> OpportunityState:
        if opportunity_id not in self._states:
            self._states[opportunity_id] = OpportunityState(opportunity_id=opportunity_id)
        return self._states[opportunity_id]

    def _transition(self, state: OpportunityState, stage: str, note: str, 
                    amount: float = 0.0, source: str = "system") -> bool:
        """Attempt a stage transition. Returns True iff the stage actually moved.

        ARCH-ENG-061: a stage not in `_ALLOWED_TRANSITIONS` is recorded in the audit
        trail with `transition_ok=False` but does NOT move `current_stage`. The old
        code appended unconditionally, so the table was decorative: `in_progress ->
        queued`, `paid -> failed` (a revenue-booked opportunity demoted) and
        `discovered -> completed` (a stage not even in the table) all "worked" while
        reporting `transition_ok=False`. `last_transition_error` is the signal.
        """
        if stage not in self._ALLOWED_TRANSITIONS.get(state.current_stage, set()):
            state.last_transition_error = f"Invalid transition from {state.current_stage} to {stage}"
            self._append(state, stage, note, amount=amount, source=source,
                         transition_ok=False, move_stage=False)
            return False

        state.last_transition_error = ""
        self._append(state, stage, note, amount=amount, source=source, transition_ok=True)
        if source != "system":
            self._notify("transition", state.opportunity_id, state)
        return True

    def _mark_paid(self, state: OpportunityState, note: str, amount: float,
                   verification, source: str = "verifier") -> bool:
        """Flip a state to `paid` THROUGH the state machine (ARCH-ENG-062).

        Every paid branch used to call `self._append(state, "paid", ...)` directly,
        which bypassed `_ALLOWED_TRANSITIONS` entirely — a single L5 balance-delta
        record moved `discovered` straight to `paid`, skipping
        researched/queued/applied/in_progress/submitted, and a `failed` opportunity
        could be resurrected to `paid`. The state machine must be the single
        authority on which moves are legal.

        The freelance route reaches `paid` from `submitted`. The crypto/airdrop
        route (CLAIMED->REVENUE_REALIZED) has no submission stage, so it is routed
        through the explicit `claimed` stage first. Intermediate stages are walked
        via the transition graph — a payout verified on an opportunity still at
        `applied` or `in_progress` advances it through the remaining stages rather
        than being refused. Terminal stages have an empty successor set, so a
        `failed` opportunity can never be resurrected to `paid`.
        """
        if "paid" not in self._ALLOWED_TRANSITIONS.get(state.current_stage, set()):
            waypoints = self._route_to(state.current_stage, "paid")
            if not waypoints:
                self._append(state, "paid", note, amount=amount, source=source,
                             transition_ok=False, move_stage=False)
                return False
            for stage in waypoints:
                # Intermediate stages are system-internal routing steps, not
                # operator/verifier actions, so they must not emit a transition
                # notification. `paid` itself is excluded — the final transition
                # below carries the real note and source.
                if stage == "paid":
                    continue
                self._transition(state, stage,
                                 f"Advanced to {stage} on verified payout",
                                 amount=amount, source="system")
        if not self._transition(state, "paid", note, amount=amount, source=source):
            return False
        state.status = "paid"
        state.verification = verification
        # ARCH-ENG-092: `_transition` -> `_append` -> `_persist` wrote the JSON
        # snapshot BEFORE these two assignments, so the file on disk held
        # current_stage='paid' with status='active' and verification=None. A
        # restart recovered exactly that, `_is_verified_evidence(None)` returned
        # False, and a real $750 externally-verified payout silently collapsed to
        # verified_revenue_usd() == 0.0 while still appearing in no unverified
        # list either — the money vanished from every report. Re-persist now that
        # the authoritative fields are actually set.
        self._persist()
        return True

    def _route_to(self, start: str, target: str) -> List[str]:
        """Shortest legal stage path `start` -> `target`, excluding `start` itself.

        ARCH-ENG-062: `_mark_paid` originally tried a single hardcoded waypoint, so
        `paid` was unreachable from `applied` and `in_progress` — a real $750 payout
        on an in-progress opportunity was refused and booked $0 revenue. Walking the
        graph keeps the state machine authoritative while still letting a verified
        payout reach `paid` from wherever the opportunity actually is. Returns []
        when no path exists (terminal stages have no successors, so `failed` and
        `rejected` can never be routed to `paid`).
        """
        if start == target:
            return []
        queue = [(start, [])]
        seen = {start}
        while queue:
            stage, path = queue.pop(0)
            for nxt in sorted(self._ALLOWED_TRANSITIONS.get(stage, set())):
                if nxt == target:
                    return path + [nxt]
                if nxt in seen:
                    continue
                seen.add(nxt)
                queue.append((nxt, path + [nxt]))
        return []

    # ── v2.0.36k Group 4 (M-1): persistence ────────────────────────────────
    def _persist(self) -> None:
        """Write all lifecycle states to the JSON state file (best-effort)."""
        if not self._state_path:
            return
        try:
            import json
            data = [self.get_state(oid) for oid in self._states]
            tmp = self._state_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2, default=str)
            os.replace(tmp, self._state_path)
        except Exception:
            # Persistence must never break the live pipeline.
            pass

    def _recover_from_disk(self) -> None:
        """Load previously-persisted states so a restart does not lose the
        authoritative lifecycle. Reconstructs minimal OpportunityState objects."""
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            import json
            with open(self._state_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            for rec in data:
                oid = rec.get('opportunity_id')
                if not oid or oid in self._states:
                    continue
                st = OpportunityState(opportunity_id=oid)
                st.current_stage = rec.get('current_stage', 'discovered')
                st.status = rec.get('status', 'active')
                st.last_amount = float(rec.get('last_amount', 0.0) or 0.0)
                st.score = float(rec.get('score', 0.5) or 0.5)
                st.budget = float(rec.get('budget', 0.0) or 0.0)
                st.deadline = float(rec.get('deadline', 0.0) or 0.0)
                st.verification = rec.get('verification', {}) if rec.get('verification') else None
                st.evidence_ids = list(rec.get('evidence_ids', []))
                hist = rec.get('history', [])
                for e in hist:
                    st.history.append(LifecycleEvent(
                        stage=e.get('stage', 'discovered'),
                        timestamp=float(e.get('timestamp', 0.0) or 0.0),
                        note=e.get('note', ''),
                        amount=float(e.get('amount', 0.0) or 0.0),
                        source=e.get('source', 'system'),
                        transition_ok=bool(e.get('transition_ok', True)),
                    ))
                self._states[oid] = st
        except Exception:
            # A corrupt state file must not crash startup; start fresh.
            pass

    def _append(self, state: OpportunityState, stage: str, note: str, 
                amount: float = 0.0, source: str = "system", transition_ok: bool = True,
                move_stage: bool = True) -> None:
        # ARCH-ENG-061: `move_stage=False` records a REFUSED transition in the audit
        # trail without moving `current_stage`. A rejected transition must leave the
        # state machine where it was.
        if move_stage:
            state.current_stage = stage
        state.history.append(LifecycleEvent(
            stage=stage, timestamp=time.time(), note=note, 
            amount=amount, source=source, transition_ok=transition_ok
        ))

        # v2.0.36k Group 4 (M-1): persist after every state mutation.
        self._persist()

    def _event_to_dict(self, event: LifecycleEvent) -> Dict:
        return {
            "stage": event.stage,
            "timestamp": event.timestamp,
            "note": event.note,
            "amount": event.amount,
            "source": event.source,
            "transition_ok": event.transition_ok
        }

    def _notify(self, event_type: str, opportunity_id: str, state: OpportunityState):
        """Notify callback if one was registered.

        Best-effort by contract: `__notify` is reached from every transition, and a
        missing callback attribute (a tracker built via `__new__` in a test fixture)
        must never abort a state change.
        """
        callback = getattr(self, "_callback", None)
        if not callback:
            return
        try:
            callback({
                "type": event_type,
                "opportunity_id": opportunity_id,
                "stage": state.current_stage,
                "score": state.score,
                "budget": state.budget
            })
        except Exception:
            pass

    # ── Export Functions ────────────────────────────────────────────────────

    def verified_revenue_usd(self) -> float:
        """A2: sum of `last_amount` for states whose payout was VERIFIED.

        States marked paid via the deprecated `mark_paid` (self-reported) carry an
        unverified evidence and are excluded. This is the honest revenue number.
        """
        total = 0.0
        for s in self._states.values():
            if s.status != "paid":
                continue
            if self._is_verified_evidence(s.verification):
                total += s.last_amount
        return round(total, 2)

    @staticmethod
    def _is_verified_evidence(ev: Optional[Dict]) -> bool:
        """True iff a stored verification dict proves an INDEPENDENT payment.

        ARCH-ENG-064: this used to read `ev.get("verified")`, but `Evidence.to_dict()`
        emits `status` / `verification_level` / `verification_method` and NEVER a
        `verified` key. The consequence was inverted trust: a genuine L5 on-chain
        payout reported `verified_revenue_usd() == 0.0` and was listed in
        `unverified_payouts()`, while a hand-written dict `{"verified": True}`
        booked its full `expected_usd` as revenue. Trust now follows the same
        evidence-policy rule the lifecycle gate uses — affirmative status AND
        verification level >= L3 external source — with the legacy `verified`
        boolean honoured only when it carries no status/level of its own.
        """
        if not ev:
            return False
        status = str(ev.get("status", "") or "").upper()
        if not status:
            # Legacy dict shape: honour the explicit boolean only.
            return bool(ev.get("verified"))
        if status not in ("VERIFIED", "PARTIALLY_VERIFIED"):
            return False
        level = ev.get("verification_level")
        if level is None:
            return False
        try:
            return int(level) >= int(VerificationLevel.L3_EXTERNAL_SOURCE)
        except (TypeError, ValueError):
            return False

    def unverified_payouts(self) -> List[str]:
        """A2: opportunity ids with a payout attempt that was NOT verified.

        Includes both states stuck at `submitted` (verification failed/blocked) and
        states wrongly marked `paid` via legacy self-report — anything carrying an
        unverified evidence. These must never be counted as honest revenue.
        """
        out = []
        for s in self._states.values():
            if s.status != "paid":
                continue
            if not self._is_verified_evidence(s.verification):
                out.append(s.opportunity_id)
        return out
        # ── Export Functions ────────────────────────────────────────────────────

    def export_queued_jobs(self, path: str = None) -> str:
        """Export queued jobs to JSON file for research folder integration."""
        queued = self.get_queued_opportunities()
        data = {
            "exported_at": time.time(),
            "count": len(queued),
            "opportunities": [
                {
                    "opportunity_id": s.opportunity_id,
                    "current_stage": s.current_stage,
                    "score": s.score,
                    "budget": s.budget,
                    "last_amount": s.last_amount,
                    "history_count": len(s.history)
                }
                for s in queued
            ]
        }
        if path:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            return str(path)
        return json.dumps(data, indent=2, default=str)

    def export_analytics_report(self, path: str = None) -> str:
        """Export analytics summary to JSON file."""
        states = list(self._states.values())
        by_stage = {}
        by_status = {}
        total_value = 0.0
        
        for s in states:
            by_stage[s.current_stage] = by_stage.get(s.current_stage, 0) + 1
            by_status[s.status] = by_status.get(s.status, 0) + 1
            if s.last_amount:
                total_value += s.last_amount

        data = {
            "generated_at": time.time(),
            "summary": {
                "total_opportunities": len(states),
                "by_stage": by_stage,
                "by_status": by_status,
                "total_value_usd": round(total_value, 2),
                "active_opportunities": len(self.get_active_opportunities()),
                "queued_ready": len(self.get_queued_opportunities()),
            },
            "top_opportunities": [
                {k: getattr(s, k) for k in ['opportunity_id', 'current_stage', 'score', 'budget'] 
                 if hasattr(s, k)}
                for s, _ in self.rank_by_value_effort(limit=5)
            ]
        }
        
        if path:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            return str(path)
        return json.dumps(data, indent=2, default=str)


# ── Module-level convenience functions ────────────────────────────────────

_lifecycle_tracker: Optional[OpportunityLifecycleTracker] = None

def get_lifecycle_tracker() -> OpportunityLifecycleTracker:
    """Get or create the global lifecycle tracker."""
    global _lifecycle_tracker
    if _lifecycle_tracker is None:
        _lifecycle_tracker = OpportunityLifecycleTracker()
    return _lifecycle_tracker


def initialize_lifecycle_export(research_folder: str = None):
    """Initialize export paths for research folder integration."""
    if research_folder:
        research_path = Path(research_folder)
        research_path.mkdir(parents=True, exist_ok=True)
        
        tracker = get_lifecycle_tracker()
        tracker.export_queued_jobs(str(research_path / "queued_jobs.json"))
        tracker.export_analytics_report(str(research_path / "analytics_report.json"))
        
        return str(research_path)