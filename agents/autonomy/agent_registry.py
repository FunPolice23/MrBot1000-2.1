"""agents/autonomy/agent_registry.py — Phase 5: Agent Registry.

Central registry for all autonomous agents (both brains + specialized
workers). Tracks capabilities, status, and workload distribution.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mrbot.autonomy.agent_registry")


class AgentStatus(Enum):
    STOPPED = "stopped"
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"


class CapabilityCategory(Enum):
    SCANNING = "scanning"
    ANALYSIS = "analysis"
    PROPOSAL = "proposal"
    SUBMISSION = "submission"
    PAYMENT = "payment"
    SAFETY = "safety"
    COMMUNICATION = "communication"
    LEARNING = "learning"


@dataclass
class CapabilitySpec:
    category: CapabilityCategory
    name: str
    version: str = "1.0.0"
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentSpec:
    """A registered agent definition."""

    agent_id: str = ""
    name: str = ""
    role: str = ""  # e.g. "small_brain", "big_brain", "worker"
    status: str = AgentStatus.STOPPED.value
    capabilities: List[CapabilitySpec] = field(default_factory=list)
    current_task: str = ""
    last_heartbeat: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0
    registered_at: float = 0.0
    lease_id: str = ""
    lease_expires_at: float = 0.0
    cancel_requested: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DelegationResult:
    task_id: str
    assigned: bool
    agent_id: str = ""
    lease_id: str = ""
    reason: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    matched_capabilities: List[str] = field(default_factory=list)


class AgentRegistry:
    """Central registry for all agents in the MrBot1000 system.

    Provides registration, discovery, workload assignment, and
    health checking.
    """

    def __init__(self, registry_path: Optional[str] = None):
        self.registry_path = registry_path
        self._agents: Dict[str, AgentSpec] = {}
        self._load()

    # ── Registration ────────────────────────────────────────────

    def register(
        self,
        name: str,
        role: str,
        capabilities: List[CapabilitySpec],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentSpec:
        """Register a new agent and return its spec."""
        agent_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).timestamp()
        spec = AgentSpec(
            agent_id=agent_id,
            name=name,
            role=role,
            status=AgentStatus.IDLE.value,
            capabilities=capabilities,
            last_heartbeat=now,
            tasks_completed=0,
            tasks_failed=0,
            registered_at=now,
            metadata=metadata or {},
        )
        self._agents[agent_id] = spec
        self._save()
        logger.info("Registered agent %s (%s) with %d capabilities", name, agent_id, len(capabilities))
        return spec

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            self._save()
            logger.info("Unregistered agent %s", agent_id)
            return True
        return False

    def heartbeat(self, agent_id: str) -> bool:
        """Record a heartbeat for an agent. Returns False if unknown."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        agent.last_heartbeat = datetime.now(timezone.utc).timestamp()
        if agent.status == AgentStatus.OFFLINE.value:
            agent.status = AgentStatus.IDLE.value
        self._save()
        return True

    # ── Discovery ───────────────────────────────────────────────

    def get_agent(self, agent_id: str) -> Optional[AgentSpec]:
        return self._agents.get(agent_id)

    def get_agents_by_role(self, role: str) -> List[AgentSpec]:
        return [a for a in self._agents.values() if a.role == role]

    def get_agents_by_capability(self, category: CapabilityCategory) -> List[AgentSpec]:
        return [
            a for a in self._agents.values()
            if any(c.category == category for c in a.capabilities)
        ]

    def get_all_agents(self) -> List[AgentSpec]:
        return list(self._agents.values())

    def get_idle_agents(self) -> List[AgentSpec]:
        return [a for a in self._agents.values() if a.status == AgentStatus.IDLE.value]

    def get_busy_agents(self) -> List[AgentSpec]:
        return [a for a in self._agents.values() if a.status == AgentStatus.BUSY.value]

    def delegate_task(self, task_id: str, required_capabilities: List[str] = None,
                      required_categories: List[CapabilityCategory] = None,
                      lease_seconds: float = 300.0) -> DelegationResult:
        """Assign work to the first idle agent matching every requirement."""
        required_names = sorted({str(name).lower() for name in (required_capabilities or [])})
        categories = set(required_categories or [])
        candidates = []
        for agent in self._agents.values():
            self._reclaim_expired(agent)
            if agent.status != AgentStatus.IDLE.value:
                continue
            names = {capability.name.lower() for capability in agent.capabilities}
            agent_categories = {capability.category for capability in agent.capabilities}
            if not set(required_names).issubset(names) or not categories.issubset(agent_categories):
                continue
            candidates.append((agent, names))

        if not candidates:
            requirements = required_names + [category.value for category in categories]
            return DelegationResult(
                task_id=task_id,
                assigned=False,
                reason="no idle agent satisfies all required capabilities",
                required_capabilities=requirements,
            )

        agent, names = sorted(candidates, key=lambda item: (
            item[0].tasks_failed, item[0].tasks_completed, item[0].agent_id))[0]
        if not self.assign_task(agent.agent_id, task_id, lease_seconds):
            return DelegationResult(
                task_id=task_id,
                assigned=False,
                reason="candidate became unavailable before lease assignment",
                required_capabilities=required_names,
            )
        assigned = self.get_agent(agent.agent_id)
        return DelegationResult(
            task_id=task_id,
            assigned=True,
            agent_id=agent.agent_id,
            lease_id=assigned.lease_id,
            reason="assigned to idle agent matching all requirements",
            required_capabilities=required_names + [category.value for category in categories],
            matched_capabilities=sorted(names.intersection(required_names)),
        )

    # ── Workload assignment ─────────────────────────────────────

    def assign_task(self, agent_id: str, task_id: str, lease_seconds: float = 300.0) -> bool:
        """Assign a task with an expiring lease. Returns False if unavailable."""
        agent = self._agents.get(agent_id)
        self._reclaim_expired(agent)
        if agent is None or agent.status == AgentStatus.BUSY.value:
            return False
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        agent.status = AgentStatus.BUSY.value
        agent.current_task = task_id
        agent.lease_id = uuid.uuid4().hex
        agent.lease_expires_at = time.time() + lease_seconds
        agent.cancel_requested = False
        self._save()
        logger.info("Assigned task %s to agent %s", task_id, agent_id)
        return True

    def renew_lease(self, agent_id: str, lease_id: str, lease_seconds: float = 300.0) -> bool:
        """Renew an owned, unexpired lease."""
        agent = self._agents.get(agent_id)
        if (agent is None or agent.status != AgentStatus.BUSY.value
                or agent.lease_id != lease_id or agent.lease_expires_at <= time.time()):
            self._reclaim_expired(agent)
            return False
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        agent.lease_expires_at = time.time() + lease_seconds
        agent.last_heartbeat = time.time()
        self._save()
        return True

    def request_cancellation(self, agent_id: str, lease_id: str) -> bool:
        """Request cooperative cancellation for the current lease."""
        agent = self._agents.get(agent_id)
        if agent is None or agent.lease_id != lease_id:
            return False
        agent.cancel_requested = True
        self._save()
        return True

    def is_cancellation_requested(self, agent_id: str, lease_id: str) -> bool:
        agent = self._agents.get(agent_id)
        return bool(agent and agent.lease_id == lease_id and agent.cancel_requested)

    def release_task(self, agent_id: str, lease_id: str) -> bool:
        """Release a task lease without recording success or failure."""
        agent = self._agents.get(agent_id)
        if agent is None or agent.lease_id != lease_id:
            return False
        self._clear_lease(agent)
        self._save()
        return True

    def complete_task(self, agent_id: str, success: bool = True, lease_id: str = "") -> bool:
        """Complete only the currently owned, unexpired lease."""
        agent = self._agents.get(agent_id)
        if agent is None or agent.status != AgentStatus.BUSY.value:
            return False
        if lease_id and agent.lease_id != lease_id:
            return False
        if agent.lease_expires_at and agent.lease_expires_at <= time.time():
            self._reclaim_expired(agent)
            return False
        self._clear_lease(agent)
        if success:
            agent.tasks_completed += 1
        else:
            agent.tasks_failed += 1
        self._save()
        return True

    @staticmethod
    def _clear_lease(agent: AgentSpec) -> None:
        agent.status = AgentStatus.IDLE.value
        agent.current_task = ""
        agent.lease_id = ""
        agent.lease_expires_at = 0.0
        agent.cancel_requested = False

    def _reclaim_expired(self, agent: Optional[AgentSpec]) -> None:
        if (agent is not None and agent.status == AgentStatus.BUSY.value
                and agent.lease_expires_at > 0 and agent.lease_expires_at <= time.time()):
            agent.tasks_failed += 1
            self._clear_lease(agent)

    # ── Health ──────────────────────────────────────────────────

    def check_health(self, stale_seconds: float = 300.0) -> Dict[str, Any]:
        """Check health of all agents. Returns summary dict."""
        now = datetime.now(timezone.utc).timestamp()
        healthy = []
        stale = []
        offline = []

        for agent in self._agents.values():
            self._reclaim_expired(agent)
            if agent.status == AgentStatus.OFFLINE.value:
                offline.append(agent.agent_id)
            elif now - agent.last_heartbeat > stale_seconds:
                stale.append(agent.agent_id)
                agent.status = AgentStatus.OFFLINE.value
            else:
                healthy.append(agent.agent_id)

        self._save()
        return {
            "healthy": healthy,
            "stale": stale,
            "offline": offline,
            "total": len(self._agents),
            "timestamp": now,
        }

    # ── Persistence ─────────────────────────────────────────────

    def _load(self) -> None:
        if not self.registry_path or not os.path.isfile(self.registry_path):
            return
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for aid, spec_data in data.get("agents", {}).items():
                caps = [
                    CapabilitySpec(**c) for c in spec_data.get("capabilities", [])
                ]
                spec = AgentSpec(
                    agent_id=aid,
                    name=spec_data.get("name", ""),
                    role=spec_data.get("role", ""),
                    status=spec_data.get("status", AgentStatus.STOPPED.value),
                    capabilities=caps,
                    last_heartbeat=spec_data.get("last_heartbeat", 0.0),
                    tasks_completed=spec_data.get("tasks_completed", 0),
                    tasks_failed=spec_data.get("tasks_failed", 0),
                    registered_at=spec_data.get("registered_at", 0.0),
                    lease_id=spec_data.get("lease_id", ""),
                    lease_expires_at=spec_data.get("lease_expires_at", 0.0),
                    cancel_requested=spec_data.get("cancel_requested", False),
                    metadata=spec_data.get("metadata", {}),
                )
                self._agents[aid] = spec
            logger.info("Loaded %d agents from registry", len(self._agents))
        except Exception as e:
            logger.error("Failed to load agent registry: %s", e)

    def _save(self) -> None:
        if not self.registry_path:
            return
        os.makedirs(os.path.dirname(self.registry_path) or ".", exist_ok=True)
        data = {
            "agents": {
                aid: {
                    "agent_id": a.agent_id,
                    "name": a.name,
                    "role": a.role,
                    "status": a.status,
                    "capabilities": [
                        {"category": c.category.value, "name": c.name, "version": c.version}
                        for c in a.capabilities
                    ],
                    "last_heartbeat": a.last_heartbeat,
                    "tasks_completed": a.tasks_completed,
                    "tasks_failed": a.tasks_failed,
                    "registered_at": a.registered_at,
                    "lease_id": a.lease_id,
                    "lease_expires_at": a.lease_expires_at,
                    "cancel_requested": a.cancel_requested,
                    "metadata": a.metadata,
                }
                for aid, a in self._agents.items()
            }
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


__all__ = [
    "AgentStatus",
    "CapabilityCategory",
    "CapabilitySpec",
    "AgentSpec",
    "DelegationResult",
    "AgentRegistry",
]
