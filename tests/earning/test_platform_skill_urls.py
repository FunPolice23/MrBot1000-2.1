"""Platform -> skill.md URL map (A4 GUI half).

The map routes agent-operated platforms' skill.md through the provenance gate
as UNTRUSTED data. Only VERIFIED URLs are listed — an unknown platform returns
"" so the persona is never sent to a fabricated document.
"""
from agents.earning.platform_skill_urls import (
    skill_url_for_platform, is_agent_operated_platform, known_agent_platforms)


def test_moltbook_resolves_to_verified_url():
    assert skill_url_for_platform("moltbook") == "https://www.moltbook.com/skill.md"
    assert is_agent_operated_platform("moltbook") is True


def test_ugig_resolves_to_verified_url():
    # Verified 2026-10-14: HTTP 200, real agent-skill frontmatter.
    assert skill_url_for_platform("ugig") == "https://ugig.net/skill.md"
    assert is_agent_operated_platform("ugig") is True


def test_unknown_platform_never_fabricates_a_url():
    # An unverified platform must return "" so the persona is never sent to a
    # document that may not exist.
    assert skill_url_for_platform("upwork") == ""
    assert skill_url_for_platform("fiverr") == ""
    assert skill_url_for_platform("reddit") == ""
    assert is_agent_operated_platform("upwork") is False


def test_empty_and_none_return_empty():
    assert skill_url_for_platform("") == ""
    assert skill_url_for_platform(None) == ""
    assert is_agent_operated_platform("") is False


def test_case_and_whitespace_insensitive():
    assert skill_url_for_platform("  Moltbook ") == "https://www.moltbook.com/skill.md"
    assert skill_url_for_platform("UGIG") == "https://ugig.net/skill.md"


def test_known_agent_platforms_lists_verified_only():
    assert set(known_agent_platforms()) == {"moltbook", "ugig"}