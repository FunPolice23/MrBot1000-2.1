# 00 — Root

Three scripts. 4,442 lines, of which 3,735 is `main.py`.

Findings are numbered `R-nn` and recorded here only. They are **not fixed** until
the sweep completes — see [INDEX.md](INDEX.md).

---

## `__init__.py` — 19 lines

**Purpose.** Package docstring and the `__version__` re-export.

**Behaviour.** Imports `app.version.__version__`, falling back to a static
literal on any exception.

| ID | Sev | Finding |
|---|---|---|
| R-01 | low | The fallback `__version__ = "2.1.31"` is **92 releases stale** (real version 2.1.123). It only fires if `app.version` fails to import, which the comment says has no dependencies — so the fallback is close to unreachable. It is still a second version literal that can drift silently, and this codebase has already been bitten by that class: CHANGELOG records a ~30-release drift fixed in v2.1.31, the very release this fallback names. |

**Assessment.** Clean apart from R-01.

---

## `run_lead_routine.py` — 688 lines

**Purpose.** Scheduled "Project Lead" routine driver. **Not program logic**: 661
of 688 lines are a single `prompt` string; the remaining 27 shelve out to an
external tool.

**What it does.** Builds `hermes -p lead chat -c "Routine: ..." -q <prompt>` and
runs it with a 600 s timeout, forwarding stdout and the child's exit code.

**Entry point.** Invoked by the scheduler/cron, not the application. Deliberately
excluded from the GitHub sync — `tests/tools/test_github_publish_sync.py:82`
asserts it is in `SKIP_FILES`.

| ID | Sev | Finding |
|---|---|---|
| R-02 | med | **`subprocess.run(..., text=True)` with no `encoding` — line 678.** Decodes child output with `locale.getpreferredencoding()`, i.e. cp1252 on this machine, so any non-cp1252 byte raises `UnicodeDecodeError` in the reader thread. This is **the same defect as ARCH-ENG-226, and that ticket missed it**: the detector found 40 such call sites repo-wide, but the fix was narrowed to the 7 in `agents/` and `gui/`, and root-level scripts were never revisited. An incomplete fix, not a new one. |

**Note on the prompt.** The 655-line prompt is an unusually disciplined operating
manual — it explicitly requires distinguishing *observed* from *implemented* from
*verified*, forbids converting narrated or expected payout into verified revenue,
and forbids claiming a test or review occurred unless it did. Worth recording,
because it states intent that later areas can check code against.

**Assessment.** No logic to audit beyond the subprocess call.

---

## `main.py` — 3,735 lines

The application entry point: `MainWindow` (94 methods, 3,141 lines), three
module-level `QThread` workers (`HttpWorker`, `PipelineWorker`,
`ModelFetchWorker`), and eight module-level helpers.

### Structure

| Region | Lines | Role |
|---|---:|---|
| `_sanitize_sys_path`, `_ensure_qt_font_directory` | 57–131 | process start-up |
| worker classes + helpers | 295–410 | background work, log rendering |
| `MainWindow.__init__` | 427–640 | construction, **3 timers started** |
| `create_ui` | 1480 | the tab strip |
| log handling | 1357–1440 | bus → table |
| approval execution | 1032–1200 | **trust boundary** |
| `save_settings` | 2697–3164 | **467 lines — a quarter of the class** |
| `shutdown` | 711 | lifecycle |

### Findings

| ID | Sev | Finding |
|---|---|---|
| R-03 | med | **`save_settings` is 467 lines writing ~100 keys through 13 `except: pass` blocks** (the highest silent-handler density in the class — 13 of 41). It is one function doing env persistence, provider modelling, roster save, FX toggles, budget controls, live model switching, and restart prompting. A single `try` wraps the tail, so a failure in one group can silently skip the rest; only the last group logs (line 3066). This is the same *shape* as ARCH-ENG-195 (values added after the write) and as ARCH-ENG-201 (a second definition silently replacing the first) — one oversized writer where a partial failure is invisible to the operator. |
| R-04 | low | **Dead workaround with a misleading comment — lines 3068–3076.** Three `DIALOGUE_*` keys are pushed into `os.environ` *before* `load_dotenv(override=True)`, with the comment "This must happen BEFORE `load_dotenv(override=True)` below, which would otherwise restore the stale .env values over them." There are no longer any stale values: ARCH-ENG-195 moved every `values[...]` assignment to before the single `set_env_values` write at :3080, so `load_dotenv` re-reads what was just written. The block is now a no-op whose comment asserts a necessity that no longer exists. |
| R-05 | info | **API keys are persisted to `.env` in plaintext** (`:2771`, `values[f"{prefix}_API_KEY"] = key`). This is the intended design and `set_env_values` is careful about *content* (it refuses to persist a comment as a value, and will not blank a protected key with an empty one), but nothing here constrains **file permissions**. `.env` also holds a `CASHAPP_TAG` and `ATOMIC_SOLANA_ADDRESS`. Flagged as an operational note for the operator, not a code defect. |
| R-06 | info | Three timers are started in `__init__` (`_balance_timer` 60 s, `_db_stats_start_timer` 600 ms, and the self-improvement monitor). `_balance_timer` and `_db_stats_start_timer` are stopped in `shutdown` (`:723`–`:726`). The self-improvement monitor is **not** in that stop list, so it survives `shutdown()` and keeps firing until the process exits. |

### What is done well

Worth recording so later analysis does not "fix" it:

- `set_env_values` (`app/environment.py:118`) is a genuinely careful writer —
  it refuses on a blocked path, drops comment-shaped values instead of baking
  them in (a real past incident: the Nous key once persisted as
  `"# Optional: Your Nous Research API key"` and every request 401'd), refuses to
  blank protected keys with an empty value, preserves unknown keys and comments,
  and retries an atomic replace five times against Windows lock races.
- `_append_log_to_table` was correctly gated on tab visibility (ARCH-ENG-223), and
  deferring is safe because `_log_emit` buffers everything and
  `_replay_log_buffer` / `_do_apply_log_filter` rebuild from it.

**Status: partial.** The approval-execution path (`:1032`–`:1200`) and
`_submit_proposal_gui` (`:1888`) are the trust boundary and are analysed next.