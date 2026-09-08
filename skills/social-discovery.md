# Skill: Social Discovery

Trigger: user requests opportunity discovery, or earnings pipeline enters discover phase, or refresh is requested for social/fiverr/upwork sources.

Input:
- source list: social, fiverr, upwork, airdrop, defi, microtask, content, dynamic
- max results per source if bounded
- allowed payment types: usd, crypto, barter
- max risk: low, medium, high

Steps:
1. Initialize discovery clients only for enabled sources
2. For each source, collect raw opportunities with source, title, description, platform, url, payment_type, estimated_value, min_amount, risk_level
3. Normalize each opportunity into a common record
4. Persist each opportunity to memory tier 1 with discovered_at timestamp
5. Return normalized list; do not invent results if source is unavailable

Guardrails:
- Do not submit, register, or apply to opportunities from this skill
- Do not scrape authenticated pages without a supported client path
- If a source is unreachable, return empty list for that source and continue
- Do not store credentials or session tokens in memory

Output:
- List of normalized opportunities
- Per-source counts and any source-level errors