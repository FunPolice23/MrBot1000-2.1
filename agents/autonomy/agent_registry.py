"""agents/autonomy/agent_registry.py — Phase 5: Agent Registry.

Central registry for all autonomous agents (both brains + specialized
workers). Tracks capabilities, status, and workload distribution.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
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
    metadata: Dict[str, Any] = field(default_factory=dict)


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

    # ── Workload assignment ─────────────────────────────────────

    def assign_task(self, agent_id: str, task_id: str) -> bool:
        """Assign a task to an agent. Returns False if agent not found or busy."""
        agent = self._agents.get(agent_id)
        if agent is None or agent.status == AgentStatus.BUSY.value:
            return False
        agent.status = AgentStatus.BUSY.value
        agent.current_task = task_id
        self._save()
        logger.info("Assigned task %s to agent %s", task_id, agent_id)
        return True

    def complete_task(self, agent_id: str, success: bool = True) -> bool:
        """Mark an agent's current task as complete."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        agent.status = AgentStatus.IDLE.value
        agent.current_task = ""
        if success:
            agent.tasks_completed += 1
        else:
            agent.tasks_failed += 1
        self._save()
        return True

    # ── Health ──────────────────────────────────────────────────

    def check_health(self, stale_seconds: float = 300.0) -> Dict[str, Any]:
        """Check health of all agents. Returns summary dict."""
        now = datetime.now(timezone.utc).timestamp()
        healthy = []
        stale = []
        offline = []

        for agent in self._agents.values():
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
    "AgentRegistry",
]
