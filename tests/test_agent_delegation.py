from agents.autonomy.agent_registry import (
    AgentRegistry,
    CapabilityCategory,
    CapabilitySpec,
)


def _agent(registry, name, capabilities):
    return registry.register(name, "worker", capabilities)


def test_delegation_selects_idle_agent_with_all_capabilities():
    registry = AgentRegistry()
    selected = _agent(registry, "analysis-worker", [
        CapabilitySpec(CapabilityCategory.ANALYSIS, "research"),
        CapabilitySpec(CapabilityCategory.SAFETY, "risk_review"),
    ])
    _agent(registry, "partial-worker", [
        CapabilitySpec(CapabilityCategory.ANALYSIS, "research"),
    ])

    result = registry.delegate_task(
        "task-1", ["research", "risk_review"], [CapabilityCategory.ANALYSIS])

    assert result.assigned
    assert result.agent_id == selected.agent_id
    assert result.lease_id
    assert result.matched_capabilities == ["research", "risk_review"]


def test_delegation_refuses_missing_capability_without_fabricating_assignment():
    registry = AgentRegistry()
    _agent(registry, "worker", [CapabilitySpec(CapabilityCategory.ANALYSIS, "research")])

    result = registry.delegate_task("task-2", ["browser_automation"])

    assert not result.assigned
    assert result.agent_id == ""
    assert "no idle agent" in result.reason
    assert registry.get_busy_agents() == []


def test_delegation_excludes_busy_agents():
    registry = AgentRegistry()
    agent = _agent(registry, "worker", [CapabilitySpec(CapabilityCategory.ANALYSIS, "research")])
    assert registry.assign_task(agent.agent_id, "existing")

    result = registry.delegate_task("task-3", ["research"])

    assert not result.assigned