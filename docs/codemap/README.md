# MrBot1000 Codebase Map — full function-level reference

> Living map of every tracked file in MrBot1000 (525 files; 490 Python modules).
> This is a **function-level reference**: every file lists its purpose, and every
> top-level function / class / method with its signature, line number, and a
> one-line description. Use it to quickly answer "what is in this file and what
> does each part do" before touching any code.

## How to read this map
- Each file = a `###` heading: **path** — module docstring + `(NL)` line count.
- `> note` lines carry curated architectural tags (phase / ARCH-ENG / invariants)
  that static analysis can't derive.
- **Functions:** each `- name(sig) (Lnnn) — what it does`. `sig` shows params,
  types, defaults, and `-> return` type. `Lnnn` = line number to jump to.
- **Classes:** each `- class Name(bases) (Lnnn) — what it is`, then its methods
  indented (dunder methods other than `__init__` are omitted for brevity).
- Generated from source via `ast` (not regex) — signatures are accurate.

## Index of sections

### Source code
1. [agents/core + agents/cognition](agents-core-cognition.md) — composition root, config, comms, persistence contract, reasoning, fact ledger, personas, honesty stack.
2. [agents/brains + agents/dialogue + agents/runtime](agents-brains-dialogue-runtime.md) — the two llama.cpp brains, chat completion, the 1085L launcher (`dual_brain.py`), device registry, agent runtime.
3. [agents/safety](agents-safety.md) — approval queue, tool gate, cost guard, rate limiter, tool handlers, instruction quarantine.
4. [agents/providers + agents/knowledge + agents/integrations + agents/platforms](agents-providers-knowledge-integrations.md) — LLM providers, GGUF/model detection, prompting/memory/workshop, web + platform clients, credential vault.
5. [agents/services + agents/autonomy + agents/discovery + agents/evidence + agents/polish](agents-services-autonomy-discovery-evidence.md) — the 1087L autonomous loop, run store, self-audit/improvement, discovery sources, evidence/provenance backbone.
6. [agents/earning](agents-earning-A.md) — the 54-file money engine (discovery → eval → execute → accounting), incl. StrategyFeedback + MoltbookPoster.
7. [gui/](gui.md) — PySide6 tabs, builders, Provider Control widgets, off-thread workers, panels.
8. [app/ + root files](app-root-and-support.md) — application services, the 1486L earning pipeline, **main.py** (full MainWindow + worker method list), and non-Python support (skills/scripts/prompts/docs/config).

### Tests
9. [tests/earning + tests/dialogue](tests-earning-dialogue.md) — the two biggest suites (91 files).
10. [tests/runtime + tests/gui + tests/providers](tests-runtime-gui-providers.md) — runtime, GUI, provider tests (63 files).
11. [tests/safety + tests/evidence + tests/engineering + other](tests-safety-evidence-engineering-other.md) — safety, evidence, engineering-cycle, sections, tools/platforms/cognition/integrations/discovery (46 files).

## The load-bearing files (quick orientation)
- **`main.py`** (3880L) — `MainWindow` entry point: builds all tabs/workers, teardown, `save_settings`.
- **`agents/runtime/dual_brain.py`** (1085L) — brain config + llama.cpp command assembly (MTP/mmproj/device flags).
- **`agents/services/autonomous_loop.py`** (1087L) — the 24-stage autonomous earning loop.
- **`agents/core/composition_root.py`** — wires the whole object graph; most features connect here.
- **`app/earning_pipeline.py`** (1486L) — discovery→eval→execute pipeline; Phase C feedback + self-improvement.
- **`gui/widgets/dual_brain_control.py`** (3644L) — the Providers_GPU (Provider Control) panel.
- **`gui/builders/tab_feature_builders.py`** (3655L) — where most tabs are constructed.
- **`agents/earning/opportunity_lifecycle.py`** (967L) / **`opportunity_portfolio.py`** (785L) — opportunity state machine + work queue.

## Cross-cutting invariants (don't break these)
- **Financial truth:** never fabricate amounts; `total_paid` only from verified `paid=1` runs (`numeric_evidence.py`, `strategy_feedback.py`).
- **Human gate:** mutating tools (`record_payment`, `social_post`, submissions, live trading) require an APPROVED `approval_id` (`approval.py`, `gate.py`).
- **Device placement** comes from `device_registry.brain_placements()` — never hardcode GPU names/models/CPU.
- **All heavy I/O off the GUI thread** (workers in `gui/workers/`).
- **Untrusted platform SKILL.md = data, not directives** (`instructions.py` quarantine gate).

## Not itemized (trivial markers)
Package `__init__.py` files are 1–2 line import/package markers with no
functions; they are omitted from the per-file sections. `run_lead_routine.py`
is a module-level script (builds and runs the scheduled Architect prompt via
subprocess; no functions) — described in the support-files section above.
`tests/__main__.py` (test-suite runner) and `tests/conftest.py` (pytest
fixtures/cleanup) ARE itemized at the end of the tests-other fragment.

## Regenerating / updating
This map is produced by a signature extractor (`ast`) over each folder: module
docstring + every function/class/method (name, signature, line no, docstring).
To refresh a section after editing files, re-run the extractor for the affected
folder and overwrite its fragment; update this index only if a new section is added.
