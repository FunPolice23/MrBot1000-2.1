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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum

from agents.cost_guard import CostGuard
from agents.circuit_breaker import ProviderCircuitBreaker

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
    """Detects and blocks recursive loops."""
    
    name = "recursion_detector"
    priority = 90
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.max_depth = self.config.get("max_depth", 10)
        self.timeout = self.config.get("timeout", 30)
        self._call_stack: List[Dict] = []
        self._lock = threading.Lock()
    
    def check(self, action: SafetyAction) -> Optional[SafetyResult]:
        if not self.enabled:
            return None
        
        with self._lock:
            now = time.time()
            
            # Check depth
            if len(self._call_stack) >= self.max_depth:
                return SafetyResult(
                    allowed=False,
                    level=SafetyLevel.BLOCK,
                    action="block",
                    reasons=[f"Call depth exceeded: {len(self._call_stack)}/{self.max_depth}"],
                    layer=self.name,
                    suggested_action="Break the recursion loop or reduce depth"
                )
            
            # Check for repeated calls with same args (pattern detection)
            recent = [c for c in self._call_stack[-5:] if c["name"] == action.name]
            if len(recent) >= 3:
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
            self._call_stack.append({
                "name": action.name,
                "timestamp": now,
                "action": action.action_type,
            })
            
            return None
    
    def pop(self):
        """Pop the last call from the stack."""
        with self._lock:
            if self._call_stack:
                self._call_stack.pop()
    
    def reset(self):
        with self._lock:
            self._call_stack = []


class ToolFirewallLayer(SafetyLayer):
    """Enforces tool allow/deny lists."""
    
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
    
    def add_to_denylist(self, tool_name: str):
        self.denylist.add(tool_name)
    
    def add_to_allowlist(self, tool_name: str):
        self.allowlist.add(tool_name)
    
    def remove_from_denylist(self, tool_name: str):
        self.denylist.discard(tool_name)
    
    def remove_from_allowlist(self, tool_name: str):
        self.allowlist.discard(tool_name)


class HumanApprovalLayer(SafetyLayer):
    """Requires human approval for high-value actions."""
    
    name = "human_approval"
    priority = 70
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.threshold_usd = self.config.get("threshold_usd", 50.0)
        self.pending_approvals: List[Dict] = []
        self._lock = threading.Lock()
        self._callback = None
    
    def set_approval_callback(self, callback: Callable):
        """Set callback for when human approves/rejects."""
        self._callback = callback
    
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
        
        # Platform-specific high-trust actions
        high_trust_actions = {
            "submit_proposal", "post_comment", "send_message",
            "create_pr", "create_issue", "send_payment"
        }
        if action.name in high_trust_actions:
            needs_approval = True
            reasons.append(f"'{action.name}' is a high-trust action")
        
        if not needs_approval:
            return None
        
        # Queue for human approval
        with self._lock:
            approval_id = f"approval_{int(time.time()*1000)}"
            approval = {
                "id": approval_id,
                "action": action,
                "reasons": reasons,
                "requested_at": time.time(),
                "status": "pending",
            }
            self.pending_approvals.append(approval)
        
        return SafetyResult(
            allowed=False,
            level=SafetyLevel.WARN,
            action="flag",
            reasons=reasons,
            layer=self.name,
            suggested_action=f"Approve or reject approval ID: {approval_id}"
        )
    
    def approve(self, approval_id: str) -> bool:
        """Approve a pending action."""
        with self._lock:
            for approval in self.pending_approvals:
                if approval["id"] == approval_id:
                    approval["status"] = "approved"
                    if self._callback:
                        self._callback(approval, True)
                    return True
        return False
    
    def reject(self, approval_id: str) -> bool:
        """Reject a pending action."""
        with self._lock:
            for approval in self.pending_approvals:
                if approval["id"] == approval_id:
                    approval["status"] = "rejected"
                    if self._callback:
                        self._callback(approval, False)
                    return True
        return False
    
    def get_pending(self) -> List[Dict]:
        """Get all pending approvals."""
        with self._lock:
            return [a for a in self.pending_approvals if a["status"] == "pending"]


class RateLimiterLayer(SafetyLayer):
    """Rate limiting per tool and per provider."""
    
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
    
    def get_remaining(self, key: str, limit: int = None) -> int:
        """Get remaining calls for a key."""
        now = time.time()
        with self._lock:
            counters = self._tool_counters.get(key, []) + self._provider_counters.get(key, [])
            recent = [t for t in counters if now - t < 60]
            return max(0, (limit or self.default_limit) - len(recent))


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
                if result is not None:
                    return result
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
        
        # All layers passed
        return SafetyResult(
            allowed=True,
            level=SafetyLevel.SAFE,
            action="allow",
            reasons=[],
            layer="all",
            suggested_action=""
        )
    
    def check_and_raise(self, action: SafetyAction):
        """Check and raise SafetyViolation if blocked."""
        result = self.check(action)
        if result.blocked:
            raise SafetyViolation(result)
        return result
    
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
