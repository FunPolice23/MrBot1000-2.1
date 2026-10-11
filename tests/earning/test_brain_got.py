"""Tests for bounded GoT records around Big/Small Brain turns."""

from agents.brains.brain_got import BrainTurnGraph


def test_brain_turn_graph_records_tool_status_without_private_reasoning():
    turn = BrainTurnGraph("small_brain", "Classify this opportunity")
    turn.record_tool_trace([{
        "name": "web_search",
        "status": "completed",
        "result_preview": "ignored by the graph contract",
    }])
    record = turn.finish("Candidate requires verification")

    nodes = record["graph"]["nodes"]
    assert record["role"] == "small_brain"
    assert record["status"] == "completed"
    assert any(node["kind"] == "observation" for node in nodes)
    assert all("reasoning" not in node["text"].lower() for node in nodes)
    assert all("result_preview" not in node["text"] for node in nodes)


def test_big_and_small_adapters_store_last_got_record():
    from agents.brains.big_brain import BigBrainAdapter
    from agents.brains.small_brain import SmallBrainAdapter

    big = BigBrainAdapter.__new__(BigBrainAdapter)
    big.last_tool_trace = [{"name": "web_read", "status": "completed"}]
    big.last_thought_graph = None
    big_turn = big._start_got_turn("Review terms")
    big._finish_got_turn(big_turn, "Needs evidence")

    small = SmallBrainAdapter.__new__(SmallBrainAdapter)
    small.last_tool_trace = [{"name": "web_search", "status": "pending_approval"}]
    small.last_thought_graph = None
    small_turn = small._start_got_turn("Triage listing")
    small._finish_got_turn(small_turn, "Blocked")

    assert big.last_thought_graph["role"] == "big_brain"
    assert small.last_thought_graph["role"] == "small_brain"
    assert big.last_thought_graph["status"] == "completed"
    assert small.last_thought_graph["status"] == "completed"
    assert any(
        node["status"] == "pending_approval"
        for node in small.last_thought_graph["graph"]["nodes"]
    )


# ── Branch expansion (Tree / Graph-of-Thoughts) ──────────────────────────────

from agents.brains.brain_got import BranchCandidate
from agents.cognition.reasoning_modes import select_reasoning_pattern
from agents.evidence.evidence import Evidence, EvidenceStatus, VerificationLevel


def _tree_pattern():
    # A goal that resolves to a branching pattern (max_branches > 1).
    return select_reasoning_pattern("compare alternatives for the best platform")


def _direct_pattern():
    return select_reasoning_pattern("hi there")


def _evidence():
    return {
        "ev-strong": Evidence(
            id="ev-strong", source="gh", evidence_type="research_summary",
            status=EvidenceStatus.VERIFIED,
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
            verification_method="authenticated_api_response"),
        "ev-weak": Evidence(
            id="ev-weak", source="other", evidence_type="research_summary",
            status=EvidenceStatus.CONFLICTED,
            verification_level=VerificationLevel.L1_SELF_REPORTED,
            verification_method="manual_attestation"),
    }


def _candidates():
    return [
        BranchCandidate(text="GitHub bounties", rationale="concrete issues",
                        evidence_ids=["ev-strong"], expected_payout=60),
        BranchCandidate(text="uGig gigs", rationale="gated behind 402",
                        evidence_ids=["ev-weak"], expected_payout=60),
        BranchCandidate(text="freelance research", rationale="human submit",
                        expected_payout=50),
    ]


def test_expand_branches_creates_scored_option_nodes():
    turn = BrainTurnGraph("big_brain", "compare alternatives best platform",
                          pattern=_tree_pattern())
    ids = turn.expand_branches(_candidates())
    assert len(ids) == 3
    assert turn.is_branching
    # Each branch is an OPTION node derived from the goal + depending on the check.
    kinds = [turn.graph.nodes[i].kind.value for i in ids]
    assert kinds == ["option", "option", "option"]
    goal_derived = [
        e for e in turn.graph.edges
        if e.kind.value == "derived_from" and e.source_id in ids
    ]
    assert len(goal_derived) == 3
    # A hypothesis child supports each branch so evidence propagates into score.
    hypotheses = [n for n in turn.graph.nodes.values() if n.kind.value == "hypothesis"]
    assert len(hypotheses) == 3


def test_expand_branches_respects_max_branches_bound():
    turn = BrainTurnGraph("big_brain", "compare alternatives", pattern=_tree_pattern())
    # tree_of_thoughts caps at 3; supply 5 candidates.
    many = _candidates() + [
        BranchCandidate(text="extra1"), BranchCandidate(text="extra2"),
    ]
    ids = turn.expand_branches(many)
    assert len(ids) <= 3


def test_direct_pattern_expand_is_a_noop():
    turn = BrainTurnGraph("big_brain", "hi there", pattern=_direct_pattern())
    assert turn.expand_branches(_candidates()) == []
    assert not turn.is_branching


def test_single_candidate_does_not_branch():
    turn = BrainTurnGraph("big_brain", "compare alternatives", pattern=_tree_pattern())
    assert turn.expand_branches([BranchCandidate(text="only one")]) == []
    assert not turn.is_branching


def test_score_and_select_prefers_evidence_backed_branch():
    turn = BrainTurnGraph("big_brain", "compare alternatives best platform",
                          pattern=_tree_pattern())
    turn.expand_branches(_candidates())
    scores = turn.score_branches(_evidence())
    assert len(scores) == 3
    # Ranked best-first: the ev-strong branch must outrank the weak/no-evidence ones.
    best = scores[0]
    assert best.direct_support + best.propagated_support >= \
        scores[-1].direct_support + scores[-1].propagated_support
    decision = turn.select_branch()
    assert decision is not None
    assert turn.graph.nodes[decision].kind.value == "decision"
    # Non-selected branches are marked rejected.
    rejected = [n for n in turn.graph.nodes.values()
                if n.kind.value == "option" and n.status == "rejected"]
    assert len(rejected) == 2
    # The winner is the evidence-backed branch (branch index 0).
    assert turn._selected_branch_id.endswith(":0")


def test_finish_reports_branching_and_outcome_follows_decision():
    turn = BrainTurnGraph("big_brain", "compare alternatives best platform",
                          pattern=_tree_pattern())
    turn.expand_branches(_candidates())
    turn.score_branches(_evidence())
    turn.select_branch()
    record = turn.finish("Chose GitHub bounties.", "completed")
    assert record["branching"] is True
    summary = record["branch_summary"]
    assert summary["branches"] == 3
    assert summary["selected"]
    assert len(summary["ranking"]) == 3
    # A branching turn records far more nodes than the linear skeleton.
    assert len(record["graph"]["nodes"]) >= 10
    # The outcome derives from the decision node.
    outcome = [n for n in record["graph"]["nodes"] if n["kind"] == "outcome"][0]
    derived_from_decision = [
        e for e in record["graph"]["edges"]
        if e["source_id"] == outcome["node_id"]
        and e["target_id"] == turn._decision_id
    ]
    assert derived_from_decision


def test_non_branching_finish_has_no_branch_summary():
    turn = BrainTurnGraph("big_brain", "hi there", pattern=_direct_pattern())
    record = turn.finish("hello", "completed")
    assert record["branching"] is False
    assert record["branch_summary"] is None


def test_finish_got_turn_wires_branch_candidates():
    from agents.brains.big_brain import BigBrainAdapter
    big = BigBrainAdapter.__new__(BigBrainAdapter)
    big.last_tool_trace = []
    big.last_thought_graph = None
    # Force a branching pattern via the goal text.
    turn = big._start_got_turn("compare alternatives for the best platform")
    big._finish_got_turn(turn, "Selected GitHub bounties.",
                         branch_candidates=_candidates(),
                         evidence_by_id=_evidence())
    rec = big.last_thought_graph
    assert rec["branching"] is True
    assert rec["branch_summary"]["branches"] == 3
