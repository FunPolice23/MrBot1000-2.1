"""capability_registry.py — extensible capability taxonomy + system capability registry (v2.0.36e).

This is the foundation of the reusable Skill/Task capability framework. It makes "coding" just one
capability among many, and gives the deterministic validator a single source of truth for what the
system can ACTUALLY do.

Design rules (per MrBot1000 security principle: the LLM is NOT authoritative; deterministic code
controls validation/execution/permissions):
- The taxonomy is open: `CapabilityCategory` seeds the 17 requested categories + OTHER, but any
  string is a valid capability token. New capabilities are registered, not hard-coded.
- `CapabilitySpec` records, for each capability: is it automatable by the system, can a human do it,
  which tool implements it, which `skills/*.md` documents it (REUSE, not duplication), maturity.
- `CapabilityRegistry` is the authoritative lookup. The validator depends ONLY on this, never on an
  LLM guess.

This module has NO network/LLM dependencies — it is fully deterministic and offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CapabilityCategory(str, Enum):
    """Seed taxonomy. The system stays extensible: any string token is a valid capability,
    but these are the canonical categories the framework understands by default."""

    READING = "READING"
    WRITING = "WRITING"
    EDITING = "EDITING"
    RESEARCH = "RESEARCH"
    DATA = "DATA"
    TRANSCRIPTION = "TRANSCRIPTION"
    CODING = "CODING"
    TESTING = "TESTING"
    QA = "QA"
    DOCUMENTS = "DOCUMENTS"
    CONTENT = "CONTENT"
    WEB_RESEARCH = "WEB_RESEARCH"
    AUTOMATION = "AUTOMATION"
    ANALYSIS = "ANALYSIS"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    CRYPTO = "CRYPTO"
    OTHER = "OTHER"

    @classmethod
    def values(cls) -> List[str]:
        return [c.value for c in cls]


@dataclass
class CapabilitySpec:
    """Authoritative description of ONE capability and what the system can do with it.

    automatable   : the system can perform this WITHOUT a human in the loop.
    human_capable : a human (operator) could perform this if the system cannot.
    tool          : the concrete tool/implementation that backs it (or None).
    skill_file    : path to the existing `skills/*.md` that documents it (reuse).
    maturity      : "stable" | "beta" | "experimental" | "planned".
    note          : free text.
    """

    name: str
    category: CapabilityCategory = CapabilityCategory.OTHER
    automatable: bool = False
    human_capable: bool = False
    tool: Optional[str] = None
    skill_file: Optional[str] = None
    maturity: str = "experimental"
    note: str = ""


class CapabilityRegistry:
    """Single source of truth: which capabilities exist and what the system can do with each.

    Extensible at runtime via `register(...)`. The deterministic validator reads ONLY from here.
    """

    def __init__(self) -> None:
        self._caps: Dict[str, CapabilitySpec] = {}
        self._seed_defaults()

    # ── Registration ──────────────────────────────────────────────
    def register(self, spec: CapabilitySpec) -> None:
        """Register (or overwrite) a capability. Extensible by design."""
        self._caps[spec.name.upper()] = spec

    def register_many(self, specs: List[CapabilitySpec]) -> None:
        for s in specs:
            self.register(s)

    # ── Lookup ────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[CapabilitySpec]:
        return self._caps.get(name.upper())

    def __contains__(self, name: str) -> bool:
        return name.upper() in self._caps

    def all(self) -> List[CapabilitySpec]:
        return list(self._caps.values())

    def by_category(self, category: CapabilityCategory) -> List[CapabilitySpec]:
        return [c for c in self._caps.values() if c.category == category]

    def automatable(self) -> List[str]:
        return [c.name for c in self._caps.values() if c.automatable]

    def __len__(self) -> int:
        return len(self._caps)

    # ── Seed: taxonomy + the system's ACTUAL current capabilities ──
    def _seed_defaults(self) -> None:
        """Seed the registry with the requested taxonomy AND the capabilities MrBot1000 can
        actually perform today (mapped to real tools / existing skill files).

        Capabilities the system cannot do (e.g. TRANSCRIPTION) are registered as human_capable
        only, so the validator can report them as human-required rather than silently executable.
        """
        specs: List[CapabilitySpec] = [
            # ── Reading / writing / editing (files + LLM) ──
            CapabilitySpec("READING", CapabilityCategory.READING, automatable=True,
                           human_capable=True, tool="filesystem.read", skill_file="skills/document-qa.md",
                           maturity="stable", note="Read local files / context."),
            CapabilitySpec("WRITING", CapabilityCategory.WRITING, automatable=True,
                           human_capable=True, tool="filesystem.write", maturity="stable",
                           note="Produce new text/files."),
            CapabilitySpec("EDITING", CapabilityCategory.EDITING, automatable=True,
                           human_capable=True, tool="filesystem.write", maturity="stable",
                           note="Revise/proofread existing content."),
            CapabilitySpec("DOCUMENT_QA", CapabilityCategory.EDITING, automatable=True,
                           human_capable=True, tool="llm+filesystem", skill_file="skills/document-qa.md",
                           maturity="stable", note="Answer questions about a document."),

            # ── Research / web ──
            CapabilitySpec("RESEARCH", CapabilityCategory.RESEARCH, automatable=True,
                           human_capable=True, tool="web_search", maturity="stable"),
            CapabilitySpec("WEB_RESEARCH", CapabilityCategory.WEB_RESEARCH, automatable=True,
                           human_capable=True, tool="web_search", maturity="stable",
                           note="Search the web / extract pages."),
            CapabilitySpec("ANALYSIS", CapabilityCategory.ANALYSIS, automatable=True,
                           human_capable=True, tool="pandas/llm", maturity="stable",
                           note="Analyze data / draw conclusions."),
            CapabilitySpec("DATA", CapabilityCategory.DATA, automatable=True,
                           human_capable=True, tool="pandas", maturity="stable",
                           note="Collect/clean/structure data."),

            # ── Coding cluster (coding is ONE capability among many) ──
            CapabilitySpec("CODING", CapabilityCategory.CODING, automatable=True,
                           human_capable=True, tool="terminal/code-exec", maturity="stable",
                           note="Write/modify code in a sandbox."),
            CapabilitySpec("DEBUGGING", CapabilityCategory.CODING, automatable=True,
                           human_capable=True, tool="terminal/code-exec", maturity="stable",
                           note="Diagnose + fix defects."),
            CapabilitySpec("TESTING", CapabilityCategory.TESTING, automatable=True,
                           human_capable=True, tool="terminal/pytest", maturity="stable",
                           note="Run automated tests."),
            CapabilitySpec("QA", CapabilityCategory.QA, automatable=True,
                           human_capable=True, tool="llm+tests", maturity="beta",
                           note="Quality checks / acceptance verification."),

            # ── Documents / content ──
            CapabilitySpec("DOCUMENTS", CapabilityCategory.DOCUMENTS, automatable=True,
                           human_capable=True, tool="docx/xlsx/pdf libs", maturity="beta",
                           note="Create/edit Office/PDF documents where libraries exist."),
            CapabilitySpec("CONTENT", CapabilityCategory.CONTENT, automatable=True,
                           human_capable=True, tool="llm", maturity="stable",
                           note="Generate articles/copy/marketing text."),

            # ── Automation ──
            CapabilitySpec("AUTOMATION", CapabilityCategory.AUTOMATION, automatable=True,
                           human_capable=True, tool="terminal/script", maturity="stable",
                           note="Scripted/repetitive actions."),

            # ── Administrative (partially automatable) ──
            CapabilitySpec("ADMINISTRATIVE", CapabilityCategory.ADMINISTRATIVE, automatable=True,
                           human_capable=True, tool="terminal/llm", maturity="beta",
                           note="Scheduling/data-entry; some steps need a human."),

            # ── Crypto (partially automatable; fund-moving is approval-gated) ──
            CapabilitySpec("CRYPTO", CapabilityCategory.CRYPTO, automatable=True,
                           human_capable=True, tool="wallet-readonly/approval", maturity="beta",
                           note="Read-only wallet ops automatable; fund movement requires human approval."),

            # ── Transcription: NOT system-supported -> human-capable only ──
            # Registered so the validator can honestly report it as human-required, never "executable".
            CapabilitySpec("TRANSCRIPTION", CapabilityCategory.TRANSCRIPTION, automatable=False,
                           human_capable=True, tool=None, maturity="planned",
                           note="No in-system transcription tool yet; a human operator can do it."),

            # ── Fallback ──
            CapabilitySpec("OTHER", CapabilityCategory.OTHER, automatable=False,
                           human_capable=False, maturity="unknown",
                           note="Unrecognized; treated as unsupported unless registered."),
        ]
        self.register_many(specs)


# Module-level default registry (singleton-ish; tests may instantiate their own).
DEFAULT_REGISTRY = CapabilityRegistry()


def get_default_registry() -> CapabilityRegistry:
    return DEFAULT_REGISTRY
