"""
shared_context.py — Cross-model communication layer for MrBot1000

Provides a shared "workspace" where both main and chat models can:
- Read each other's decisions and reasoning
- Coordinate actions across subagents
- Maintain a persistent conversation context
- Pass tasks, results, and state updates

This enables genuine multi-model collaboration where the chat model
can understand what the main model decided, and vice versa.
"""

import json
import os
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict

# Shared context file location
SHARED_CONTEXT_PATH = Path.home() / ".local" / "share" / "mrbot1000" / "shared_context.json"

@dataclass
class ModelContext:
    """Context entry for a specific model"""
    model_name: str
    timestamp: float = field(default_factory=time.time)
    current_task: str = ""
    reasoning_chain: List[str] = field(default_factory=list)
    key_decisions: List[Dict] = field(default_factory=list)
    pending_actions: List[str] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)

@dataclass  
class SharedState:
    """Global shared state across all models and agents"""
    version: int = 1
    last_updated: float = field(default_factory=time.time)
    models: Dict[str, ModelContext] = field(default_factory=dict)
    global_tasks: List[Dict] = field(default_factory=list)
    recent_events: List[Dict] = field(default_factory=list)
    cross_model_signals: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        result = {"version": self.version, "last_updated": self.last_updated}
        result["models"] = {}
        for name, ctx in self.models.items():
            result["models"][name] = {
                "model_name": ctx.model_name,
                "timestamp": ctx.timestamp,
                "current_task": ctx.current_task,
                "reasoning_chain": ctx.reasoning_chain,
                "key_decisions": ctx.key_decisions,
                "pending_actions": ctx.pending_actions,
                "results": ctx.results,
            }
        result["global_tasks"] = self.global_tasks
        result["recent_events"] = self.recent_events[-100:]  # Keep last 100
        result["cross_model_signals"] = self.cross_model_signals[-50:]  # Keep last 50
        return result

class SharedContext:
    """
    Thread-safe shared context for cross-model communication.
    Both main and chat models read/write here to coordinate.
    """
    
    def __init__(self, path: str = None):
        self._path = Path(path or SHARED_CONTEXT_PATH)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        with self._lock:
            if not self._path.exists():
                self._write_state(SharedState())
    
    def _read_state(self) -> SharedState:
        with self._lock:
            return self._read_state_unlocked()

    def _read_state_unlocked(self) -> SharedState:
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            state = SharedState(version=data.get("version", 1))
            state.last_updated = data.get("last_updated", time.time())
            state.global_tasks = data.get("global_tasks", [])
            state.recent_events = data.get("recent_events", [])
            state.cross_model_signals = data.get("cross_model_signals", [])

            for name, ctx_data in data.get("models", {}).items():
                state.models[name] = ModelContext(
                    model_name=ctx_data.get("model_name", name),
                    timestamp=ctx_data.get("timestamp", time.time()),
                    current_task=ctx_data.get("current_task", ""),
                    reasoning_chain=ctx_data.get("reasoning_chain", []),
                    key_decisions=ctx_data.get("key_decisions", []),
                    pending_actions=ctx_data.get("pending_actions", []),
                    results=ctx_data.get("results", {}),
                )
            return state
        except (FileNotFoundError, json.JSONDecodeError):
            return SharedState()
    
    def _write_state(self, state: SharedState):
        with self._lock:
            self._write_state_unlocked(state)

    def _write_state_unlocked(self, state: SharedState):
        state.last_updated = time.time()
        payload = json.dumps(state.to_dict(), indent=2)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self._path)
    
    # ── Model Context Management ───────────────────────────────────────
    
    def update_model_context(self, model_name: str, **kwargs):
        """Update context for a specific model"""
        with self._lock:
            state = self._read_state_unlocked()

            if model_name not in state.models:
                state.models[model_name] = ModelContext(model_name=model_name)

            ctx = state.models[model_name]
            ctx.model_name = model_name
            ctx.timestamp = time.time()

            for key, value in kwargs.items():
                if hasattr(ctx, key):
                    current = getattr(ctx, key)
                    if isinstance(current, list) and isinstance(value, list):
                        current.extend(value)
                        setattr(ctx, key, current)
                    elif isinstance(current, dict) and isinstance(value, dict):
                        current.update(value)
                        setattr(ctx, key, current)
                    else:
                        setattr(ctx, key, value)

            self._write_state_unlocked(state)
    
    def get_model_context(self, model_name: str) -> Optional[ModelContext]:
        """Get context for a specific model"""
        state = self._read_state()
        return state.models.get(model_name)
    
    def get_all_model_contexts(self) -> Dict[str, ModelContext]:
        """Get contexts for all models"""
        state = self._read_state()
        return state.models
    
    # ── Task Management ────────────────────────────────────────────────
    
    def add_global_task(self, task: str, assignee: str = None, priority: int = 5):
        """Add a cross-model task"""
        with self._lock:
            state = self._read_state_unlocked()
            task_obj = {
                "id": f"task_{int(time.time()*1000)}",
                "task": task,
                "assignee": assignee,
                "priority": priority,
                "created": time.time(),
                "status": "pending"
            }
            state.global_tasks.append(task_obj)
            self._write_state_unlocked(state)
            return task_obj["id"]
    
    def get_pending_tasks(self, model_name: str = None) -> List[Dict]:
        """Get pending tasks for a model or all pending tasks"""
        state = self._read_state()
        tasks = [t for t in state.global_tasks if t["status"] == "pending"]
        if model_name:
            tasks = [t for t in tasks if t["assignee"] == model_name or t["assignee"] is None]
        return tasks
    
    def complete_task(self, task_id: str, result: str = ""):
        """Mark a task as completed"""
        with self._lock:
            state = self._read_state_unlocked()
            for task in state.global_tasks:
                if task["id"] == task_id:
                    task["status"] = "completed"
                    task["result"] = result
                    task["completed"] = time.time()
                    break
            self._write_state_unlocked(state)
    
    # ── Event & Signal System ────────────────────────────────────────────
    
    def add_event(self, event_type: str, source: str, data: dict):
        """Log a cross-model event"""
        with self._lock:
            state = self._read_state_unlocked()
            event = {
                "type": event_type,
                "source": source,
                "data": data,
                "timestamp": time.time()
            }
            state.recent_events.append(event)
            self._write_state_unlocked(state)
    
    def add_signal(self, from_model: str, to_model: str, message: str, data: dict = None):
        """Send a signal from one model to another"""
        with self._lock:
            state = self._read_state_unlocked()
            signal = {
                "from": from_model,
                "to": to_model,
                "message": message,
                "data": data or {},
                "timestamp": time.time()
            }
            state.cross_model_signals.append(signal)
            self._write_state_unlocked(state)
    
    def get_signals(self, model_name: str, limit: int = 10) -> List[Dict]:
        """Get signals intended for a model"""
        state = self._read_state()
        signals = [s for s in state.cross_model_signals 
                   if s["to"] == model_name or s["to"] == "all"]
        return signals[-limit:]

    def update_opportunity_lifecycle(self, opportunity_id: str, current_stage: str = "discovered",
                                      status: str = "active", last_amount: float = 0.0,
                                      note: str = "") -> Dict[str, Any]:
        """Persist a lifecycle snapshot for an opportunity in shared context."""
        with self._lock:
            state = self._read_state_unlocked()
            snapshot = {
                "opportunity_id": opportunity_id,
                "current_stage": current_stage,
                "status": status,
                "last_amount": last_amount,
                "note": note,
                "timestamp": time.time(),
            }
            state.recent_events.append({
                "type": "opportunity_lifecycle",
                "source": "shared_context",
                "data": snapshot,
                "timestamp": snapshot["timestamp"],
            })
            self._write_state_unlocked(state)
            return snapshot

    def update_research_snapshot(self, research: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a compact research snapshot so both models can reuse it."""
        with self._lock:
            state = self._read_state_unlocked()
            payload = {
                "research_path": research.get("research_path"),
                "research_file_count": research.get("research_file_count", 0),
                "root_excerpt": (research.get("root") or "")[:4000],
                "research_excerpt": (research.get("research") or "")[:4000],
                "timestamp": time.time(),
            }
            state.recent_events.append({
                "type": "research_snapshot",
                "source": "shared_context",
                "data": payload,
                "timestamp": payload["timestamp"],
            })
            self._write_state_unlocked(state)
            return payload

    def get_latest_research_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the latest shared research snapshot, if available."""
        state = self._read_state()
        snapshots = [event["data"] for event in state.recent_events if event.get("type") == "research_snapshot"]
        return snapshots[-1] if snapshots else None

    def get_opportunity_lifecycle(self) -> List[Dict[str, Any]]:
        """Return recent opportunity lifecycle snapshots."""
        state = self._read_state()
        return [
            event["data"] for event in state.recent_events
            if event.get("type") == "opportunity_lifecycle"
        ][-20:]
    
    # ── High-Level Coordination ────────────────────────────────────────
    
    def query_model(self, model_name: str, question: str) -> str:
        """
        Query another model's context and get their relevant information.
        Returns combined reasoning from the target model.
        """
        ctx = self.get_model_context(model_name)
        if not ctx:
            return f"No context available for {model_name}"
        
        # Build a summary of what this model knows
        response = f"Context from {model_name}:\n"
        if ctx.current_task:
            response += f"- Working on: {ctx.current_task}\n"
        if ctx.reasoning_chain:
            response += f"- Recent reasoning: {' -> '.join(ctx.reasoning_chain[-5:])}\n"
        if ctx.key_decisions:
            response += f"- Key decisions: {json.dumps(ctx.key_decisions[-3:], indent=2)}\n"
        if ctx.results:
            response += f"- Results: {json.dumps(ctx.results, indent=2)}\n"
        
        # Add signal that we queried this model
        self.add_signal("Manager", model_name, f"query_{question[:50]}", {"question": question})
        
        return response
    
    def share_decision(self, model_name: str, decision: str, reasoning: List[str]):
        """Share a decision with other models"""
        self.update_model_context(
            model_name,
            reasoning_chain=reasoning,
            key_decisions=[{"decision": decision, "at": time.time()}]
        )
        
        # Notify other models of this decision
        all_models = self.get_all_model_contexts()
        for other_model in all_models:
            if other_model != model_name:
                self.add_signal(
                    model_name, other_model,
                    f"decision_{decision[:30]}",
                    {"decision": decision}
                )
    
    def get_working_directory(self) -> Path:
        """Get the path to the shared context file's directory"""
        return self._path.parent


# Singleton instance for easy access
_shared_context: Optional[SharedContext] = None


def get_shared_context(path: Optional[str] = None) -> SharedContext:
    global _shared_context
    if path:
        return SharedContext(path=path)
    if _shared_context is None:
        _shared_context = SharedContext()
    return _shared_context