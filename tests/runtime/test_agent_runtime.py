from agents.runtime.agent import (
    AgentDescriptor,
    AgentEventKind,
    AgentRuntime,
)
from agents.core.comms import EventBus, MessageType


def _runtime():
    return AgentRuntime(
        "evaluate the opportunity",
        (
            AgentDescriptor("edward", "Edward Hurst", "driver"),
            AgentDescriptor("jacob", "Jacob Stanley", "navigator"),
        ),
    )


def test_runtime_selects_an_opportunity_without_a_snapshot_round():
    runtime = _runtime()

    first = runtime.next_opportunity()
    assert first is not None
    assert first.descriptor.agent_id == "edward"

    event = runtime.record_turn(
        "edward",
        "I propose verifying the client's payment history.",
        intents=("proposal", "action"),
    )
    assert event.kind is AgentEventKind.TURN_COMPLETED
    assert runtime.next_opportunity(exclude="edward").descriptor.agent_id == "jacob"
    assert runtime.states["edward"].proposed_actions


def test_runtime_tracks_questions_and_high_priority_interrupts():
    runtime = _runtime()
    runtime.record_turn("jacob", "Where is the payment evidence?", intents=("question",))

    assert runtime.states["jacob"].pending_questions
    interrupt = runtime.interrupt("jacob", "edward", "evidence conflict")

    assert interrupt.kind is AgentEventKind.INTERRUPT
    assert interrupt.priority == 10
    assert runtime.states["edward"].attention == 1.0


def test_runtime_updates_goal_and_exposes_state_snapshot():
    runtime = _runtime()
    runtime.update_goal("verify the client before proposing work")

    snapshot = runtime.snapshot()
    assert snapshot["goal"] == "verify the client before proposing work"
    assert snapshot["agents"]["edward"]["current_goal"] == snapshot["goal"]


def test_runtime_publishes_state_events_to_shared_bus():
    bus = EventBus.reset_instance()
    received = []
    bus.subscribe_type(MessageType.COGNITION_UPDATE, received.append)
    runtime = AgentRuntime("test", (AgentDescriptor("edward", "Edward", "driver"),), bus=bus)

    runtime.publish(AgentEventKind.PROPOSAL_MADE, "edward", payload={"text": "verify"})

    assert len(received) == 1
    assert received[0].payload["event_kind"] == "proposal_made"
