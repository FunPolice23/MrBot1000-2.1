"""Platform -> remote ``skill.md`` URL map for agent-operated earning platforms.

When a Dialogue opportunity's platform is agent-operated (it publishes a
machine-readable ``skill.md`` playbook), the personas' read-only ``web_read``
can fetch it as **untrusted reference data**. The fetch is routed through the
provenance/instruction gate (``agents/safety/handlers.py::_tool_web_read`` ->
``InstructionGate``), so the content is DATA for review, never directives.

Only platforms whose ``skill.md`` URL is KNOWN/VERIFIED are listed. Adding a
platform requires confirming its ``/skill.md`` actually resolves; a guessed URL
must NEVER be added — it would fabricate a document and mislead the personas
into "reading" something that does not exist.
"""

# Verified entries only. ``moltbook`` is confirmed: ``agents/earning/
# moltbook_agent.py`` publishes this exact URL (``MOLTBOOK_SKILL_URL``) and the
# gate already handles it.
_PLATFORM_SKILL_URLS = {
    "moltbook": "https://www.moltbook.com/skill.md",
    # Verified 2026-10-14: HTTP 200, real agent-skill frontmatter
    # ("name: ugig, version: 1.0.0, Gig marketplace for AI agents").
    "ugig": "https://ugig.net/skill.md",
}


def skill_url_for_platform(platform: str) -> str:
    """Return the verified ``skill.md`` URL for an agent-operated platform.

    Returns ``""`` for an unknown or unverified platform, so the caller never
    directs a persona to a document that may not exist (no fabrication).
    Case-insensitive and whitespace-tolerant.
    """
    if not platform:
        return ""
    key = str(platform).strip().lower()
    return _PLATFORM_SKILL_URLS.get(key, "")


def is_agent_operated_platform(platform: str) -> bool:
    """True when the platform has a verified, gate-routable ``skill.md``."""
    return bool(skill_url_for_platform(platform))


def known_agent_platforms() -> list:
    """The platform keys with a verified skill.md (for the Dialogue hint line)."""
    return sorted(_PLATFORM_SKILL_URLS)