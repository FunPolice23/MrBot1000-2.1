"""task_spec.py — Task specification + deterministic semantic requirement inference (v2.0.36e).

The `Task` dataclass is the reusable unit the framework reasons about. It is capability-agnostic:
a task declares `required_capabilities` (strings), and the deterministic validator (task_validator.py)
decides whether the system can execute it.

Per the user's security principle, the LLM is NOT authoritative: `infer_task_requirements` defaults
to a deterministic, offline lexicon mapping natural language -> required capabilities. An LLM may be
plugged in via `set_requirement_inferrer(...)` for richer semantics, but the validator still makes
the final, authoritative feasibility call. Never let the LLM's guess mark an unsupported task as
executable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── The reusable Task unit ────────────────────────────────────────
@dataclass
class Task:
    """A reusable, capability-described unit of work.

    The ten fields below are exactly the ones the user specified. Plus lightweight metadata
    (title/description/source) for provenance. `execution_mode`/`human_required` are normally
    filled in by the deterministic validator, not by the caller or the LLM.
    """

    task_type: str = ""                 # e.g. "proofreading", "bug_fix", "transcription"
    required_capabilities: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    tools_required: List[str] = field(default_factory=list)
    estimated_effort: float = 0.0       # hours (LLM/estimate guess; not authoritative)
    validation_method: str = ""         # how completion is verified
    human_required: bool = False        # set by validator (authoritative)
    execution_mode: str = ""            # "automatic" | "human_in_loop" | "hybrid" | "unsupported"
    payment_conditions: Dict[str, object] = field(default_factory=dict)

    # provenance
    title: str = ""
    description: str = ""
    source: str = ""

    def normalized_requirements(self) -> List[str]:
        return sorted({c.upper() for c in self.required_capabilities})


@dataclass
class TaskFeasibility:
    """Authoritative output of the deterministic capability validator."""

    verdict: str                        # fully_automatable | partially_automatable | human_required | unsupported
    supported: List[str] = field(default_factory=list)     # capabilities the system can serve
    automatable: List[str] = field(default_factory=list)   # subset that need no human
    human_only: List[str] = field(default_factory=list)    # supported only via a human
    missing_system: List[str] = field(default_factory=list)  # required but not in system at all
    unsupported_hard: List[str] = field(default_factory=list)  # required, no system AND no human
    is_executable: bool = False         # False for unsupported (never pretend it can run)
    explanation: str = ""
    confidence: float = 0.0            # 0..1; how well requirements are understood

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "is_executable": self.is_executable,
            "supported": self.supported,
            "automatable": self.automatable,
            "human_only": self.human_only,
            "missing_system": self.missing_system,
            "unsupported_hard": self.unsupported_hard,
            "explanation": self.explanation,
            "confidence": self.confidence,
        }


# ── Deterministic semantic inference (LLM-optional) ───────────────
# Lexicon: phrase/keyword -> capability token. Deterministic + offline; the LLM may override.
_LEXICON: Dict[str, List[str]] = {
    "proofread": ["READING", "EDITING", "DOCUMENT_QA"],
    "edit": ["EDITING", "WRITING"],
    "rewrite": ["EDITING", "WRITING"],
    "write": ["WRITING"],
    "author": ["WRITING", "CONTENT"],
    "content": ["CONTENT", "WRITING"],
    "article": ["WRITING", "CONTENT"],
    "copy": ["CONTENT", "WRITING"],
    "blog": ["WRITING", "CONTENT"],
    "read": ["READING"],
    "summar": ["READING", "ANALYSIS"],
    "research": ["RESEARCH", "WEB_RESEARCH", "ANALYSIS"],
    "investigat": ["RESEARCH", "WEB_RESEARCH"],
    "company": ["WEB_RESEARCH", "DATA", "ANALYSIS"],
    "transcrib": ["TRANSCRIPTION"],
    "audio": ["TRANSCRIPTION"],
    "code": ["CODING"],
    "python": ["CODING", "DEBUGGING"],
    "bug": ["CODING", "DEBUGGING", "TESTING"],
    "debug": ["DEBUGGING", "CODING"],
    "fix": ["CODING", "DEBUGGING"],
    "test": ["TESTING", "QA"],
    "qa": ["QA", "TESTING"],
    "verify": ["QA", "TESTING"],
    "data": ["DATA", "ANALYSIS"],
    "analy": ["ANALYSIS", "DATA"],
    "document": ["DOCUMENTS", "DOCUMENT_QA"],
    "docx": ["DOCUMENTS"],
    "xlsx": ["DOCUMENTS"],
    "pdf": ["DOCUMENTS"],
    "automat": ["AUTOMATION"],
    "script": ["AUTOMATION", "CODING"],
    "admin": ["ADMINISTRATIVE"],
    "schedule": ["ADMINISTRATIVE"],
    "crypto": ["CRYPTO"],
    "wallet": ["CRYPTO"],
    "web": ["WEB_RESEARCH"],
    "search": ["WEB_RESEARCH", "RESEARCH"],
}

# Optional LLM inferrer (set via set_requirement_inferrer). Signature: (text:str)->List[str].
_LLM_INFERRER = None


def set_requirement_inferrer(fn) -> None:
    """Optionally plug an LLM in for richer semantic mapping. The validator still decides feasibility."""
    global _LLM_INFERRER
    _LLM_INFERRER = fn


def infer_task_requirements(text: str) -> List[str]:
    """Map natural-language text -> required capability tokens.

    Deterministic lexicon by default (offline). If an LLM inferrer is registered, merge its
    suggestions with the lexicon hits (LLM adds candidates; lexicon guarantees coverage).
    The result is a *hint* — the validator makes the authoritative call.
    """
    text_l = (text or "").lower()
    found: set = set()
    for key, caps in _LEXICON.items():
        if key in text_l:
            found.update(caps)
    if _LLM_INFERRER is not None:
        try:
            extra = _LLM_INFERRER(text) or []
            found.update(c.upper() for c in extra)
        except Exception:
            pass  # LLM failure must never break deterministic inference
    return sorted(found)


def build_task(task_type: str, description: str = "", *, title: str = "",
               source: str = "", infer_requirements: bool = True,
               extra_capabilities: Optional[List[str]] = None) -> Task:
    """Convenience constructor: optionally infer required capabilities from the description."""
    reqs: List[str] = []
    if infer_requirements:
        reqs = infer_task_requirements(description or task_type)
    if extra_capabilities:
        reqs = sorted(set(reqs) | {c.upper() for c in extra_capabilities})
    return Task(
        task_type=task_type,
        required_capabilities=reqs,
        title=title or task_type,
        description=description,
        source=source,
    )


def task_from_opportunity(opp, registry=None) -> Task:
    """Map an existing earning `Opportunity` into a reusable Task (reuse, not duplicate).

    Uses the opportunity's task_type + required_skills + automation_potential to seed capabilities.
    The LLM/estimate layer is NOT authoritative here — only the validator is.
    """
    registry = registry
    reqs: set = set()
    tt = (getattr(opp, "task_type", "") or "").upper()
    if tt:
        reqs.add(tt)
    for s in getattr(opp, "required_skills", []) or []:
        reqs.add(str(s).upper())
    # Map a few well-known opportunity markers to capabilities.
    if "code" in (getattr(opp, "category", "") or "").lower() or "cod" in tt.lower():
        reqs.add("CODING")
    return Task(
        task_type=tt or "opportunity",
        required_capabilities=sorted(reqs),
        title=getattr(opp, "title", "") or tt,
        description=getattr(opp, "description", ""),
        source=getattr(opp, "source", ""),
        estimated_effort=float(getattr(opp, "estimated_effort", 0.0) or 0.0),
        human_required=bool(getattr(opp, "human_required", False)),
    )
