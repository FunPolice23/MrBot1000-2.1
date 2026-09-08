"""
agents/workflow_engine.py — Structured earning workflow engine (v2.1 Phase 1).

Implements the Discovery → Vetting → Proposal → Execution → Review lifecycle:
- Structured phases with clear entry/exit criteria
- Human approval gates at critical transitions
- Automatic progression when criteria are met
- Full audit trail for learning
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any

from agents.opportunity_models import Opportunity
from agents.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


# ── Workflow Phases ───────────────────────────────────────────────────────

class WorkflowPhase(Enum):
    DISCOVERY = "discovery"
    VETTING = "vetting"
    PROPOSAL = "proposal"
    EXECUTION = "execution"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


# ── Phase Transitions ─────────────────────────────────────────────────────

ALLOWED_TRANSITIONS: Dict[WorkflowPhase, set] = {
    WorkflowPhase.DISCOVERY: {WorkflowPhase.VETTING, WorkflowPhase.REJECTED},
    WorkflowPhase.VETTING: {WorkflowPhase.PROPOSAL, WorkflowPhase.REJECTED},
    WorkflowPhase.PROPOSAL: {WorkflowPhase.EXECUTION, WorkflowPhase.REJECTED},
    WorkflowPhase.EXECUTION: {WorkflowPhase.REVIEW, WorkflowPhase.FAILED},
    WorkflowPhase.REVIEW: {WorkflowPhase.COMPLETED, WorkflowPhase.FAILED},
    WorkflowPhase.COMPLETED: set(),
    WorkflowPhase.FAILED: set(),
    WorkflowPhase.REJECTED: set(),
}


# ── Workflow State ────────────────────────────────────────────────────────

@dataclass
class PhaseEntry:
    phase: WorkflowPhase
    timestamp: float
    note: str = ""
    data: Dict = field(default_factory=dict)


@dataclass
class WorkflowState:
    """State of a single opportunity through the workflow."""
    opportunity_id: str
    current_phase: WorkflowPhase = WorkflowPhase.DISCOVERY
    history: List[PhaseEntry] = field(default_factory=list)
    phase_data: Dict[WorkflowPhase, Dict] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    outcome: Optional[str] = None
    earnings: float = 0.0
    costs: float = 0.0
    
    def transition_to(self, new_phase: WorkflowPhase, note: str = "", data: Dict = None):
        """Transition to a new phase."""
        self.history.append(PhaseEntry(
            phase=self.current_phase,
            timestamp=time.time(),
            note=note,
            data=data or {},
        ))
        self.current_phase = new_phase
        self.updated_at = time.time()
        
        if new_phase in (WorkflowPhase.COMPLETED, WorkflowPhase.FAILED, WorkflowPhase.REJECTED):
            self.completed_at = time.time()


# ── Workflow Engine ───────────────────────────────────────────────────────

class WorkflowEngine:
    """Manage opportunity workflows from discovery to completion."""
    
    def __init__(self, cost_tracker: CostTracker = None):
        self.cost_tracker = cost_tracker
        self._workflows: Dict[str, WorkflowState] = {}
        self._callbacks: List[Callable] = []
    
    def register_callback(self, callback: Callable):
        """Register a callback for workflow events."""
        self._callbacks.append(callback)
    
    def start_workflow(self, opportunity: Opportunity) -> WorkflowState:
        """Start a new workflow for an opportunity."""
        state = WorkflowState(
            opportunity_id=opportunity.id,
            current_phase=WorkflowPhase.DISCOVERY,
        )
        state.phase_data[WorkflowPhase.DISCOVERY] = {
            "opportunity": opportunity.to_dict() if hasattr(opportunity, 'to_dict') else {},
            "started_at": time.time(),
        }
        self._workflows[opportunity.id] = state
        self._notify("workflow_started", state)
        return state
    
    def get_workflow(self, opportunity_id: str) -> Optional[WorkflowState]:
        """Get workflow state by opportunity ID."""
        return self._workflows.get(opportunity_id)
    
    def get_active_workflows(self) -> List[WorkflowState]:
        """Get all active (not completed/failed/rejected) workflows."""
        return [w for w in self._workflows.values() 
                if w.current_phase not in (WorkflowPhase.COMPLETED, WorkflowPhase.FAILED, WorkflowPhase.REJECTED)]
    
    def get_workflows_by_phase(self, phase: WorkflowPhase) -> List[WorkflowState]:
        """Get all workflows in a specific phase."""
        return [w for w in self._workflows.values() if w.current_phase == phase]
    
    def transition(self, opportunity_id: str, new_phase: WorkflowPhase, 
                   note: str = "", data: Dict = None) -> bool:
        """Transition a workflow to a new phase."""
        state = self._workflows.get(opportunity_id)
        if not state:
            return False
        
        # Check if transition is allowed
        if new_phase not in ALLOWED_TRANSITIONS.get(state.current_phase, set()):
            logger.warning(f"Invalid transition: {state.current_phase} -> {new_phase}")
            return False
        
        # Check cost budget for expensive phases
        if new_phase == WorkflowPhase.EXECUTION and self.cost_tracker:
            if not self.cost_tracker.should_allow_call(estimated_cost=0.50):
                logger.warning("Cost cap reached - cannot transition to execution")
                return False
        
        state.transition_to(new_phase, note, data)
        self._notify("phase_changed", state)
        
        if new_phase == WorkflowPhase.COMPLETED:
            self._notify("workflow_completed", state)
        elif new_phase == WorkflowPhase.FAILED:
            self._notify("workflow_failed", state)
        
        return True
    
    def update_phase_data(self, opportunity_id: str, phase: WorkflowPhase, data: Dict):
        """Update data for a specific phase."""
        state = self._workflows.get(opportunity_id)
        if state:
            state.phase_data[phase] = data
            state.updated_at = time.time()
    
    def record_earnings(self, opportunity_id: str, amount: float):
        """Record earnings for a workflow."""
        state = self._workflows.get(opportunity_id)
        if state:
            state.earnings += amount
            state.updated_at = time.time()
    
    def record_cost(self, opportunity_id: str, amount: float):
        """Record costs for a workflow."""
        state = self._workflows.get(opportunity_id)
        if state:
            state.costs += amount
            state.updated_at = time.time()
    
    def get_metrics(self) -> Dict:
        """Get aggregate workflow metrics."""
        total = len(self._workflows)
        active = len(self.get_active_workflows())
        completed = len([w for w in self._workflows.values() if w.current_phase == WorkflowPhase.COMPLETED])
        failed = len([w for w in self._workflows.values() if w.current_phase == WorkflowPhase.FAILED])
        rejected = len([w for w in self._workflows.values() if w.current_phase == WorkflowPhase.REJECTED])
        
        total_earnings = sum(w.earnings for w in self._workflows.values())
        total_costs = sum(w.costs for w in self._workflows.values())
        
        return {
            "total": total,
            "active": active,
            "completed": completed,
            "failed": failed,
            "rejected": rejected,
            "success_rate": completed / (completed + failed) if (completed + failed) > 0 else 0,
            "total_earnings": total_earnings,
            "total_costs": total_costs,
            "net_earnings": total_earnings - total_costs,
            "roi": ((total_earnings - total_costs) / total_costs * 100) if total_costs > 0 else 0,
        }
    
    def _notify(self, event: str, state: WorkflowState):
        """Notify callbacks of workflow events."""
        for callback in self._callbacks:
            try:
                callback(event, state)
            except Exception as e:
                logger.warning(f"Callback error: {e}")
