"""
agents/opportunity_lifecycle.py — Opportunity lifecycle automation

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

from agents.evidence import Evidence

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
            "discovered": {"researched", "queued", "failed"},
            "researched": {"queued", "failed"},
            "queued": {"applied", "rejected", "failed"},
            "applied": {"in_progress", "rejected", "failed"},
            "in_progress": {"submitted", "failed"},
            "submitted": {"paid", "failed"},
            "paid": set(),
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
            from agents.evidence_policy import is_transition_eligible
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
                from agents.evidence_factory import from_verification_evidence
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
            state.last_amount = max(state.last_amount, amount)
            state.status = "paid"
            state.verification = evidence
            self._append(state, "paid",
                         f"Payment verified: {evidence.get('summary','')}",
                         amount=amount, source="verifier")
            return state
        # New Evidence path
        if evidence is not None and self._evidence_store is not None:
            self._evidence_store.record(evidence)
            state.evidence_ids.append(evidence.id)
            from agents.evidence_policy import is_transition_eligible
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
            state.status = "paid"
            state.verification = evidence.to_dict()
            self._append(state, "paid",
                         f"Payment verified via {evidence.verification_method} ({evidence.verification_level.name})",
                         amount=amount, source="verifier")
            return state
        # No store + Evidence: require explicit verified flag on the Evidence
        if getattr(evidence, "status", None) is not None and evidence.status.is_affirmative:
            state.last_amount = max(state.last_amount, amount)
            state.status = "paid"
            state.verification = evidence.to_dict()
            self._append(state, "paid", "Payment verified (no store)", amount=amount, source="verifier")
            return state
        self._append(state, "submitted", "Payment NOT verified (no store)", amount=amount, source="verifier")
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
        from agents.evidence_policy import reconcile as _reconcile, is_transition_eligible
        reconciled = _reconcile(ev, reconciler, note=note, method=method)
        self._evidence_store.record(reconciled)
        # If this was a payment/balance record, re-evaluate the SUBMITTED->PAID eligibility.
        all_ev = self._evidence_store.for_subject("opportunity", opportunity_id)
        if is_transition_eligible("SUBMITTED->PAID", all_ev) or \
           is_transition_eligible("CLAIMED->REVENUE_REALIZED", all_ev):
            state = self._ensure(opportunity_id)
            if state.current_stage in ("submitted", "claimed"):
                state.status = "paid"
                self._append(state, "paid",
                             f"Reconciled to paid via {method} ({reconciler})",
                             amount=state.last_amount, source="verifier")
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
        state.status = "failed"
        self._transition(state, "failed", note or "Opportunity failed", source="user")
        return state

    def mark_rejected(self, opportunity_id: str, reason: str = "") -> OpportunityState:
        state = self._ensure(opportunity_id)
        state.status = "rejected"
        self._transition(state, "rejected", reason or "Opportunity rejected", source="user")
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
        elif outcome_state == "failed":
            self.mark_failed(opportunity_id, note or "failed")
        elif outcome_state in ("rejected", "rejected_apply", "rejected_pay"):
            self.mark_rejected(opportunity_id, note or "rejected")
        else:
            # generic terminal transition (e.g. completed/submitted/abandoned)
            state = self._ensure(opportunity_id)
            state.status = outcome_state
            self._transition(state, outcome_state, note or outcome_state, source="system")

        # v2.0.36g: record search-strategy economic outcome (if a recorder was wired). The
        # pipeline extracts the strategy:<id> from the opportunity's provenance and updates
        # Search Strategy Memory so the discovery scheduler learns which searches pay off.
        if self._outcome_callback is not None:
            try:
                self._outcome_callback(opportunity_id, effective_state,
                                       revenue=revenue, cost=cost, effort_hours=effort_hours)
            except Exception:
                pass  # recorder failure must never break the lifecycle transition

        if self._learning_loop is None:
            return None
        return self._learning_loop.process_outcome(
            opportunity_id, outcome_state=effective_state,
            platform=platform, category=category, task_type=task_type,
            revenue=revenue, cost=cost, effort_hours=effort_hours,
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
                    amount: float = 0.0, source: str = "system") -> None:
        if stage not in self._ALLOWED_TRANSITIONS.get(state.current_stage, set()):
            state.last_transition_error = f"Invalid transition from {state.current_stage} to {stage}"
            self._append(state, stage, note, amount=amount, source=source, transition_ok=False)
            return

        state.last_transition_error = ""
        self._append(state, stage, note, amount=amount, source=source, transition_ok=True)
        if source != "system":
            self._notify("transition", state.opportunity_id, state)

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
                amount: float = 0.0, source: str = "system", transition_ok: bool = True) -> None:
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
        """Notify callback if one was registered."""
        if self._callback:
            try:
                self._callback({
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
            ev = s.verification
            if ev and ev.get("verified"):
                total += s.last_amount
        return round(total, 2)

    def unverified_payouts(self) -> List[str]:
        """A2: opportunity ids with a payout attempt that was NOT verified.

        Includes both states stuck at `submitted` (verification failed/blocked) and
        states wrongly marked `paid` via legacy self-report — anything carrying an
        unverified evidence. These must never be counted as honest revenue.
        """
        out = []
        for s in self._states.values():
            ev = s.verification
            if ev is not None and not ev.get("verified"):
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