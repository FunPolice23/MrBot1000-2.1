from agents.brains.brain_got import BrainTurnGraph
from agents.cognition.reasoning_modes import (
    ReasoningPattern,
    select_reasoning_pattern,
)


def test_pattern_selection_scales_with_task_shape():
    assert select_reasoning_pattern("say hello").pattern is ReasoningPattern.DIRECT_DIALOGUE
    assert select_reasoning_pattern("compare platforms", candidate_count=3).pattern is ReasoningPattern.TREE_OF_THOUGHTS
    assert select_reasoning_pattern("coordinate a workflow", dependency_count=4).pattern is ReasoningPattern.GRAPH_OF_THOUGHTS
    assert select_reasoning_pattern(
        "choose a risky approach", candidate_count=2, risk="high"
    ).pattern is ReasoningPattern.LATS
    assert select_reasoning_pattern("write acceptance criteria and requirements").pattern is ReasoningPattern.SPECIFICATION_DRIVEN
    assert select_reasoning_pattern("benchmark this workflow with mocked tools").pattern is ReasoningPattern.WORKFLOW_EVAL
    assert select_reasoning_pattern("synthesize memory from execution logs").pattern is ReasoningPattern.MEMORY_SYNTHESIS
    assert select_reasoning_pattern("investigate model latency and cost").pattern is ReasoningPattern.LLM_OBSERVABILITY


def test_brain_graph_records_decision_action_and_dispatcher_result():
    turn = BrainTurnGraph("edward", "compare two verified opportunities")
    turn.record_decision("opportunity-a", "higher expected value", evidence_ids=("ev_1",))
    turn.record_action("action-1", "submit_proposal", approval_required=True)
    turn.record_execution("action-1", "blocked", "approval was not supplied")
    result = turn.finish("I recommend opportunity A.", status="completed")

    assert result["pattern"]["name"] == ReasoningPattern.TREE_OF_THOUGHTS.value
    nodes = {node["kind"]: node for node in result["graph"]["nodes"]}
    assert nodes["decision"]["evidence_ids"] == ["ev_1"]
    assert nodes["action"]["status"] == "approval_required"
    assert nodes["observation"]["source"] == "dispatcher"
