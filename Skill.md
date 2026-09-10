# Skill.md — Skill Specification Template

This template defines the standard format for documenting skills in MrBot1000.

---

## How to Create a New Skill

1. Create a new file in `/skills/` directory
2. Name it: `<skill-name>.md` (kebab-case)
3. Copy this template and fill in the sections
4. Version your skills for updates

---

## Skill Specification Format

```markdown
# Skill: <Name in Title Case>

## Trigger
<When should this skill activate?>
Requirements for skill to be invoked

## Input
- <Parameter 1>: <Type and description>
- <Parameter 2>: <Type and description>

## Steps
1. <Step 1 description>
2. <Step 2 description>
3. Continue with numbered steps

## Guardrails
- <Safety rule 1 - what NOT to do>
- <Safety rule 2 - what NOT to do>
- <Safety rule 3 - ensure proper handling>

## Output
- <Output 1>: <description>
- <Output 2>: <description>
```

---

## Example: Social Discovery

```markdown
# Skill: Social Discovery

## Trigger
user requests opportunity discovery, or earnings pipeline enters discover phase, or refresh is requested for social/fiverr/upwork sources.

## Input
- source list: social, fiverr, upwork, airdrop, defi, microtask, content, dynamic
- max results per source if bounded
- allowed payment types: usd, crypto, barter
- max risk: low, medium, high

## Steps
1. Initialize discovery clients only for enabled sources
2. For each source, collect raw opportunities with source, title, description, platform, url, payment_type, estimated_value, min_amount, risk_level
3. Normalize each opportunity into a common record
4. Persist each opportunity to memory tier 1 with discovered_at timestamp
5. Return normalized list; do not invent results if source is unavailable

## Guardrails
- Do not submit, register, or apply to opportunities from this skill
- Do not scrape authenticated pages without a supported client path
- If a source is unreachable, return empty list for that source and continue
- Do not store credentials or session tokens in memory

## Output
- List of normalized opportunities
- Per-source counts and any source-level errors
```

---

## Skill Types in MrBot1000

| Skill | Purpose | Responsible Agent |
|-------|---------|-------------------|
| `social-discovery.md` | Find jobs/opportunities | JobSearch |
| `opportunity-evaluation.md` | Score/rank opportunities | Analyst |
| `opportunity-filtering.md` | Filter by risk/reward | JobSearch |
| `opportunity-execution.md` | Execute accepted tasks | Coder |
| `opportunity-lifecycle.md` | Track and summarize opportunity progress | Summarizer/Manager |
| `document-qa.md` | Answer questions about files | Summarizer |

---

## Best Practices

1. **Specific Triggers**: Be precise about when the skill should activate
2. **Clear Inputs**: Define all parameters and their types
3. **Numbered Steps**: Make execution flow obvious
4. **Explicit Guardrails**: List what the skill MUST NOT do
5. **Structured Output**: Define exactly what the skill returns
6. **State-Aware Execution**: For lifecycle and status skills, include how the result should be persisted to shared context or memory
7. **Evidence-Based Reporting**: Prefer observed state, tool output, and prior records over assumptions

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-08-04 | Initial template |
| 1.1 | 2026-08-05 | Added lifecycle-aware skill guidance and updated skill types |

---

## Related Documentation

- `Agent.md` - Agent runtime contract
- `ARCHITECTURE.md` - Full system architecture
- `CHANGELOG.md` - Change history