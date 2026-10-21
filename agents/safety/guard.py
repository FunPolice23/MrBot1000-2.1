"""
agents/safety_guard.py — Multi-layer safety orchestrator (v2.1 Phase 3).

Central safety system that coordinates all safety layers:
1. CostGuard - Daily/weekly LLM spend limits
2. RecursionDetector - Infinite loop detection
3. ToolFirewall - Tool allow/deny lists
4. HumanApproval - Human sign-off for high-value actions
5. RateLimiter - Per-tool/per-provider rate limiting
6. ProviderCircuitBreaker - Fail-fast for dead providers (existing)

Each layer can block or flag an action independently. Any layer
vetoing means the action is blocked.
"""

import time
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum

from agents.safety.cost import CostGuard
from agents.safety.circuit import ProviderCircuitBreaker

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
    SAFE = "safe"               # No restrictions
    MONITOR = "monitor"         # Logged, no restriction
    WARN = "warn"               # Warned, requires acknowledgment
    BLOCK = "block"             # Blocked, needs override
    CRITICAL = "critical"       # Hard block, no override


@dataclass
class SafetyAction:
    """Represents an action to be checked."""
    action_type: str             # "tool_call", "api_call", "llm_call", etc.
    name: str                    # tool name or API endpoint
    arguments: Dict = field(default_factory=dict)
    estimated_cost: float = 0.0  # USD estimate
    platform: str = ""           # upwork, github, etc.
    requires_funds: bool = False # Does this spend money?
    metadata: Dict = field(default_factory=dict)


@dataclass
class SafetyResult:
    """Result of safety checks."""
    allowed: bool
    level: SafetyLevel
    action: str                  # "allow", "block", "flag", "rate_limited"
    reasons: List[str] = field(default_factory=list)
    layer: str = ""              # Which layer made the decision
    suggested_action: str = ""   # What the human should do
    
    @property
    def blocked(self) -> bool:
        return self.action in ("block", "rate_limited")
    
    @property
    def flagged(self) -> bool:
        return self.action == "flag"


# ── Safety Layers ────────────────────────────────────────────────────────

class SafetyLayer:
    """Base class for a single safety layer."""
    
    name: str = "base"
    priority: int = 50  # Higher = checked first
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self._enabled = self.config.get("enabled", True)
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        """Check an action. Returns None to pass to next layer."""
        raise NotImplementedError
    
    def reset(self):
        """Reset layer state."""
        pass


class CostGuardLayer(SafetyLayer):
    """Enforces daily/weekly LLM spend limits."""
    
    name = "cost_guard"
    priority = 100
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        budget = self.config.get("daily_budget_usd", 0)
        self.guard = CostGuard(daily_budget_usd=budget)
    
    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        if not self.enabled:
            return None
        
        # Only check LLM and billable API calls
        if action.action_type not in ("llm_call", "api_call"):
            return None
        
        db = self.config.get("database")
        if db is None:
            return None
        
        if self.guard.should_skip(db, action.name):
            return SafetyResult(
                allowed=False,
                level=SafetyLevel.BLOCK,
                action="block",
                reasons=[f"Daily budget exceeded (${self.guard.daily_budget_usd})"],
                layer=self.name,
                suggested_action="Wait until budget resets tomorrow"
            )
        
        return None


class RecursionDetectorLayer(SafetyLayer):
    """Detects and blocks recursive loops.

    Two distinct rules, and they need two distinct histories:

    * DEPTH — how many calls are in flight *right now*. This is genuine
      nesting, so ``check`` pushes and ``SafetyGuard.check`` pops when the
      action returns.
    * REPEATS — how many *identical* calls happened recently in sequence.
      This is temporal, not nested, so it must survive the pop.

    Both used to read one ``_call_stack`` that nothing ever popped, which
    coupled them wrongly in both directions. Reproduced before the fix: 11
    *distinct* submissions on one long-lived ``SafetyGuard()`` returned
    ``block / "Call depth exceeded: 10/10"`` — ordinary sequential work
    refused as a recursion loop, because the depth stack only ever grew.
    Naively adding the pop instead silently disabled the repeat rule (a pop
    after every check leaves nothing for it to count). Hence the split: the
    depth stack is bracketed and self-balancing, and repeats are counted from
    a separate bounded history of completed calls.
    """

    name = "recursion_detector"
    priority = 90

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.max_depth = self.config.get("max_depth", 10)
        self.timeout = self.config.get("timeout", 30)
        self.repeat_threshold = self.config.get("repeat_threshold", 3)
        self.repeat_window = self.config.get("repeat_window", 5)
        # Live nesting depth. Bracketed by SafetyGuard.check (push in check,
        # pop when the action returns).
        self._call_stack: List[Dict] = []
        # Completed calls, oldest first, pruned to the timeout window. This is
        # what the repeat rule counts; it deliberately outlives the pop.
        self._recent: List[Dict] = []
        self._lock = threading.Lock()

    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        if not self.enabled:
            return None

        with self._lock:
            now = time.time()

            # Check depth (concurrent nesting)
            if len(self._call_stack) >= self.max_depth:
                return SafetyResult(
                    allowed=False,
                    level=SafetyLevel.BLOCK,
                    action="block",
                    reasons=[f"Call depth exceeded: {len(self._call_stack)}/{self.max_depth}"],
                    layer=self.name,
                    suggested_action="Break the recursion loop or reduce depth"
                )

            # Check for repeated calls with same args (pattern detection).
            # Counted over recent COMPLETED calls, so it still fires for a
            # sequential loop — the case it exists for — without being
            # disabled by the depth pop.
            self._recent = [c for c in self._recent
                            if now - c["timestamp"] <= self.timeout]
            recent = [c for c in self._recent[-self.repeat_window:]
                      if c["name"] == action.name]
            if len(recent) >= self.repeat_threshold:
                return SafetyResult(
                    allowed=False,
                    level=SafetyLevel.BLOCK,
                    action="block",
                    reasons=[f"Repeated calls to '{action.name}' detected ({len(recent)}x)"],
                    layer=self.name,
                    suggested_action="Stop repeated calls or change parameters"
                )

            # Check timeout
            if self._call_stack:
                elapsed = now - self._call_stack[-1]["timestamp"]
                if elapsed > self.timeout:
                    return SafetyResult(
                        allowed=False,
                        level=SafetyLevel.BLOCK,
                        action="block",
                        reasons=[f"Call timeout exceeded: {elapsed:.1f}s/{self.timeout}s"],
                        layer=self.name,
                        suggested_action="Reduce operation complexity or increase timeout"
                    )

            # Push current call
            entry = {
                "name": action.name,
                "timestamp": now,
                "action": action.action_type,
            }
            self._call_stack.append(entry)

            return None

    def pop(self):
        """Retire the last in-flight call, recording it for the repeat rule."""
        with self._lock:
            if not self._call_stack:
                return
            entry = self._call_stack.pop()
            # Keep the repeat window bounded; a long session must not grow
            # without limit.
            if len(self._recent) >= self.repeat_window * 4:
                self._recent = self._recent[-(self.repeat_window * 2):]
            self._recent.append(entry)

    def reset(self):
        with self._lock:
            self._call_stack = []
            self._recent = []


class ToolFirewallLayer(SafetyLayer):
    """Enforces tool allow/deny lists.

    ARCH-ENG-257 (AE-01): the four runtime mutators (`add_to_denylist`,
    `add_to_allowlist`, `remove_from_denylist`, `remove_from_allowlist`)
    were deleted. The lists are fixed at construction from settings, so the
    setters advertised an editing capability nothing used.
    """
    
    name = "tool_firewall"
    priority = 80
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.allowlist = set(self.config.get("allowlist", []))
        self.denylist = set(self.config.get("denylist", []))
        self.default_allow = self.config.get("default_allow", True)
    
    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        if not self.enabled:
            return None
        
        if action.action_type != "tool_call":
            return None
        
        # Check denylist first (explicit deny)
        if action.name in self.denylist:
            return SafetyResult(
                allowed=False,
                level=SafetyLevel.BLOCK,
                action="block",
                reasons=[f"Tool '{action.name}' is on the denylist"],
                layer=self.name,
                suggested_action="Remove from denylist or use alternative tool"
            )
        
        # Check allowlist (if non-empty, only allow listed tools)
        if self.allowlist and action.name not in self.allowlist:
            return SafetyResult(
                allowed=False,
                level=SafetyLevel.BLOCK,
                action="block",
                reasons=[f"Tool '{action.name}' is not on the allowlist"],
                layer=self.name,
                suggested_action="Add to allowlist or use alternative tool"
            )
        
        return None
    
class HumanApprovalLayer(SafetyLayer):
    """Requires human approval for high-value actions.

    ARCH-ENG-258 (AE-03): `set_approval_callback` was deleted;
    `self._callback` was initialised to None and never assigned, while the
    layer enqueues directly into the shared `HumanApprovalQueue`.
    """
    
    name = "human_approval"
    priority = 70
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.threshold_usd = self.config.get("threshold_usd", 50.0)
        # approval_id -> the legacy pending dict (carries the SafetyAction).
        # The DECISION lives in HumanApprovalQueue; this map only remembers
        # which queued items this layer asked for, so get_pending() can scope
        # itself to its own requests instead of reporting the whole queue.
        self._owned: Dict[str, Dict] = {}
        self._owned_max = self.config.get("owned_max", 256)
        self._lock = threading.Lock()
        self._callback = None

    @property
    def pending_approvals(self) -> List[Dict]:
        """Back-compat view of this layer's still-pending requests."""
        return self.get_pending()

    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        if not self.enabled:
            return None
        
        # Check if action requires human approval
        needs_approval = False
        reasons = []
        
        if action.requires_funds:
            needs_approval = True
            reasons.append("Action requires funds")
        
        if action.estimated_cost >= self.threshold_usd:
            needs_approval = True
            reasons.append(f"Estimated cost ${action.estimated_cost:.2f} >= threshold ${self.threshold_usd:.2f}")
        
        # Platform-specific high-trust actions. The identity of the action may
        # arrive in EITHER field: ``agents.earning.platform_submitter`` and
        # ``agents.earning.real_crypto_operator`` both put the verb in
        # ``action_type`` and a descriptive label in ``name``. Matching only
        # ``name`` let a real submission request read as ``allow`` and
        # auto-approve an irreversible action. The two vocabularies do not
        # overlap (production action_types are tool_call/api_call/llm_call plus
        # these verbs), so checking both fields cannot misfire.
        high_trust_actions = {
            "submit_proposal", "post_comment", "send_message",
            "create_pr", "create_issue", "send_payment"
        }
        high_trust_hit = action.name in high_trust_actions or action.action_type in high_trust_actions
        if high_trust_hit:
            needs_approval = True
            label = action.name if action.name in high_trust_actions else action.action_type
            reasons.append(f"'{label}' is a high-trust action")
        
        if not needs_approval:
            return None

        # Queue for human approval. The authoritative queue is
        # HumanApprovalQueue — the one the GUI Approvals panel and
        # safety_tools_tab actually read. This layer used to keep its own
        # private list, so a submission it flagged appeared NOWHERE the
        # operator could approve it: the Approvals panel showed "No pending
        # approvals" while the submitter waited forever. Reproduced:
        # guard.check(submit_proposal) -> guard pending=1, queue pending=0.
        approval_id = f"approval_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        record = {
            "id": approval_id,
            "action": action,
            "reasons": reasons,
            "requested_at": time.time(),
            "status": "pending",
        }
        queued = self._enqueue_to_shared_queue(approval_id, action, reasons)
        with self._lock:
            self._owned[approval_id] = record
            self._prune_owned_locked()
            if not queued:
                # Queue unavailable: keep the local record so the request is
                # still visible to get_pending()/approve()/reject() rather
                # than silently vanishing.
                pass

        return SafetyResult(
            allowed=False,
            level=SafetyLevel.WARN,
            action="flag",
            reasons=reasons,
            layer=self.name,
            suggested_action=f"Approve or reject approval ID: {approval_id}"
        )

    def _enqueue_to_shared_queue(self, approval_id: str, action: SafetyAction,
                                 reasons: List[str]) -> bool:
        """Mirror this request into HumanApprovalQueue. Best-effort.

        Returns True when the item reached the shared queue. A failure here
        must not lose the request, so the caller keeps its local record.
        """
        try:
            from agents.safety.approval import (
                ApprovalItem,
                ApprovalKind,
                HumanApprovalQueue,
            )
            kind = ApprovalKind.ACTION
            verb = action.action_type if action.action_type in (
                "submit_proposal", "post_comment", "create_pr", "create_issue",
                "send_message") else ""
            if verb == "submit_proposal":
                kind = ApprovalKind.SUBMISSION
            elif action.action_type == "send_payment" or action.requires_funds:
                kind = ApprovalKind.PAYMENT
            item = ApprovalItem(
                id=approval_id,
                kind=kind,
                title=f"{action.action_type}: {action.name}",
                description="; ".join(reasons),
                requested_by="safety_guard",
                details={
                    "action_type": action.action_type,
                    "name": action.name,
                    "platform": action.platform,
                    "arguments": dict(action.arguments or {}),
                    "reasons": list(reasons),
                    "estimated_cost": action.estimated_cost,
                },
                payload={
                    "action_type": action.action_type,
                    "name": action.name,
                    "arguments": dict(action.arguments or {}),
                    "platform": action.platform,
                },
            )
            enqueued = HumanApprovalQueue.instance().enqueue(item)
            # enqueue() reassigns the id when it collides with an existing
            # item. Using the returned id keeps _owned and the queue keyed
            # identically; ignoring it would silently desync them.
            if enqueued.id != approval_id:
                with self._lock:
                    self._owned.pop(approval_id, None)
                return False
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("SafetyGuard could not enqueue approval: %s", exc)
            return False

    def _prune_owned_locked(self):
        """Drop decided records so _owned cannot grow without bound.

        The Earning tab holds one process-lifetime guard and the Safety & Tools
        tab polls get_pending() on a timer, so an ever-growing map of decided
        requests would be walked on every refresh forever.

        Only DECIDED records are dropped. A PENDING one is never pruned: it is
        an approval request a human has not answered yet, and losing it would
        lose the request itself. A long run of genuinely unanswered requests is
        therefore expected to grow the map — that is correct, not a leak.
        """
        if len(self._owned) <= self._owned_max:
            return
        stale = [k for k, v in self._owned.items()
                 if v.get("status") != "pending"]
        for key in stale[:len(self._owned) - self._owned_max]:
            self._owned.pop(key, None)

    def approve(self, approval_id: str) -> bool:
        """Approve a pending action."""
        with self._lock:
            record = self._owned.get(approval_id)
            if record is None or record.get("status") != "pending":
                return False
            record["status"] = "approved"
        decided = self._decide_in_shared_queue(approval_id, approved=True)
        if not decided:
            # The queue did not record the decision. Roll the local state back
            # so a caller that ignores the return value cannot mistake a failed
            # write for a human approval, and do not fire the callback.
            with self._lock:
                if record.get("status") == "approved":
                    record["status"] = "pending"
            return False
        if self._callback:
            try:
                self._callback(record, True)
            except Exception as exc:
                logger.error("approval callback failed: %s", exc)
        return True

    def reject(self, approval_id: str) -> bool:
        """Reject a pending action."""
        with self._lock:
            record = self._owned.get(approval_id)
            if record is None or record.get("status") != "pending":
                return False
            record["status"] = "rejected"
        decided = self._decide_in_shared_queue(approval_id, approved=False)
        if not decided:
            with self._lock:
                if record.get("status") == "rejected":
                    record["status"] = "pending"
            return False
        if self._callback:
            try:
                self._callback(record, False)
            except Exception as exc:
                logger.error("rejection callback failed: %s", exc)
        return True

    def _decide_in_shared_queue(self, approval_id: str, approved: bool) -> bool:
        """Record the human's decision in the shared queue, if we mirrored it."""
        try:
            from agents.safety.approval import HumanApprovalQueue
            queue = HumanApprovalQueue.instance()
            item = queue.find_by_id(approval_id)
            if item is None:
                return False
            if approved:
                return queue.approve(approval_id, notes="Approved via SafetyGuard")
            return queue.deny(approval_id, notes="Rejected via SafetyGuard")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("SafetyGuard could not record decision: %s", exc)
            return False

    def get_pending(self) -> List[Dict]:
        """Get all pending approvals.

        Sourced from HumanApprovalQueue (the operator-visible queue) and
        scoped to the requests this layer raised, so the legacy dict shape
        callers depend on is preserved while the decision state stays in one
        place.
        """
        try:
            from agents.safety.approval import (
                ApprovalStatus,
                HumanApprovalQueue,
            )
            queue = HumanApprovalQueue.instance()
            by_id = {i.id: i for i in queue.all()}
        except Exception:
            by_id = {}
        with self._lock:
            owned = list(self._owned.items())
        pending: List[Dict] = []
        for approval_id, record in owned:
            if record.get("status") != "pending":
                continue
            item = by_id.get(approval_id)
            if item is not None and item.status != ApprovalStatus.PENDING:
                # Decided in the GUI queue: mirror it back so a second
                # approve() cannot run the same action twice.
                record["status"] = ("approved"
                                    if item.status == ApprovalStatus.APPROVED
                                    else "rejected")
                continue
            pending.append(record)
        if len(self._owned) > self._owned_max:
            self._prune_owned_locked()
        return pending


class RateLimiterLayer(SafetyLayer):
    """Rate limiting per tool and per provider.

    ARCH-ENG-259 (AE-04): `get_remaining` and the orchestration wrapper
    `check_and_raise` had zero callers and were deleted; callers inspect the
    `SafetyDecision` returned by `check`.
    """
    
    name = "rate_limiter"
    priority = 60
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.tool_limits: Dict[str, int] = config.get("tool_limits", {})
        self.provider_limits: Dict[str, int] = config.get("provider_limits", {})
        self.default_limit = config.get("default_limit_per_minute", 60)
        self._tool_counters: Dict[str, List[float]] = {}
        self._provider_counters: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
    
    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        if not self.enabled:
            return None
        
        now = time.time()
        with self._lock:
            # Check tool rate limit
            if action.action_type == "tool_call":
                limit = self.tool_limits.get(action.name, self.default_limit)
                if not self._check_rate(self._tool_counters, action.name, now, limit):
                    return SafetyResult(
                        allowed=False,
                        level=SafetyLevel.BLOCK,
                        action="rate_limited",
                        reasons=[f"Rate limit exceeded for tool '{action.name}' ({limit}/min)"],
                        layer=self.name,
                        suggested_action="Wait before retrying"
                    )
            
            # Check provider rate limit
            if action.action_type == "api_call" and action.platform:
                limit = self.provider_limits.get(action.platform, self.default_limit)
                if not self._check_rate(self._provider_counters, action.platform, now, limit):
                    return SafetyResult(
                        allowed=False,
                        level=SafetyLevel.BLOCK,
                        action="rate_limited",
                        reasons=[f"Rate limit exceeded for platform '{action.platform}' ({limit}/min)"],
                        layer=self.name,
                        suggested_action="Wait before retrying"
                    )
        
        return None
    
    def _check_rate(self, counters: Dict[str, List[float]], key: str, now: float, limit: int) -> bool:
        """Check if a call is within rate limit."""
        if key not in counters:
            counters[key] = []
        
        # Remove entries older than 60 seconds
        counters[key] = [t for t in counters[key] if now - t < 60]
        
        if len(counters[key]) >= limit:
            return False
        
        counters[key].append(now)
        return True
    
# ── Safety Guard Orchestrator ────────────────────────────────────────────

class SafetyGuard:
    """Central safety orchestrator. Checks all layers."""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.layers: List[SafetyLayer] = []
        self.circuit_breaker = ProviderCircuitBreaker()
        self._setup_layers()
    
    def _setup_layers(self):
        """Initialize all safety layers."""
        # Cost guard
        if self.config.get("cost_guard", {}).get("enabled", True):
            self.layers.append(CostGuardLayer(self.config.get("cost_guard", {})))
        
        # Recursion detector
        if self.config.get("recursion_detector", {}).get("enabled", True):
            self.layers.append(RecursionDetectorLayer(self.config.get("recursion_detector", {})))
        
        # Tool firewall
        if self.config.get("tool_firewall", {}).get("enabled", True):
            self.layers.append(ToolFirewallLayer(self.config.get("tool_firewall", {})))
        
        # Human approval
        if self.config.get("human_approval", {}).get("enabled", True):
            self.layers.append(HumanApprovalLayer(self.config.get("human_approval", {})))
        
        # Rate limiter
        if self.config.get("rate_limiter", {}).get("enabled", True):
            self.layers.append(RateLimiterLayer(self.config.get("rate_limiter", {})))
        
        # Sort by priority (highest first)
        self.layers.sort(key=lambda l: l.priority, reverse=True)
    
    def check(self, action: SafetyAction) -> SafetyResult:
        """Run all safety layers on an action."""
        for layer in self.layers:
            try:
                result = layer.check(action)
            except Exception as e:
                logger.error(f"Safety layer '{layer.name}' error: {e}")
                # Fail safe: block on layer error
                return SafetyResult(
                    allowed=False,
                    level=SafetyLevel.BLOCK,
                    action="block",
                    reasons=[f"Safety layer '{layer.name}' failed: {e}"],
                    layer=layer.name,
                    suggested_action="Review safety configuration"
                )
            finally:
                # The recursion detector models NESTED depth: check() pushes,
                # and the caller must pop. Nothing outside the layer ever
                # called pop(), so on a long-lived guard the stack only grew
                # and every later action was refused as a recursion loop
                # ("Call depth exceeded: 10/10"). Bracketing the call here
                # makes the layer self-balancing regardless of caller.
                pop = getattr(layer, "pop", None)
                if callable(pop):
                    try:
                        pop()
                    except Exception as e:
                        logger.error(f"Safety layer '{layer.name}' pop failed: {e}")
            if result is not None:
                return result

        # All layers passed
        return SafetyResult(
            allowed=True,
            level=SafetyLevel.SAFE,
            action="allow",
            reasons=[],
            layer="all",
            suggested_action=""
        )
    
    def get_layer(self, name: str) -> Optional[SafetyLayer]:
        """Get a specific safety layer by name."""
        for layer in self.layers:
            if layer.name == name:
                return layer
        return None
    
    def get_status(self) -> Dict:
        """Get status of all safety layers."""
        return {
            "layers": [
                {
                    "name": layer.name,
                    "enabled": layer.enabled,
                    "priority": layer.priority,
                }
                for layer in self.layers
            ],
            "total_layers": len(self.layers),
            "circuit_breaker": {
                "enabled": True,
            },
        }
    
    def reset(self):
        """Reset all layers."""
        for layer in self.layers:
            layer.reset()
    
    def get_pending_approvals(self) -> List[Dict]:
        """Get pending human approvals."""
        layer = self.get_layer("human_approval")
        if isinstance(layer, HumanApprovalLayer):
            return layer.get_pending()
        return []
    
    def approve(self, approval_id: str) -> bool:
        """Approve a pending action."""
        layer = self.get_layer("human_approval")
        if isinstance(layer, HumanApprovalLayer):
            return layer.approve(approval_id)
        return False
    
    def reject(self, approval_id: str) -> bool:
        """Reject a pending action."""
        layer = self.get_layer("human_approval")
        if isinstance(layer, HumanApprovalLayer):
            return layer.reject(approval_id)
        return False


class SafetyViolation(Exception):
    """Raised when a safety check blocks an action."""
    
    def __init__(self, result: SafetyResult):
        self.result = result
        super().__init__(f"Safety violation: {', '.join(result.reasons)}")
