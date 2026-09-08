"""task_validator.py — DETERMINISTIC capability validator (v2.0.36e).

This is the authoritative gate. The LLM may *suggest* what a task requires (task_spec.infer),
but ONLY this validator decides whether the system can actually execute it. Unsupported tasks are
never reported as executable.

Verdict logic (deterministic, offline):
- For each required capability, look it up in the registry:
    * system + automatable        -> served automatically
    * system + human-only         -> served via human
    * not in system + human_capable -> requires a human (no automation)
    * not in system + not human     -> HARD UNSUPPORTED (cannot be done at all)
- `human_available` (default True) decides whether human-required is acceptable.
- Verdict:
    * any HARD UNSUPPORTED                       -> "unsupported"   (is_executable=False)
    * all served automatically                  -> "fully_automatable"
    * mix of auto + human, no hard-unsupported  -> "partially_automatable"
    * only human-served, no hard-unsupported    -> "human_required"
- Unsupported capabilities are NOT silently dropped: they are surfaced in `missing_system` /
  `unsupported_hard` and force `is_executable=False`.
"""

from __future__ import annotations

from typing import List, Optional

from agents.capability_registry import CapabilityRegistry, CapabilitySpec, get_default_registry
from agents.task_spec import Task, TaskFeasibility


class CapabilityValidator:
    """Deterministic feasibility gate backed by a CapabilityRegistry."""

    def __init__(self, registry: Optional[CapabilityRegistry] = None,
                 human_available: bool = True) -> None:
        self.registry = registry or get_default_registry()
        self.human_available = human_available

    def set_human_available(self, available: bool) -> None:
        self.human_available = available

    # ── Core gate ────────────────────────────────────────────────
    def validate(self, task: Task) -> TaskFeasibility:
        reqs = task.normalized_requirements()
        if not reqs:
            # No declared capabilities: cannot determine executability -> treat as unsupported
            # (do NOT pretend it is runnable). Caller must supply requirements.
            f = TaskFeasibility(
                verdict="unsupported",
                is_executable=False,
                explanation="No required capabilities declared; cannot validate executability.",
                confidence=0.0,
            )
            self._apply_to_task(task, f)
            return f

        supported: List[str] = []
        automatable: List[str] = []
        human_only: List[str] = []
        missing_system: List[str] = []     # not in registry at all
        unsupported_hard: List[str] = []   # in registry but neither system nor human can do it

        for cap in reqs:
            spec: Optional[CapabilitySpec] = self.registry.get(cap)
            if spec is None:
                # Unknown capability token: not in the system. Treat as missing (needs human/unknown).
                missing_system.append(cap)
                continue
            if spec.automatable:
                supported.append(cap)
                automatable.append(cap)
            elif spec.human_capable:
                if self.human_available:
                    supported.append(cap)
                    human_only.append(cap)
                else:
                    # Human-capable but no human operator configured -> cannot be performed.
                    unsupported_hard.append(cap)
            else:
                # Registered but neither automatable nor human-capable -> hard unsupported.
                unsupported_hard.append(cap)

        # Decide verdict deterministically.
        if unsupported_hard:
            verdict = "unsupported"
            is_exec = False
            expl = (f"Hard-unsupported capabilities (cannot be performed by system or human): "
                    f"{', '.join(unsupported_hard)}.")
        elif missing_system and not self.human_available:
            verdict = "unsupported"
            is_exec = False
            expl = (f"Required capabilities not available in-system and no human operator "
                    f"configured: {', '.join(missing_system)}.")
        elif missing_system and self.human_available:
            # Missing from system but a human could do them -> human-required (cannot auto-run).
            verdict = "human_required"
            is_exec = True
            human_only.extend(missing_system)
            expl = (f"Requires human operator for: {', '.join(missing_system)} "
                    f"(not automatable in-system).")
        elif human_only and not automatable:
            verdict = "human_required"
            is_exec = True
            expl = f"All required capabilities require a human operator: {', '.join(human_only)}."
        elif human_only and automatable:
            verdict = "partially_automatable"
            is_exec = True
            expl = (f"Partially automatable. Automatic: {', '.join(automatable)}; "
                    f"human-required: {', '.join(human_only)}.")
        else:
            # everything automatable
            verdict = "fully_automatable"
            is_exec = True
            expl = f"Fully automatable with system capabilities: {', '.join(automatable)}."

        # Confidence: higher when requirements are known capabilities, lower when missing/unknown.
        known = len(supported) + len(unsupported_hard)
        total = len(reqs)
        confidence = (known / total) if total else 0.0

        f = TaskFeasibility(
            verdict=verdict,
            supported=sorted(supported),
            automatable=sorted(automatable),
            human_only=sorted(set(human_only)),
            missing_system=sorted(missing_system),
            unsupported_hard=sorted(unsupported_hard),
            is_executable=is_exec,
            explanation=expl,
            confidence=confidence,
        )
        self._apply_to_task(task, f)
        return f

    def _apply_to_task(self, task: Task, f: TaskFeasibility) -> None:
        """Write the authoritative execution mode / human_required back onto the task
        (deterministic — overrides any LLM/caller guess)."""
        task.human_required = f.verdict in ("human_required", "partially_automatable")
        task.execution_mode = {
            "fully_automatable": "automatic",
            "partially_automatable": "hybrid",
            "human_required": "human_in_loop",
            "unsupported": "unsupported",
        }.get(f.verdict, "unsupported")

    # ── Helper: classify a single capability (used by tooling/UI) ──
    def classify(self, capability: str) -> str:
        spec = self.registry.get(capability)
        if spec is None:
            return "unsupported"
        if spec.automatable:
            return "fully_automatable"
        if spec.human_capable:
            return "human_required"
        return "unsupported"
