from agents.cognition.personas import DRIVER, NAVIGATOR, PersonaRole


def test_driver_contract_prioritizes_progress_without_authority():
    contract = DRIVER.contract
    assert contract is not None
    assert contract.role is PersonaRole.DRIVER
    assert "select and size opportunities" in contract.responsibilities
    assert "human approval" in contract.prohibited_authorities
    assert "tree" in contract.default_reasoning_modes


def test_navigator_contract_prioritizes_verification_without_authority():
    contract = NAVIGATOR.contract
    assert contract is not None
    assert contract.role is PersonaRole.NAVIGATOR
    assert "detect contradictions" in contract.responsibilities
    assert "check freshness" in contract.required_checks
    assert "tool execution" in contract.prohibited_authorities


def test_prompt_contains_role_contract():
    prompt = NAVIGATOR.build_system_prompt(goal="verify a listing", compact=True)
    assert "ROLE CONTRACT (navigator)" in prompt
    assert "You cannot authorize" in prompt


def test_prompt_teams_conversational_awareness_not_a_script():
    """Both tiers must instruct the agent to react to the human and teammates
    specifically, vary its replies, and hold a genuine opinion — the antidote to
    robotic, script-following turns that ignore the human or restate the same
    analysis every turn."""
    full = DRIVER.build_system_prompt(goal="Earn money", tier="full")
    compact = NAVIGATOR.build_system_prompt(goal="Earn money", tier="compact")
    for label, prompt in (("full", full), ("compact", compact)):
        assert "BE A REAL PARTICIPANT" in prompt, f"{label} tier missing awareness block"
    # The full tier carries the detailed instructions.
    assert "ANSWER THEM" in full, "full tier must instruct answering the human directly"
    assert "genuine opinion" in full, "full tier must encourage a real stance"
    # Both must warn against the robotic failure modes.
    for prompt in (full, compact):
        assert "restate" in prompt.lower() or "same way" in prompt.lower()