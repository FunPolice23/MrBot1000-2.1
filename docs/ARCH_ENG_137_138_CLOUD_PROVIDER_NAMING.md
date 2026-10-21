# ARCH-ENG-137/138 — The cloud-provider path was wired to the wrong names

**Release:** v2.1.100 · **Date:** 2026-10-14 · **Status:** VERIFIED (executed)
**Cycle:** continuous engineering (no user assignment)

---

## 1. Where this came from

The N-brain roadmap's Phase 1 added cloud providers to the runtime in two commits:

- `5bb8144` — `agents/runtime/provider_keys.py`: `resolve_provider_api_key()`
- `0b4c7d0` — cloud providers become first-class in `dual_brain.py`; both brain
  adapters store `self.provider` and `_get_client()` sources the key via the
  resolver.

The ledger's 2026-10-14 scan flagged the seam immediately:

> **[wiring][P1] `agents/runtime/provider_keys.py:75` — the cloud API-key resolver
> never reads the env vars the app actually writes.**

This cycle applied the discipline that found v2.1.99's four credential leaks: audit
the **consumers** of a new seam, not the seam itself. That surfaced five defects
across three files, all in the same trust area (credential handling and the
guards that protect money).

---

## 2. Evidence — every defect was reproduced by execution first

### 2.1 ARCH-ENG-137 — the resolver matched none of its own names

The resolver's env chain was: encrypted vault → `PROVIDER_API_KEY_<PROVIDER>` →
`<ROLE>_API_KEY`.

Nothing in the repository writes the last two names. The Settings GUI persists the
standard spelling (`main.py:2705`, `values[f"{prefix}_API_KEY"] = key`) and provider
detection keys off that same spelling (`provider_manager.py:439-460`, `key_env`).
Confirmed against the live `.env`:

```
ANTHROPIC_API_KEY   DEEPSEEK_API_KEY   GROQ_API_KEY    OPENAI_API_KEY
OPENROUTER_API_KEY  TOGETHER_API_KEY   NOUS_API_KEY    MISTRAL_API_KEY
GEMINI_API_KEY      VLLM_API_KEY       KOBOLDCPP_API_KEY  LM_STUDIO_API_KEY
```

**Reproduction, before the fix** (`OPENAI_API_KEY` and `NVIDIA_API_KEY` set):

```
openai       -> ''
nvidia       -> ''
nvidia_nim   -> ''
groq         -> ''
anthropic    -> ''
llamacpp     -> 'local'
```

A cloud brain therefore failed closed on every call. Fail-closed is the right
*security* posture, but the cause here was a naming bug, not an absent key — the
operator had done everything correctly and got a silent 401.

**Reproduction, after the fix** (same environment):

```
openai       -> '***'          # the configured key resolves
nvidia       -> 'nvapi-test-1' # via the alias table
nvidia_nim   -> 'nvapi-test-1' # same key, runtime spelling
groq         -> ''             # genuinely unconfigured — still fails closed
anthropic    -> ''             # genuinely unconfigured — still fails closed
llamacpp     -> 'local'
```

### 2.2 ARCH-ENG-137 — the budget guard inverted itself

`CostGuard.should_skip` (`worker_llm_mixin.py:117`) skips a provider when the daily
cap is hit *unless* `is_local_provider` says it is free. The old
`agents/safety/cost.py` recognised only `ollama` and `local*`.

The adapter names the workers actually pass are `big-brain` and `small-brain`.
Under the old logic both were **BILLABLE**, so hitting the cap produced:

> "skipping paid provider 'big-brain', falling back to local" — and then spent
> money on a cloud provider.

The guard spent the real money it exists to prevent. Reproduced by execution: 14
test failures (6 tests / 34 subtests) against the old code, all passing after.

### 2.3 ARCH-ENG-137 — the free brain was throttled like a paid API

`provider_rate_limiter._LOCAL_MARKERS` had no `brain` entry. Verified by execution:

```
_defaults_for("big-brain") == (1.0, 500)   # the CLOUD tier
```

A hardware-bound llama.cpp brain on the 5060 Ti got a 500-calls/day ceiling and a
1/sec throttle it can outrun. After the fix: `(2.0, 0)` — uncapped.

### 2.4 ARCH-ENG-138 — the cloud brain could not authenticate

```python
def check_endpoint(url, timeout=10):
    req = urllib.request.Request(url)        # no Authorization header
```

A cloud `/v1/models` probe gets a 401, which the class catches and reports as
`(False, [])`. The Providers & GPU row therefore showed "Stopped" forever, even
with a valid key — reproduced by execution.

### 2.5 ARCH-ENG-138 — "Start" on a cloud brain always failed

```python
load_provider_model("openai", ...) -> (False, 'openai does not expose a model-load API')
load_provider_model("groq",    ...) -> (False, 'groq does not expose a model-load API')
unload_provider_model("openai", ...) -> (False, 'openai does not expose a model-unload API')
unload_provider_model("groq",    ...) -> (False, 'groq does not expose a model-unload API')
```

`provider_lifecycle_backend._start_external_brain` (`:718`) routes **every**
non-llamacpp role through `_load_external_model` → `load_provider_model`. So
"Start" on a cloud brain logged `❌ Big Brain openai does not expose a model-load
API` and could never reach Running. Reproduced by execution, above.

---

## 3. What changed

| File | Change |
|---|---|
| `agents/runtime/provider_keys.py` | Added `<PROVIDER>_API_KEY` to the env chain (ahead of the generic role fallback); added `_PROVIDER_ENV_ALIASES` (`nvidia_nim`/`nvidia` → `NVIDIA_API_KEY`). |
| `agents/safety/cost.py` | `is_local_provider` now recognises the on-machine set via `provider_keys.LOCAL_PROVIDERS` (spelling-normalised) plus any `-brain` adapter. |
| `agents/safety/provider_rate_limiter.py` | Added `"brain"` to `_LOCAL_MARKERS`. |
| `agents/providers/provider_lifecycle.py` | `_auth_headers()` derives a Bearer token through `provider_keys`; `check_endpoint` accepts `provider`/`api_key`; cloud `load`/`unload` are truthful no-op successes. |
| `gui/workers/provider_workers.py` | `check_endpoint` call passes `provider=` so the header is actually sent. |
| `gui/workers/provider_lifecycle_backend.py` | Same, at the roster probe site. |

### Design decisions

1. **One credential authority.** `_auth_headers` resolves through
   `provider_keys` rather than reading env directly, so there is no second place
   a credential convention can drift. The key is never logged; the tests assert
   that.
2. **A local provider still probes unauthenticated.** Sending a Bearer token to
   127.0.0.1 would be wrong, and `_is_local` short-circuits before the header is
   built.
3. **The cloud no-op is scoped to known vendors.** `_is_cloud` checks membership
   in `CLOUD_PROVIDER_DEFAULT_ENDPOINTS`. An unrecognised provider keeps its
   explicit failure — silently turning "unknown vendor" into a fake success would
   be exactly the fabrication class this codebase treats as its highest-severity
   bug.
4. **Provider-specific key beats role key.** `OPENAI_API_KEY` is checked before
   `BIG_API_KEY` so a deliberately per-provider key is never shadowed by a
   generic one.

### A mistake this cycle made, and what caught it

The first draft of the alias table included `lmstudio → LM_STUDIO`. The new test
`test_local_provider_never_consults_the_env_key_chain` failed on it:

```
AssertionError: 'local' != 'LMS_KEY_1'
```

`lmstudio` is in `LOCAL_PROVIDERS` and returns the `"local"` sentinel *before* the
env chain is reached. The alias was dead code — and had it not been, it would have
let an on-machine provider present a credential it does not need. The entry was
removed and the test kept as the guard on that invariant. This is the teeth-proving
discipline working on the fix itself, not just on the bug.

---

## 4. Verification

### New / extended tests

- `tests/providers/test_cloud_provider_lifecycle.py` (new, 10 tests) — Bearer
  header present for cloud and absent for local; the header reaching `urllib`;
  the key never hitting stdout; cloud load/unload succeeding **with no network
  call at all**; unknown vendor still failing explicitly; lmstudio still POSTing.
- `tests/runtime/test_provider_keys.py` (+5) — the standard spelling resolving for
  five providers; the NIM alias for both spellings; provider-key-beats-role-key;
  fail-closed intact when nothing is configured; local never consulting the chain.
- `tests/safety/test_cost_guard_local_classification.py` (new, 6 / 34 subtests) —
  local never skipped past the cap, billable skipped past the cap, disabled budget
  skipping nothing.
- `tests/safety/test_provider_rate_limiter.py` (+1) — brain adapters get the local
  tier (`cap == 0`, `rate >= 2.0`).

### Teeth proven by revert (not asserted against itself)

With all three production fixes reverted to HEAD:

```
29 failed, 28 passed, 4 subtests passed
```

Restored:

```
41 passed, 60 subtests passed
```

The cost-guard revert alone fails 14; the key-resolution revert fails the five new
env-spelling tests plus precedence; the lifecycle revert fails all 10 cloud
lifecycle tests. Each test targets behaviour and fails when the defect returns.

### Regression runs

- `tests/runtime` + `tests/providers` + `tests/safety`: **519 passed, 1 skipped,
  146 subtests**.
- GUI board / rate-settings suites (`test_dialogue_board_render.py`,
  `test_dialogue_board_title_sanitization.py`,
  `test_provider_rate_settings.py`): **11 passed**.

### Safety-boundary review

No human-approval gate, financial-evidence rule, or submission control was
touched. No LLM output became financial truth. No simulated value became verified
revenue. The change moves exactly one thing: a credential the operator already
configured now reaches the client that needed it, and the budget guard stops
skipping the free brain in favour of a paid one.

---

## 5. Open follow-ups

- **Live cloud smoke test** (still owed from the Phase-1 plan): a real endpoint
  plus a throwaway key, to confirm the end-to-end path now authenticates. Not
  done here because it requires a real credential and real spend.
- **`_sync_adapter_models` is defined nowhere** (`gui/tabs/dialogue_tab.py:487`,
  `:1215-1216`) — the real method is singular and lives on
  `ProviderLifecycleBackend`. Both guards are permanently False, so "Sync adapter
  models from GUI selection before responding" is a silent no-op on every turn.
  Ledger P1, still open.
- **`_build_provider_panels` is never parented** and its `_on_model_changed`
  persists to `.env` from a GUI callback (`dual_brain_control.py:463-465`,
  `:551-566`). Ledger P1, still open.
- **Version discipline drift:** the ten dialogue/runtime commits since v2.1.99
  (`3ba4851` … `5c12d0b`) touched neither `app/version.py` nor `CHANGELOG.md`.
  Not corrected here — recording another agent's unverified work as a release
  would be worse than the drift — but it needs a coordinated decision.

---

## 6. Lesson

**A seam that fails closed can still be broken.** Fail-closed is a security
property, not evidence of correctness: the resolver in this cycle was behaving
exactly as designed while being completely unable to read the configuration the
application itself writes. Auditing a new integration means checking that its
**inputs** are the ones the system actually produces, not just that its failure
mode is safe.

The corollary, learned from v2.1.99 and repeated here: the defect is never in the
function you just wrote. It is in the four consumers of that function nobody
looked at yet.
