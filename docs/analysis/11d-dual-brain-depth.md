# 11d — `agents/runtime/dual_brain.py` depth pass (1,381 lines, 39 methods)

> **X-01 RESOLVED in v2.1.125 (ARCH-ENG-270).** `get_template_info` existed "for
> logging purposes" and had no caller. It is deleted, and `build_llama_command`
> now logs at the point the `raise_exception` fallback template is applied --
> an info line naming the model and template length, or a warning when no
> fallback exists and the server may reject every request.
>

Depth-pass #4 of 83. The most-used module in the repository (37 outside consumers).
**37 of 39 live — 2 dead**, and both are reporting wrappers rather than mechanism.

---

## Structure

```
L   61-63     class BrainRole (Enum)
L  154-514    class BrainConfig           -- 7 methods
L  982-1356   class DualBrainRuntime      -- 20 methods
  + 12 module-level functions (107-1362)
```

The module-level functions carry the hardware contract:
`_server_bin`, `estimate_model_size_b`, `is_cpu_decision_model`,
`choose_cpu_decision_model`, `build_slot_config`, `_apply_saved_settings`,
`apply_hardware_fallback`, `_resolve_provider_endpoint`, `_config_from_roster_slot`,
`_vram_safe_context` (80L), `build_config` (140L), `default_contract`.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| X-01 | low | **`BrainConfig.get_template_info` (`:407`, 14 lines) is dead — but the mechanism it reports on is live and correct.** The method reads GGUF metadata for `tokenizer.chat_template`, flags `"raise_exception"` in the template, and returns the fallback. Its companion `_get_fallback_template` (`:439`) and predicate `_model_needs_raise_exception` (`:423`) **are** live: `:400-403` applies the fallback when building the llama-server command. So the fix works and only its *"for logging purposes"* wrapper is unwired. Benign — and a useful counterexample to the sweep's usual result. |
| X-02 | info | **`DualBrainRuntime.provider_diagnostics` (`:1043`, 5 lines) is dead** — a thin delegation to `agents.core.configuration.redacted_configuration` for "operator diagnostics". Note the redaction is the point: the diagnostic path deliberately goes through a redacted view rather than raw settings. |

---

## Verified as sound — the hardware contract, verified cross-module

Every function implementing the stated policy is genuinely wired, and **cross-module
rather than self-referential**:

| Function | Refs | Cross-module callers |
|---|---:|---|
| `apply_hardware_fallback` | 7 | `agents/__init__.py:12,38` (facade export), `dual_brain.py:246` |
| `choose_cpu_decision_model` | 4 | **`provider_lifecycle_backend.py:587,599`** |
| `is_cpu_decision_model` | 8 | **`provider_lifecycle_backend.py:587`** |
| `estimate_model_size_b` | 4 | internal + `dual_brain.py:1377` |
| `build_slot_config` | 7 | `brain_roster.py:294`, `speaker_registry.py:165,167` |
| `_config_from_roster_slot` | 2 | `dual_brain.py:857` |

`choose_cpu_decision_model` and `is_cpu_decision_model` being called from
`provider_lifecycle_backend.py` (assessed in `11b` as 61-of-63 live) is the concrete
evidence that the CPU/RAM path is exercised from the GUI, not merely declared.

**`_apply_saved_settings` (`:592`) and `apply_hardware_fallback` (`:633`) together
are the hardware-policy path**, and the module docstring is explicit about the
contract: *"Big Brain → available primary GPU or configured provider; Small Brain →
secondary GPU, CPU/system RAM, or configured provider"*, with *"Every component
(adapters, GUI, legacy workers) reads it"*.

**The command builder documents a Windows-specific constraint correctly.**
`dual_brain.py:280-283`: this llama.cpp line *"rejects numeric indices
(`--device 1` → 'invalid device') and the WindowsApps MSVC build can't run the
1660 Super at all"*, so the device is passed **by name** (`CUDA0`/`CUDA1`). That
matches `scripts/launch_llamacpp_brain.ps1` exactly, which also uses `$Device =
"CUDA0"` / `"CUDA1"`. The runtime and the launcher agree on the constraint, which is
the kind of agreement that usually decays and here has not.

**The `raise_exception` template fallback is documented with its blast radius**
(`:285-288`): *"detects models with Jinja templates that use `raise_exception()`
(e.g., Ministral, Qwen3.5+, Gemma 4) … since llama.cpp doesn't provide that
function."*

**`_model_needs_raise_exception` (`:423`) deliberately avoids a GUI-thread freeze**
and says why: *"Reads ONLY the chat-template key (scalar metadata) — a full
`read_metadata()` would materialise the ~128k-token vocab on the GUI thread and
freeze the window for seconds on every Start click."* That is the same
reasoning class as ARCH-ENG-221's `gguf_meta` caching.

---

## Re-verification of earlier findings

**M-03 confirmed unchanged.** `_vram_safe_context` (`:758-837`) is live and its
fallback path at `:831-836` still ignores `kv_type_bytes`, `role`, `gpu_layers` and
model size. Since `*_MODEL_PATH` is unset in `.env`, the fallback remains the active
path on both of the operator's cards. **This is now the third file where M-03's
conditions have been re-checked and found unchanged** — the finding is stable, not
an artefact of one reading.

**M-04 confirmed.** The redundant `min(fits, default_context)` at `:818` and `:819`
is still present (`:818` is `fits = max(4096, min(fits, default_context))`, `:819`
repeats the `min`). Harmless; the 4096 floor is deliberate.

---

## Assessment

This is the strongest result in the depth pass so far, and it is worth being
explicit about why: **37 of 39 live, and both dead methods are diagnostic wrappers
rather than mechanism.** That is the opposite of the `main.py` result (a dead island
around a trust mechanism) and the `earning_pipeline.py` result (a dead island around
three feature gates).

X-01 is the finding I'd point at as the counterexample to the sweep's thesis. The
chat-template fallback is **fully live** — `:400-403` applies it to the actual
llama-server command — and the codebase documents both the models it targets
(Ministral, Qwen3.5+, Gemma 4) and the reason llama.cpp needs it. Only the
"for logging purposes" report is unwired. That is what a correctly-scoped fix looks
like when the mechanism matters and the observability doesn't.

The hardware-policy verification here is also the strongest evidence in the sweep
for your specific constraints. The functions that implement "one model per device",
"CPU/RAM decision models" and "fall back to secondary GPU" are not only present but
**called from a different package** — which is what distinguishes a wired mechanism
from a self-referential one.