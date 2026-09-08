"""agents/alerting.py — Real-time alerting rules layer (Phase 6).

Sits between the event logger and the notification service:
- Each rule filters events by type/source/level
- On a matching event, the rule evaluates a condition
- If the condition fires, the rule emits a notification and/or a metric update
- Rules are configurable: spend thresholds, tier change alerts,
  safety-block alerts, pending-approval aging, earning milestones

Implementation stays desktop-app focused; no external services.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agents.event_logger import Event, EventType, EventLevel, StructuredEventLogger
from agents.notifications import NotificationService, NotifLevel, notify

logger = logging.getLogger("mrbot.alerting")


# ── Rule kinds ───────────────────────────────────────────────────────────────

class RuleKind(str, Enum):
    LLM_SPEND_THRESHOLD = "llm_spend_threshold"
    SURVIVAL_TIER_CHANGE = "survival_tier_change"
    SAFETY_BLOCK = "safety_block"
    PENDING_APPROVAL_AGING = "pending_approval_aging"
    EARNING_MILESTONE = "earning_milestone"
    CUSTOM_EVENT = "custom_event"


# ── Rule definition ─────────────────────────────────────────────────────────

@dataclass
class AlertRule:
    """A single alerting rule.

    ``condition`` is a callable ``(event: Event, state: Dict[str, Any]) -> bool``
    that returns True when the rule should fire.

    ``on_fire`` is a callable ``(event: Event, state: Dict[str, Any]) -> None``
    that emits a notification and/or updates state.
    """
    id: str = ""
    name: str = ""
    kind: str = RuleKind.CUSTOM_EVENT.value
    enabled: bool = True
    event_type: Optional[str] = None   # filter by EventType value
    source: Optional[str] = None       # filter by source
    level: Optional[str] = None        # filter by EventLevel value
    condition: Optional[Callable[[Event, Dict[str, Any]], bool]] = None
    on_fire: Optional[Callable[[Event, Dict[str, Any]], None]] = None
    # Running state across events (e.g. cumulative spend, aging timers)
    state: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            import uuid
            self.id = uuid.uuid4().hex

    def matches(self, event: Event) -> bool:
        if not self.enabled:
            return False
        if self.event_type and event.event_type != self.event_type:
            return False
        if self.source and event.source != self.source:
            return False
        if self.level and event.level != self.level:
            return False
        return True


# ── Predefined rule factories ────────────────────────────────────────────────

def llm_spend_threshold_rule(
    name: str = "LLM spend threshold (cloud only)",
    max_usd: float = 10.0,
    window_seconds: int = 3600,
    fire_once_per_window: bool = False,
    cloud_providers: Optional[List[str]] = None,
) -> AlertRule:
    """Fire when estimated LLM spend from cloud providers in the window
    exceeds max_usd.

    Local models (Ollama, llama.cpp, vLLM on local hardware, etc.) are
    free of API cost — only hardware and time — so their spend events are
    ignored by this rule. Pass the list of provider names that should count
    as "cloud" (i.e. metered API cost). The default covers the common cloud
    providers used in this project.
    """
    if cloud_providers is None:
        cloud_providers = [
            "nous", "openai", "anthropic", "google", "azure",
            "bedrock", "vertex", "cohere", "replicate", "huggingface",
            "together", "groq", "mistral", "xai", "deepseek",
        ]
    cloud_set = {p.lower() for p in cloud_providers}

    rid = f"llm_spend_cloud_{max_usd}_{window_seconds}"
    state: Dict[str, Any] = {
        "window_start": time.time(),
        "window_spend": 0.0,
        "fired_in_window": False,
        "cloud_providers": cloud_set,
    }

    def condition(ev: Event, st: Dict[str, Any]) -> bool:
        if ev.event_type not in (EventType.LLM_SPEND.value,):
            return False
        provider = str(ev.details.get("provider", "")).lower()
        if provider not in st["cloud_providers"]:
            # Local / free provider — skip counting toward the cloud budget.
            return False
        now = time.time()
        if now - st["window_start"] > window_seconds:
            st["window_start"] = now
            st["window_spend"] = 0.0
            st["fired_in_window"] = False
        est = float(ev.details.get("est_usd", 0.0))
        st["window_spend"] = st.get("window_spend", 0.0) + est
        return st["window_spend"] >= max_usd and not st.get("fired_in_window", False)

    def on_fire(ev: Event, st: Dict[str, Any]) -> None:
        st["fired_in_window"] = True
        notify(
            "Cloud LLM spend alert",
            f"Cloud spend ${st['window_spend']:.2f} exceeded "
            f"${max_usd:.2f} in the last {window_seconds // 60} min "
            f"(providers watched: {', '.join(sorted(st['cloud_providers']))}). "
            f"Local model usage is excluded from this budget.",
            level=NotifLevel.WARNING.value,
            source="alerting",
            sticky=False,
            payload={
                "rule": name,
                "spend": st["window_spend"],
                "limit": max_usd,
                "cloud_providers": sorted(st["cloud_providers"]),
            },
        )

    return AlertRule(
        id=rid,
        name=name,
        kind=RuleKind.LLM_SPEND_THRESHOLD.value,
        enabled=True,
        event_type=EventType.LLM_SPEND.value,
        condition=condition,
        on_fire=on_fire,
        state=state,
        tags=["llm_spend", "spend", "cloud"],
    )


def survival_tier_change_rule(
    name: str = "Survival tier change",
    critical_only: bool = False,
) -> AlertRule:
    """Fire on any survival tier change event from the event logger."""
    def condition(ev: Event, st: Dict[str, Any]) -> bool:
        if ev.event_type != EventType.HEARTBEAT.value:
            return False
        prev = st.get("last_tier")
        cur = ev.details.get("tier", "")
        if prev == cur:
            return False
        st["last_tier"] = cur
        if critical_only:
            return cur in ("LOW", "CRITICAL")
        return True

    def on_fire(ev: Event, st: Dict[str, Any]) -> None:
        tier = ev.details.get("tier", "unknown")
        notify(
            "Survival tier changed",
            f"Tier is now: {tier}",
            level=NotifLevel.WARNING.value if tier in ("LOW", "CRITICAL") else NotifLevel.INFO.value,
            source="alerting",
            sticky=tier in ("LOW", "CRITICAL"),
            payload={"tier": tier, "credits": ev.details.get("credits", 0.0)},
        )

    return AlertRule(
        id="survival_tier_change",
        name=name,
        kind=RuleKind.SURVIVAL_TIER_CHANGE.value,
        enabled=True,
        event_type=EventType.HEARTBEAT.value,
        condition=condition,
        on_fire=on_fire,
        state={},
        tags=["heartbeat", "tier"],
    )


def safety_block_rule(
    name: str = "Safety block",
) -> AlertRule:
    """Fire on any safety event where blocked=True."""
    def condition(ev: Event, st: Dict[str, Any]) -> bool:
        if ev.event_type != EventType.SAFETY.value:
            return False
        return bool(ev.details.get("blocked", False))

    def on_fire(ev: Event, st: Dict[str, Any]) -> None:
        gate = ev.details.get("gate_type", "unknown")
        desc = ev.details.get("description", "")
        notify(
            f"Safety block: {gate}",
            desc or f"{gate} blocked an action",
            level=NotifLevel.ERROR.value,
            source="alerting",
            sticky=True,
            payload={"gate_type": gate, "description": desc},
        )

    return AlertRule(
        id="safety_block",
        name=name,
        kind=RuleKind.SAFETY_BLOCK.value,
        enabled=True,
        event_type=EventType.SAFETY.value,
        condition=condition,
        on_fire=on_fire,
        state={},
        tags=["safety", "block"],
    )


def pending_approval_aging_rule(
    name: str = "Pending approval aging",
    max_age_seconds: int = 900,
) -> AlertRule:
    """Fire when a pending approval item has aged past max_age_seconds.

    Uses the HumanApprovalQueue if available; otherwise no-op.
    """
    def condition(ev: Event, st: Dict[str, Any]) -> bool:
        # Only re-evaluate on heartbeat ticks or manual refresh.
        # For simplicity, we treat any event as a trigger and re-check the queue.
        try:
            from agents.approval_queue import HumanApprovalQueue, ApprovalStatus
            q = HumanApprovalQueue.instance()
            now = time.time()
            for item in q.pending():
                age = now - item.requested_at
                if age >= max_age_seconds and not st.get(f"aged_{item.id}", False):
                    st[f"aged_{item.id}"] = True
                    st[f"tracked_{item.id}"] = item.requested_at
                    return True
                if item.status != ApprovalStatus.PENDING:
                    st.pop(f"aged_{item.id}", None)
                    st.pop(f"tracked_{item.id}", None)
            return False
        except Exception:
            return False

    def on_fire(ev: Event, st: Dict[str, Any]) -> None:
        try:
            from agents.approval_queue import HumanApprovalQueue
            q = HumanApprovalQueue.instance()
            now = time.time()
            for item in q.pending():
                age = now - item.requested_at
                if age >= max_age_seconds:
                    notify(
                        "Pending approval aging",
                        f"'{item.title}' has been pending for {age:.0f}s "
                        f"(limit {max_age_seconds}s).",
                        level=NotifLevel.WARNING.value,
                        source="alerting",
                        sticky=True,
                        payload={"item_id": item.id, "age": age,
                                 "max_age": max_age_seconds},
                    )
        except Exception:
            pass

    return AlertRule(
        id="pending_approval_aging",
        name=name,
        kind=RuleKind.PENDING_APPROVAL_AGING.value,
        enabled=True,
        condition=condition,
        on_fire=on_fire,
        state={},
        tags=["approval", "aging"],
    )


def earning_milestone_rule(
    name: str = "Earning milestone",
    target_total: float = 10.0,
    fire_once: bool = True,
) -> AlertRule:
    """Fire when cumulative earnings cross target_total."""
    state: Dict[str, Any] = {"total_earned": 0.0, "fired": False}

    def condition(ev: Event, st: Dict[str, Any]) -> bool:
        if ev.event_type != EventType.EARNING.value:
            return False
        rev = float(ev.details.get("revenue", 0.0))
        if rev <= 0:
            return False
        prev = st.get("total_earned", 0.0)
        st["total_earned"] = prev + rev
        if fire_once and st.get("fired", False):
            return False
        return (prev < target_total <= st["total_earned"]) or \
               (not fire_once and st["total_earned"] >= target_total)

    def on_fire(ev: Event, st: Dict[str, Any]) -> None:
        st["fired"] = True
        notify(
            "Earning milestone reached",
            f"Total earned: ${st['total_earned']:.2f} "
            f"(target was ${target_total:.2f})",
            level=NotifLevel.SUCCESS.value,
            source="alerting",
            sticky=False,
            payload={"total_earned": st["total_earned"], "target": target_total},
        )

    return AlertRule(
        id=f"earning_milestone_{target_total}",
        name=name,
        kind=RuleKind.EARNING_MILESTONE.value,
        enabled=True,
        event_type=EventType.EARNING.value,
        condition=condition,
        on_fire=on_fire,
        state=state,
        tags=["earning", "milestone"],
    )


# ── Rule engine ──────────────────────────────────────────────────────────────

class AlertRuleEngine:
    """Evaluates alert rules against the event log and fires notifications.

    Usage:
        engine = AlertRuleEngine.instance()
        engine.add_rule(llm_spend_threshold_rule(max_usd=10.0))
        engine.process_event(event)   # called from event logger hook / timer

    For desktop use, the engine can be polled on a timer (e.g. every few seconds)
    and/or hooked into the event logger's ``log`` method via a lightweight wrapper.
    """

    _instance: Optional["AlertRuleEngine"] = None
    _lock = None

    def __init__(self, log_path: Optional[str] = None):
        self._rules: List[AlertRule] = []
        self._log_path = log_path
        self._notif = NotificationService.instance()

    @classmethod
    def _get_lock(cls):
        import threading as _t
        if cls._lock is None:
            cls._lock = _t.Lock()
        return cls._lock

    @classmethod
    def instance(cls) -> "AlertRuleEngine":
        with cls._get_lock():
            if cls._instance is None:
                cls._instance = cls.__new__(cls)
                cls._instance.__init__()
            return cls._instance

    @classmethod
    def reset_singleton(cls):
        with cls._get_lock():
            cls._instance = None

    # ── Rule management ──────────────────────────────────────────────────────

    def add_rule(self, rule: AlertRule) -> AlertRule:
        self._rules.append(rule)
        return rule

    def add_rules(self, rules: List[AlertRule]) -> List[AlertRule]:
        self._rules.extend(rules)
        return self._rules

    def remove_rule(self, rule_id: str) -> bool:
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                self._rules.pop(i)
                return True
        return False

    def get_rules(self) -> List[AlertRule]:
        return list(self._rules)

    def enabled_rules(self) -> List[AlertRule]:
        return [r for r in self._rules if r.enabled]

    def enable_rule(self, rule_id: str, enabled: bool = True) -> bool:
        for r in self._rules:
            if r.id == rule_id:
                r.enabled = enabled
                return True
        return False

    # ── Processing ───────────────────────────────────────────────────────────

    def process_event(self, event: Event) -> List[str]:
        """Evaluate all rules against a single event.

        Returns list of rule IDs that fired.
        """
        fired: List[str] = []
        for rule in self.enabled_rules():
            if not rule.matches(event):
                continue
            try:
                if rule.condition and rule.condition(event, rule.state):
                    if rule.on_fire:
                        rule.on_fire(event, rule.state)
                    fired.append(rule.id)
            except Exception as e:
                logger.warning("rule %s evaluation failed: %s", rule.id, e)
        return fired

    def process_events(self, events: List[Event]) -> Dict[str, int]:
        """Process a batch of events and return per-rule fire counts."""
        counts: Dict[str, int] = {}
        for ev in events:
            for rid in self.process_event(ev):
                counts[rid] = counts.get(rid, 0) + 1
        return counts

    # ── Active state summary ─────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for the GUI."""
        total = len(self._rules)
        enabled = len(self.enabled_rules())
        rules_info = [
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind,
                "enabled": r.enabled,
                "tags": r.tags,
            }
            for r in self._rules
        ]
        return {
            "total_rules": total,
            "enabled_rules": enabled,
            "disabled_rules": total - enabled,
            "rules": rules_info,
            "last_updated": time.time(),
        }


# ── Module-level convenience ─────────────────────────────────────────────────

def add_default_rules():
    """Add the common desktop-app alerting rules."""
    engine = AlertRuleEngine.instance()
    engine.add_rules([
        llm_spend_threshold_rule(max_usd=10.0),
        survival_tier_change_rule(),
        safety_block_rule(),
        pending_approval_aging_rule(max_age_seconds=900),
        earning_milestone_rule(target_total=10.0),
    ])
    return engine.get_rules()


__all__ = [
    "AlertRule",
    "AlertRuleEngine",
    "RuleKind",
    "add_default_rules",
    "llm_spend_threshold_rule",
    "survival_tier_change_rule",
    "safety_block_rule",
    "pending_approval_aging_rule",
    "earning_milestone_rule",
]
