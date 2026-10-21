# 10k — `agents/knowledge/`

> **J-01 RESOLVED in v2.1.125 (ARCH-ENG-297).** `KnowledgeContext.build_context()`
> now retrieves through `LayeredMemoryRetriever`, so freshness, expiry,
> quarantine and layer filtering are applied to the prompt context instead of a
> raw table scan.
>
> **J-04/J-05 RESOLVED in v2.1.125 (ARCH-ENG-296).** `prompt_sanitize.py` and
> `proposal_reviewer.py` now have executable regression tests: injection markers
> are neutralised and wrapped, plain text survives unchanged, a thin proposal is
> blocked, a complete proposal passes, and the analyst-backed quality path is
> exercised (ARCH-ENG-294). The gate is no longer only claimed live.

14 scripts, 3,808 lines. Workspace management, prompt construction, prompt
sanitisation, skill indexing, and the memory database. Reviewed at method level
rather than module level — which is what surfaced the significant findings here.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 1 | — |
| `prompt_assembly.py` | 25 | `big_brain`, `small_brain` |
| `llama_setting_help.py` | 70 | `brain_settings_row`, `dual_brain_control` |
| `prompt_sanitize.py` | 109 | 8 sites — **0 tests** |
| `proposal_writer.py` | 120 | `earning_tab.py` |
| `proposal_templates.py` | 128 | `proposal.py`, `earning_pipeline.py` ×2 |
| `proposal_reviewer.py` | 207 | `main.py` — **0 tests** |
| `layered_memory.py` | 144 | **nothing** |
| `layered_memory.py` | 144 | **DEAD** |
| `prompt_utils.py` | 171 | `library.py` |
| `skill_index.py` | 335 | `dialogue_tab.py` |
| `program_knowledge.py` | 442 | `big_brain`, `small_brain`, `personas` ×3 |
| `prompting_engine.py` | 484 | `big_brain` ×3, `small_brain` ×2 |
| `help_catalog.py` | 575 | `help_dialog.py` |
| `workshop.py` | 997 | 11 sites (`handlers.py` ×5+) |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| J-01 | med | **`layered_memory.py` (144 lines) is entirely dead.** `LayeredMemoryRetriever`, `MemoryLayer`, `MemoryEntry` — a *"Layered, freshness-aware retrieval over the existing program [knowledge]"* — appear only inside their own module and its `__all__`. Six test references, zero production. This is the freshness-aware retrieval layer sitting directly on top of `program_knowledge.py`'s `MemoryDatabase`, i.e. the natural consumer of the memory store that ARCH-ENG-156 had to isolate after 120 fabricated persona turns were written into the operator's live `dual_brain.db`. The memory store is live; the thing that would read it back intelligently is not. |
| J-02 | med | **23 of `Workshop`'s 47 methods are dead — the file I/O layer is live and the domain-entity layer is almost entirely not.** Live: `_ensure_dirs`, `_safe_path`, `_usage_bytes`, `_invalidate_usage`, `storage_stats`, `_can_write`, `create_folder`, `read_file`, `_write_or_raise`, `write_file`, `append_file`, `list_files`, `create_proposal`, `add_account`, `list_accounts`, `_load_accounts`, `_save_accounts`, `add_payment_method`, `list_payment_methods`, `_load_payments`, `_save_payments`, `search_files`, `get_stats`, `get_workspace_summary`. Dead: every `research`, `script`, `application`, `deliverable`, `template` and `note` method, plus `list_dirs`, `file_exists`, `get_file_info`, `get_proposal`, `list_proposals`, `update_proposal_status`, `get_account`, `remove_account`, `get_payment_method`. Eight of the dead methods have tests, which is why they read as live. |
| J-03 | low | **The account and payment-method surface is write-only.** `add_account` and `add_payment_method` each have 2 production call sites; `get_account`, `get_payment_method` and `remove_account` have **zero**. An operator (or the agent) can store account and payment credentials into the workshop through the production API, but cannot read one back or revoke it through that API. `list_accounts` and `list_payment_methods` are live and internally backed by `_load_*`, so the data is retrievable in bulk — but there is no single-item retrieval and **no removal path at all**. Worth confirming against `wallet_crypto.py`'s vault before treating it as a gap rather than a deliberate boundary. |
| J-04 | med | **`prompt_sanitize.py` — 109 lines of prompt-injection defence, live from 8 sites, zero tests.** This is the module that hardens every scrape, search result and gig description before it enters a prompt. It is well-designed (see below) and completely unverified. |
| J-05 | med | **`proposal_reviewer.py` — the pre-submission gate, zero tests.** The docstring is unambiguous: *"Before any proposal is allowed to hit the Upwork API, it must pass this gate."* It answers whether the work is finished and error-free, and computes requirement coverage via `_extract_requirements` / `_coverage` (which returns a coverage fraction and a missing list). It is live from `main.py` and tested nowhere. This is the same *category* as H-01 (`QualityController`, demo-only) — a review gate that decides whether output is good enough — and here the gate runs in production but has never been shown to do the right thing. |
| J-06 | low | **The sanitiser is lossy and its patterns are over-broad.** `re.compile(r"system\s+prompt", re.I)` at `prompt_sanitize.py:48` matches benign prose — "the system prompt was truncated" — and replaces it irreversibly with `[INJECTION-REMOVED]`. The ChatML/Instruct tag patterns (`:56-61`) match `<system>`, `<user>` and `<assistant>` case-insensitively, which will corrupt legitimate quoted content in a gig description. There is no un-sanitise path and no record of what was removed, so the operator cannot tell a sanitiser false positive from an attack. |
| J-07 | info | **A comment asserts an ordering property the code does not have.** `prompt_sanitize.py:40` reads *"Order matters: we neutralize the most structurally dangerous first"* — but each `pat.sub()` in `neutralize_instructions` is independent and the patterns do not overlap, so iteration order is immaterial. Harmless; mildly misleading to the next reader. |

---

## Verified as sound

**`prompt_sanitize.py`'s architecture is right, and its docstring says so
honestly.** It draws the right boundary between two different threats:
the **directive path** (SKILL.md), which `instruction_gate.py` quarantines so
that untrusted instructions are *"NEVER injected as directives until a human
approves them*; and the **data path** (scrapes, search, gigs), which this module
hardens. And it explicitly refuses to overclaim its own importance:

> *"we do NOT rely on sanitization alone. The chat routing layer already
> classifies intent and the action pipeline gates execution; sanitization just
> reduces the blast radius of malicious scraped text."*

That is the correct framing for a pattern-matching defence: the patterns are
necessarily incomplete, and the module says so instead of implying the list is
exhaustive. J-04 is about it being untested, not about it being unsound.

**`proposal_reviewer.py` returns rather than raises.** `ProposalReviewer.review`
is documented as *"Run the full gate. Returns a ReviewResult (never raises)"* —
a review gate that cannot take down the submit path by raising on malformed
input is the right shape, and `_coverage` returning `(fraction, missing_list)`
gives the operator actionable output rather than a boolean.

**`program_knowledge.py` is genuinely live** from `big_brain`, `small_brain` and
`personas` (three sites), with 13 test references behind the ARCH-ENG-156
isolation fix.

---

## Assessment

This area is where the module-level sweep would have been misleading, which is
why it was reviewed per file. At module level `agents/knowledge/` looks healthy:
13 of 14 modules have production consumers, and the only dead one is a
144-line `layered_memory.py`. At method level the picture is much less even —
**`workshop.py` is half-dead in a way its module-level presence conceals**, and
two security-relevant gates have zero tests.

J-02 and J-04/J-05 share a cause worth naming. In both cases the code is
well-documented enough to *read* as verified: `workshop.py`'s dead methods have
tests, and the two gates have thorough docstrings. The sweep's earlier heuristic
— presence of tests or documentation implies a function — is exactly backwards
here, and J-02 is a clean demonstration: eight dead methods, all tested.

The most useful output of this area is the *shape* of the dead surface rather
than any individual method. `Workshop` implements a full workspace domain —
proposals, research, scripts, applications, deliverables, templates, notes,
accounts, payment methods — but only the generic file operations and the two
credential-sinking methods are wired. That reads less like incremental decay and
more like a design that was built out fully and then only partially adopted,
which is a different remediation conversation from "delete the dead code".