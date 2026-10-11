import pytest

from agents.cognition import (
    CognitionRecord,
    ThoughtEdge,
    ThoughtEdgeKind,
    ThoughtGraph,
    ThoughtNode,
    ThoughtNodeKind,
)
from agents.evidence.evidence import Evidence, EvidenceStatus, VerificationLevel


def _verified_evidence(evidence_id="ev-1"):
    return Evidence(
        id=evidence_id,
        source="test",
        evidence_type="research_summary",
        status=EvidenceStatus.VERIFIED,
        verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
        verification_method="authenticated_api_response",
    )


def test_graph_requires_real_affirmative_evidence_for_support():
    graph = ThoughtGraph()
    graph.add_node(ThoughtNode("claim", ThoughtNodeKind.CLAIM, "listing is open", evidence_ids=["ev-1"]))

    unsupported = graph.measure_support("claim", {})
    supported = graph.measure_support("claim", {"ev-1": _verified_evidence()})

    assert unsupported.recommendation == "insufficient_support"
    assert not unsupported.action_eligible
    assert supported.recommendation == "supported"
    assert supported.action_eligible


def test_graph_propagates_support_but_contradiction_wins():
    graph = ThoughtGraph()
    graph.add_node(ThoughtNode("fact", ThoughtNodeKind.EVIDENCE, "API confirms listing" , evidence_ids=["ev-1"]))
    graph.add_node(ThoughtNode("claim", ThoughtNodeKind.CLAIM, "listing is open", evidence_ids=["ev-1"]))
    graph.add_node(ThoughtNode("bad", ThoughtNodeKind.CLAIM, "listing is closed", status="contradicted"))
    graph.add_edge(ThoughtEdge("fact", "claim", ThoughtEdgeKind.SUPPORTS))
    graph.add_edge(ThoughtEdge("bad", "claim", ThoughtEdgeKind.CONTRADICTS))

    measure = graph.measure_support("claim", {"ev-1": _verified_evidence()})

    assert measure.recommendation == "contradicted"
    assert measure.contradiction > 0
    assert not measure.action_eligible


def test_graph_dependency_blocks_until_dependency_is_supported():
    graph = ThoughtGraph()
    graph.add_node(ThoughtNode("check", ThoughtNodeKind.CHECK, "verify payment", evidence_ids=["ev-1"]))
    graph.add_node(ThoughtNode("action", ThoughtNodeKind.ACTION, "submit proposal", evidence_ids=["ev-1"]))
    graph.add_edge(ThoughtEdge("action", "check", ThoughtEdgeKind.DEPENDS_ON))

    blocked = graph.measure_support("action", {})
    ready = graph.measure_support("action", {"ev-1": _verified_evidence()})

    assert blocked.recommendation == "blocked"
    assert blocked.unresolved_dependencies == 1
    assert ready.recommendation == "supported"


def test_graph_rejects_dependency_cycles_and_serializes_on_record():
    graph = ThoughtGraph()
    graph.add_node(ThoughtNode("a", ThoughtNodeKind.CLAIM, "a"))
    graph.add_node(ThoughtNode("b", ThoughtNodeKind.CLAIM, "b"))
    graph.add_edge(ThoughtEdge("a", "b", ThoughtEdgeKind.DEPENDS_ON))
    with pytest.raises(ValueError, match="cycle"):
        graph.add_edge(ThoughtEdge("b", "a", ThoughtEdgeKind.DEPENDS_ON))

    record = CognitionRecord(goal="review", persona="edward", thought_graph=graph)
    payload = record.to_dict()
    assert payload["thought_graph"]["nodes"][0]["kind"] == "claim"
    assert payload["thought_graph"]["edges"][0]["kind"] == "depends_on"


def test_graph_wide_measurement_is_available_for_diagnostics():
    graph = ThoughtGraph()
    graph.add_node(ThoughtNode("claim", ThoughtNodeKind.CLAIM, "claim", evidence_ids=["ev-1"]))
    measures = graph.measure_all({"ev-1": _verified_evidence()})
    assert measures["claim"].action_eligible


def test_show_thoughts_renders_the_finish_dict_graph():
    """The Dialogue 'Thoughts' button must render the dict that
    BrainTurnGraph.finish() returns, not treat it as an object with .to_dict().

    Regression: the renderer did ``graph.to_dict() if hasattr(graph, "to_dict")
    else {}`` — but last_thought_graph is a plain dict, so hasattr was False and
    every turn rendered as "0 node(s), 0 edge(s)" no matter how many nodes the
    turn actually recorded.
    """
    from unittest.mock import MagicMock

    from agents.brains.brain_got import start_brain_turn
    from gui.tabs.dialogue_tab import DialogueTab

    turn = start_brain_turn("big_brain", "Earn any amount of money or crypto")
    turn.last_tool_trace = [{"name": "web_read", "status": "ok"}]
    finished = turn.finish("I pivoted to GitHub bounties.", "completed")
    # The graph really has nodes/edges.
    assert len(finished["graph"]["nodes"]) >= 4
    assert len(finished["graph"]["edges"]) >= 3

    tab = DialogueTab.__new__(DialogueTab)
    tab._last_thought_graph = finished
    tab._thought_graph_history = [finished]
    tab.append_system = MagicMock()

    tab._show_thoughts()

    rendered = "\n".join(str(c.args[0]) for c in tab.append_system.call_args_list)
    # Must report the real node/edge counts, never the phantom 0/0.
    assert "0 node(s)" not in rendered
    assert f"{len(finished['graph']['nodes'])} node(s)" in rendered
    assert f"{len(finished['graph']['edges'])} edge(s)" in rendered
    # The goal node text should be visible too.
    assert "Earn any amount of money or crypto" in rendered
    # The selected reasoning pattern must be surfaced so a direct (non-branching)
    # turn is explained rather than looking empty.
    assert "pattern:" in rendered
    assert finished["pattern"]["name"] in rendered