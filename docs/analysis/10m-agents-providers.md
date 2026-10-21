# 10m — `agents/providers/`

> **L-01 RESOLVED in v2.1.125 (ARCH-ENG-298).** `model_recommendations.summary()`
> is now surfaced on each `BrainSettingsRow` for its bound model, so the
> per-family llama.cpp guidance is visible where the operator edits the
> settings. Nothing is auto-applied.

13 scripts, 3,647 lines. The model-adapter layer: provider detection, adapters for
Ollama / OpenAI-compatible / Anthropic / llama.cpp, GGUF metadata, Hugging Face
discovery, and hot-reload.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 29 | facade re-exporting all adapters |
| `anthropic_adapter.py` | 55 | `worker_provider_mixin.py:90, 108` |
| `context_table.py` | 62 | all three adapters (relative import) |
| `model_capabilities.py` | 90 | `brain_control_row.py` |
| `ollama_adapter.py` | 131 | `main.py` |
| `model_recommendations.py` | 153 | **nothing** |
| `provider_hot_reload.py` | 189 | `main.py` ×2 |
| `provider_lifecycle.py` | 279 | `dual_brain_control.py`, `provider_lifecycle_backend.py` |
| `openai_compatible.py` | 374 | `big_brain`, `small_brain` ×2 each |
| `gguf_meta.py` | 473 | 13 sites — `prompting_engine`, `brain_contention`, `dual_brain` |
| `model_profile.py` | 558 | `big_brain`, `small_brain` |
| `huggingface_models.py` | 557 | `model_library_tab.py` |
| `provider_manager.py` | 697 | 15 sites — `device_registry`, `hardware_plan`, `tab_feature_builders` |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| L-01 | med | **`model_recommendations.py` (153 lines) is dead.** *"Per-model recommended llama.cpp settings (Phase G)"* — `_detect_family` (`:111`), `recommend` (`:119`), `summary` (`:143`). `_detect_family` has two production references, both inside its own module; `recommend` and `summary` have **zero production importers of any form**. Five test references. This is the module that would translate a model name into sensible llama.cpp flags, and it is not consulted by anything that launches a model. Worth pairing with `llama_setting_help.py` (live, 2 GUI sites) when deciding whether the recommendation path is unfinished or superseded. |
| L-02 | info | **Two modules look dead and are not — facade and relative imports again.** A reachability scan flagged both `anthropic_adapter` and `context_table` as having zero production consumers. Both are live. `AnthropicAdapter` is constructed at `agents/brains/worker_provider_mixin.py:108` via the package facade rather than a direct `agents.providers.anthropic_adapter` import, and `context_table.lookup_context` is imported by all three adapters using **relative** imports (`from .context_table import lookup_context` at `anthropic_adapter.py:7`, `ollama_adapter.py:12`, `openai_compatible.py:28`). This is the third time in this sweep that relative imports have defeated a reachability scan — the first was `agents/earning/__init__.py`'s 21 relative imports, where the same blind spot cost nine false positives before it was caught. |

---

## Verified as sound

**The hardware policy is genuinely encoded, not just documented in prose.**
`agents/runtime/brain_roster.py:26` carries the rule as an explicit ARCH-ENG-219
constant: *"ONE MODEL PER DEVICE, UNLESS THE DEVICE HAS >= 32 GB VRAM"* — matching
the stated constraint exactly, including the VRAM threshold that makes the
exception conditional rather than absolute.

**VRAM estimation has a single named authority.** `brain_contention.py:28`
describes `agents.providers.gguf_meta.estimate_vram_gb` as *"the single source of
truth"* for VRAM need, with a documented preference for the real GGUF and an
explicit fallback. `gguf_meta.py:389` is the implementation, and its reachability
(13 production sites including `prompting_engine`, `brain_contention` and
`dual_brain`) is consistent with that claim — this is not one of the codebase's
"correct but unwired" mechanisms.

The system-RAM accounting requirement is also directly addressed:
`brain_contention.py:43` records that `estimate_model_ram_gb` *"used to add KV to
system RAM only when…"* — i.e. the GPU-also-uses-system-RAM correction was a
specific fix rather than an accident. (Both files are in `agents/runtime/`, which
is the next area, and will be assessed there rather than here.)

**The two context-window tables are correctly distinguished, not duplicated.**
A first pass flagged `context_table.MODEL_CONTEXT_TABLE` (`gpt-4o*`: 128000,
`claude*`: 200000) and `dual_brain._VRAM_TIER_CONTEXT` (`((8.0, 8192),
(12.0, 16384), (24.0, 32768))`) as two competing authorities for the same fact.
They are not. The comment at `dual_brain.py:753` states the division: *"Used when
there is no GGUF to measure — e.g. a cloud provider, or a local slot whose model
name is not a path."* One answers "what does this API model support?", the other
"what can this GPU hold?". Both are reachable and both are used.

**`openai_compatible.py` extends the SSRF guard to provider base URLs** —
`agents/providers/__init__.py:14` records that *"any user-supplied base_url is
validated through `InstructionGate._is_safe_fetch_url`"*, with its own literal
blocklist at `:301-313` covering metadata, multicast and reserved ranges. This is
the *correct* application of the convention I-01 found missing in the browsing
layer: a guard applied at the boundary where the untrusted value enters.

---

## A methodology note — the third shell failure

The alternation-handling failure that produced ~150,000 nonsense hits in
`agents/knowledge/` and again in this area is a **shell-escaping problem, not a
regex problem**. A pattern containing `|` passed through the PowerShell heredoc
into `git grep -E` does not survive as one argument. It has now corrupted three
separate results this session, each of which had to be discarded and re-derived.

The replacement — globbing the tree in Python and scanning file contents directly
with `re.compile` — completed in one call with clean output and no shell
involvement. **That is the method to use for the rest of the sweep.** The earlier
`grepE` helper is retained only for single-token, no-alternation patterns.

This matters beyond tidiness: two of the corrupted results were on the same class
of question (is X reachable), which is exactly the class where a garbage result
is most likely to be believed rather than re-checked.

---

## Assessment

This area is in good shape. Every module except one has a live consumer, the
adapters are reached through a consistent facade, and the VRAM/context logic —
the part most likely to be subtly wrong on the user's actual hardware — has a
named single authority and a documented division of labour between the two
context tables.

`L-01` is a modest dead module by the standards of this sweep. It matters slightly
more than its size because it sits on a path the operator would reasonably expect
to be automatic: choosing llama.cpp settings for a downloaded model. Its absence
is consistent with `model_recommendations` having been an early design that
`gguf_meta` later made unnecessary — `estimate_vram_gb` and the live
`llama_setting_help` cover the ground between them. That is a retirement
decision, not a wiring one.

The reachability lesson is the more transferable output. Three separate blind
spots have now produced false positives in this sweep — dict-valued dispatch in
`agents/core`, return types used by attribute access in `agents/earning`, and
facade/relative imports here. All three share a cause: **a module reached by an
indirect path looks identical to a module reached by no path.** For the remainder
of the sweep, reachability claims are checked by symbol *and* by import form
before they are recorded.