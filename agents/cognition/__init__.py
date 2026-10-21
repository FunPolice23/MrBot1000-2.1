"""Canonical cognition contracts and bounded reasoning policies."""

# ARCH-ENG-233 (BG-01): only the thought-graph artifacts are re-exported now.
# The CognitionRecord record cluster and its ledger/state/memory_promotion/
# contradictions satellites are deleted -- they had no production consumer.
from .graph import (
    SupportMeasure,
    ThoughtEdge,
    ThoughtEdgeKind,
    ThoughtGraph,
    ThoughtNode,
    ThoughtNodeKind,
)
from .reasoning_modes import (
    ModePolicy,
    PatternSelection,
    ReasoningMode,
    ReasoningPattern,
    select_reasoning_mode,
    select_reasoning_pattern,
)
from .dialogue_honesty import DialogueHonestyService
from .dialogue import DialogueIntent, DialogueTurn, NaturalDialogue
from .coordinator import (
    CollaborationStage,
    DualBrainCoordinator,
    RunRecord,
    STAGE_REQUEST_TYPE,
    STAGE_RESULT_TYPE,
    STAGE_ROLES,
    StageRun,
)
from .personas import (
    DRIVER,
    NAVIGATOR,
    PERSONAS,
    Persona,
    PersonaRole,
    RoleContract,
    all_personas,
    persona_for_brain_role,
    persona_for_key,
)
from .epistemic import EpistemicLevel, classify, confidence, context_note, disclaimer
from .fact_ledger import (
    ClaimStatus,
    FactLedger,
    LedgerEntry,
    LedgerError,
    IllegalTransition,
    SourceKind,
    UnsubstantiatedVerification,
    source_authority,
)
from .operator_override import OperatorOverrideRegistry, OverrideError, OverrideRecord

# ARCH-ENG-233: the CognitionRecord cluster names are removed from the
# public surface; the graph artifacts below are the live half.
__all__ = [
    "ThoughtEdge", "ThoughtEdgeKind", "ThoughtGraph", "ThoughtNode",
    "ThoughtNodeKind", "SupportMeasure",
    "DialogueHonestyService",
    "DialogueIntent", "DialogueTurn", "NaturalDialogue",
    "CollaborationStage", "DualBrainCoordinator", "RunRecord",
    "STAGE_REQUEST_TYPE", "STAGE_RESULT_TYPE", "STAGE_ROLES", "StageRun",
    "DRIVER", "NAVIGATOR", "PERSONAS", "Persona", "PersonaRole",
    "RoleContract", "all_personas", "persona_for_brain_role", "persona_for_key",
    "EpistemicLevel", "classify", "confidence", "context_note", "disclaimer",
    "ClaimStatus", "FactLedger", "LedgerEntry", "LedgerError",
    "IllegalTransition", "SourceKind", "UnsubstantiatedVerification",
    "source_authority",
    "OperatorOverrideRegistry", "OverrideError", "OverrideRecord",
    "ModePolicy", "PatternSelection", "ReasoningMode", "ReasoningPattern",
    "select_reasoning_mode", "select_reasoning_pattern",
]
