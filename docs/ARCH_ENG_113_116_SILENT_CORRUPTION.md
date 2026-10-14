# ARCH-ENG-113/114/115/116 — silent corruption under test capture

**Status:** **RESOLVED in v2.1.92**
**Resolved:** 2026-10-13, v2.1.92 continuous-engineering cycle

Four defects, one theme: **the system stated something it had not verified.**
All four were found by running the suite the way an operator runs it
(`pytest -s`, and the default fd capture) instead of the way that happened to
pass in-tree.

The lesson that generalises past these four bugs is at the bottom.

---

## ARCH-ENG-113 — an explicit `path=` escaped `.env` test isolation

**Symptom.** The suite sometimes aborted at teardown with
`AssertionError: the test suite modified .env`, pointing at a one-byte diff.

**Root cause.** `app/environment.py::set_env_values(values, path=...)` lets a
caller name the target file directly. Two GUI persistence paths used that to
retry a failed write against a **hardcoded** `<repo>/.env`:

- `gui/widgets/dual_brain_control.py` → `_persist_settings`
- `gui/workers/provider_lifecycle_backend.py` → `_write_env_values`

The isolation guard `_env_write_refusal()` only refused when
`MRBOT_ENV_PATH` was **unset**. Under pytest the override **is** set, so the
write was permitted — and the explicit path pointed at the operator's live
credentials file. A guard that checks "is an override configured?" does not
check "does the caller's own argument defeat the override?".

**Reproduced.** One transient failure on the isolated write rewrote the live
`.env`: every CRLF became LF and a provider toggle flipped. Byte-level diff
captured.

**Fix.** `_env_write_refusal(path)` now resolves the caller's target and refuses
it under pytest whenever it resolves to the repository's own `.env` — absolute,
relative, or via `..`. An explicit *isolated* path still writes, so the
legitimate production fallback (CWD != repo root) is untouched. The guard
remains test-only: outside pytest nothing changes.

**Discrimination.** `tests/engineering/test_arch_eng_113_env_fallback_bypass.py`
(6 tests): 2 failed + 1 error with the fix stashed, 6 passed with it applied.
The module is **self-healing** — it snapshots the live `.env` and restores it if
an attempt ever succeeds, because otherwise detecting this regression would
itself corrupt operator config, which is the very failure mode under test.

---

## ARCH-ENG-114 — `pytest -s` silently enabled safe mode for the session

**Symptom.** 3 tests in `tests/safety/test_safe_mode_pipeline.py` failed, in a
file that passes 5/5 when run alone.

**Root cause.** `main.py` defines `-sm` / `--safe-mode` and called
`parse_known_args()` unconditionally **at module scope**. `parse_known_args` is
deliberately permissive, and argparse expands the short-option cluster `-s`
followed by `m` into `-sm`:

```
parse_known_args(['-s'])  ->  safe_mode=True     # measured
```

Any host process that imported `main` and owned `argv` therefore had its flags
consumed. pytest's `-s` (no capture) was the trigger, so
`python -m pytest -s` set `MRBOT_SAFE_MODE=true` process-wide.
`ActionPipeline.__init__` reads that env var, so every pipeline built afterwards
skipped its file writes.

**Traced** with an `os.environ` audit hook: the write originates at
`main.py:107`, reached via `tests/conftest.py:115` (`import main` inside the
`_track_mainwindow_instances` fixture).

**Fix.** Guard the parse on `if __name__ == "__main__"` — only the real
entrypoint consumes argv. `python main.py -sm` still enables safe mode
(verified by executing the guarded block under `__name__ == "__main__"`).

**Discrimination.** `tests/engineering/test_arch_eng_114_argv_collision.py`
(6 tests): 3 failed unfixed, 6 passed fixed. Note the entrypoint test drives
the *guarded block* rather than executing `main.py` as `__main__`, because that
would boot the whole GUI.

---

## ARCH-ENG-115 — a brain prompt asserted hardware detection never confirmed

**Symptom.** `tests/runtime/test_brain_prompt_hardware.py::...not_hardcoded`
failed ~50% of runs.

**Root cause.** Both `_hardware_line()` implementations fell back to
`cfg.gpu_label` when the device registry came back empty. That default is a
literal placeholder: `ROLE_DEFAULTS[BIG]["gpu_label"]` is the string
`"GPU 0 (detected hardware)"`. So whenever `nvidia-smi` returned nothing, the
brain was told — as fact — that it runs on a specific GPU that had never been
detected.

**Measured.** With detection stubbed to CPU-only, the old code produced:

```
"You run on GPU 0 (detected hardware)."
```

while the only detected device was the CPU/RAM pool.

This is an evidence-integrity defect in the same family as the project's
financial-truth rules: an inferred or defaulted value presented as observed
fact. It is also what made the test flaky — detection intermittently yields
CPU-only, the prompt still claims "GPU 0", and the "names a real detected
device" assertion fails.

**Fix.** No confirmed device → no hardware section at all. Omitting is strictly
better than asserting a false one. Applied to both adapters.

**Discrimination.**
`tests/engineering/test_arch_eng_115_hardware_placeholder.py` (5 tests):
5 failed unfixed, 5 passed fixed. The structural lock inspects **parsed code**
(AST, docstring stripped), so the explanatory comment that names `gpu_label`
does not trip its own assertion.

---

## ARCH-ENG-116 — GPU detection reported ZERO GPUs on a two-GPU box

**Symptom.** `tests/gui/test_gui_smoke.py::test_management_tab_builds` failed
with 1 persona field instead of 3, and the run took 8s instead of 3.4s.

**Root cause — two compounding defects in `_detect_gpus`.**

1. **The spawn failed and was swallowed.** `subprocess.run(...,
   capture_output=True)` must duplicate whichever standard streams it is given
   so the child can inherit them. On Windows that `DuplicateHandle` fails with
   WinError 50 / errno 22 when the parent's own stdout is a pipe a capture layer
   has reconfigured — exactly what pytest's default `--capture=fd` does.

   The failing handle was **stdin**, not stdout. `_get_handles()` duplicates
   every stream it is handed, and leaving stdin implicit made it inherit the
   capture pipe. A bare `except Exception: continue` then made a spawn failure
   indistinguishable from "this query form is unsupported".

   Measured: `_detect_gpus()` under `--capture=fd` raised
   `OSError(22, 'The request is not supported', None, 50, None)` and returned
   0 GPUs; under `--capture=sys` or `-s` the same code returned both cards.

2. **The documented fallback was dead code.** The ProviderManager fallback
   called `get_gpus(detect=False)`, which returns the manager's **cached** list
   — empty until something has probed. The fallback only runs when nvidia-smi
   has already failed, so nothing had probed: it returned `[]` every time.

**Impact when both fired.** Every caller saw a GPU-less box: the Management tab
built 1 persona field instead of 3, and the brain prompts dropped their
hardware section entirely.

**Fix.**
- New `_run_nvidia_smi()` names all three std streams explicitly — stdout to a
  real temp file, stdin and stderr to DEVNULL — so nothing has to be inherited.
- The fallback forces a probe with `detect=True`.
- New `_LAST_DETECT_ERROR` records why a probe could not run, so a caller can
  distinguish "this box has no GPUs" from "we could not ask". Those two must
  never be conflated.

**Discrimination.**
`tests/engineering/test_arch_eng_116_gpu_detection_capture.py` (6 tests):
2 failed unfixed, 6 passed fixed. Verified 5/5 consecutive runs under the exact
`--capture=fd` mode that was failing, at 3.4s (was 8.2s).

---

## Verification

Full suite on the authoritative interpreter (global Python 3.14, per the
project convention — the venv `python` is 3.11 and is NOT the runtime):

```
1759 passed, 5 skipped, 106 subtests passed
```

- Re-run with `-s`, the operator flag that exposed 113 and 114: identical.
- `.env` byte-identical before and after the entire run.
- Discrimination proven per fix: with each fix stashed its tests fail; with it
  applied they pass.

---

## Durable lessons

1. **A guard that checks whether an override is set is not a guard.** Check what
   the call actually resolves to. An explicit `path=` argument defeats an
   override the same way a hardcoded path does (113).

2. **Never parse `argv` at import time in a library module.** `parse_known_args`
   will consume whatever the host process owns, and argparse's short-option
   clustering turns an unrelated `-s` into your own `-sm`. Gate it on
   `__name__ == "__main__"` (114).

3. **A placeholder default must never be asserted as fact.** If a value could
   not be observed, omit the claim rather than substituting a default. This is
   the same rule the project already applies to financial truth — apply it to
   hardware, capabilities, and every other "observed" field (115).

4. **`except Exception: continue` converts an infrastructure failure into a
   plausible-looking wrong answer.** "Could not run the probe" and "the probe
   found nothing" are different states; conflating them produced a confidently
   false "zero GPUs". Record why a probe failed (116).

5. **A fallback you never exercise is not a fallback.** `detect=False` returned
   an empty cache on the only path that could reach it. Verify the fallback
   actually returns something (116).

6. **Run the suite the way the operator runs it.** All four defects were
   invisible under the command line that happened to be in use. `-s` and the
   default fd capture are both legitimate; a suite that only passes under one
   is not passing.
