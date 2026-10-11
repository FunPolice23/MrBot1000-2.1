import time

from agents.autonomy.agent_registry import AgentRegistry, CapabilitySpec, CapabilityCategory


def _registry():
    return AgentRegistry()


def _agent(registry):
    return registry.register("worker", "worker", [CapabilitySpec(CapabilityCategory.ANALYSIS, "review")])


def test_lease_must_be_owned_to_complete_and_can_be_renewed():
    registry = _registry()
    agent = _agent(registry)
    assert registry.assign_task(agent.agent_id, "task-1", lease_seconds=1)
    lease_id = registry.get_agent(agent.agent_id).lease_id
    assert lease_id
    assert not registry.complete_task(agent.agent_id, lease_id="wrong")
    assert registry.renew_lease(agent.agent_id, lease_id, lease_seconds=10)
    assert registry.complete_task(agent.agent_id, lease_id=lease_id)
    assert registry.get_agent(agent.agent_id).status == "idle"


def test_expired_lease_is_reclaimed_and_late_completion_rejected():
    registry = _registry()
    agent = _agent(registry)
    assert registry.assign_task(agent.agent_id, "task-2", lease_seconds=0.01)
    lease_id = registry.get_agent(agent.agent_id).lease_id
    time.sleep(0.03)
    assert not registry.complete_task(agent.agent_id, lease_id=lease_id)
    current = registry.get_agent(agent.agent_id)
    assert current.status == "idle"
    assert current.tasks_failed == 1


def test_cancellation_is_cooperative_and_scoped_to_lease():
    registry = _registry()
    agent = _agent(registry)
    assert registry.assign_task(agent.agent_id, "task-3")
    lease_id = registry.get_agent(agent.agent_id).lease_id
    assert registry.request_cancellation(agent.agent_id, lease_id)
    assert registry.is_cancellation_requested(agent.agent_id, lease_id)
    assert registry.release_task(agent.agent_id, lease_id)
    assert not registry.is_cancellation_requested(agent.agent_id, lease_id)