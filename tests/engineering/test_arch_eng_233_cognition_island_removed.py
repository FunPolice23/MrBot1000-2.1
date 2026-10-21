"""ARCH-ENG-233 / BG-01 -- the CognitionRecord island is deleted, not wired.

The finding
-----------
`agents/cognition/graph.py` contained two cognitions systems. The live one --
`ThoughtGraph` and its propagation (`measure_support`, `rank_options`) -- is the
support machinery behind `brain_got.py` branch scoring and `earning/got.py`
option ranking. The dead one -- the `CognitionRecord` cluster of 11 dataclasses
plus the `ledger.py` / `state.py` / `memory_promotion.py` / `contradictions.py`
satellites -- had zero production consumers, yet executed on every run because
`agents/cognition/__init__.py` re-exported it. Five test modules covered it in
full, and none of it ran in the product.

Why deletion was the disposition
--------------------------------
Its evidence gates (`Claim.can_support_action`, `Outcome.can_update_learning`,
`Lesson.can_be_promoted`) were looser than the live
`SupportMeasure.action_eligible` gate -- the BG-02 disagreement. Wiring the
cluster would have made the NEWLY-WIRED gate the permissive one
(ARCH-ENG-211's shape), and wiring a writer onto empty tables is exactly what
ARCH-ENG-158's fail-closed discipline forbids. Deletion removes BG-02 with it:
the strict live gate is untouched.

What this file locks
--------------------
* the four satellite modules no longer exist at any import path;
* the cluster names are absent from the `agents.cognition` surface;
* the live thought-graph half still works after the cut;
* the UNRELATED `fact_ledger` claim machinery -- the live `Claim` that
  `dialogue_honesty` uses -- was not collateral damage.

Vacuity probe (2026-10-19): every assertion in
`test_record_cluster_names_removed_from_surface` and
`test_deleted_satellite_modules_are_gone` fails against the pre-fix tree
(cluster present in `__all__`, satellites importable); the probe in
`test_live_thought_graph_half_still_works` fails against a tree where the
DELETE step accidentally removed the live half.
"""

import importlib.util

import agents.cognition as cognition_pkg
from agents.cognition import graph as cognition_graph

# The satellite modules deleted with the island.
DELETED_MODULES = (
    "agents.cognition.ledger",
    "agents.cognition.state",
    "agents.cognition.memory_promotion",
    "agents.cognition.contradictions",
)

# The names the facade used to re-export from the deleted cluster.
REMOVED_SURFACE_NAMES = (
    "CognitionRecord",
    "InformationItem",
    "Claim",          # the graph.py variant; fact_ledger's Claim was never on this surface
    "Option",
    "Decision",
    "ApprovalRequest",
    "ApprovalState",
    "ActionIntent",
    "ActionState",
    "ToolExecution",
    "Outcome",
    "OutcomeState",
    "InformationKind",
    "Lesson",
    "CognitionLedger",
    "ContradictionCase",
    "ContradictionStatus",
    "open_contradiction",
    "MemoryPromotionPolicy",
    "PromotionDecision",
    "CanonicalCognitionState",
)

# The half that must survive the deletion: brain_got.py and earning/got.py
# import all six.
LIVE_GRAPH_NAMES = (
    "ThoughtGraph",
    "ThoughtNode",
    "ThoughtEdge",
    "ThoughtNodeKind",
    "ThoughtEdgeKind",
    "SupportMeasure",
)


def test_deleted_satellite_modules_are_gone():
    for module_name in DELETED_MODULES:
        assert importlib.util.find_spec(module_name) is None, module_name


def test_record_cluster_names_removed_from_surface():
    assert set(REMOVED_SURFACE_NAMES).isdisjoint(cognition_pkg.__all__)
    for name in REMOVED_SURFACE_NAMES:
        assert not hasattr(cognition_pkg, name), name


def test_live_thought_graph_half_still_works():
    for name in LIVE_GRAPH_NAMES:
        assert hasattr(cognition_pkg, name), name
        assert name in cognition_pkg.__all__

    graph = cognition_pkg.ThoughtGraph()
    graph.add_node(cognition_pkg.ThoughtNode(
        "claim", cognition_pkg.ThoughtNodeKind.CLAIM, "a claim"))
    measure = graph.measure_support("claim")
    assert measure.recommendation == "insufficient_support"
    assert not measure.action_eligible


def test_graph_module_carries_no_record_cluster():
    assert getattr(cognition_graph, "CognitionRecord", None) is None
    assert set(LIVE_GRAPH_NAMES) == set(cognition_graph.__all__)


def test_fact_ledger_claim_machinery_untouched():
    """The LIVE Claim (`dialogue_honesty` uses it) must not be collateral."""
    from agents.cognition.dialogue_honesty import DialogueHonestyService
    from agents.cognition.fact_ledger import Claim, ClaimStatus, FactLedger

    assert Claim is not None
    assert ClaimStatus is not None
    assert FactLedger is not None
    assert DialogueHonestyService is not None
