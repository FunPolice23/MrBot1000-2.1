from agents.personas import DRIVER, NAVIGATOR, PersonaRole


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