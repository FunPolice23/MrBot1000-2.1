# 10t — `scripts/`, `tools/`, `skills/`, `tmp/`

The remaining small areas: 8 launchers, 4 dev tools, 1 Python + 7 markdown skills,
and 6 debris probe scripts.

> **Tracker correction.** `INDEX.md` labelled this area `70-launchers/`. No such
> directory exists. The 8 launchers are in **`scripts/`** (6 `.ps1`, 2 `.bat`, all
> tracked, ~155 lines). The heading has been corrected.

---

## `scripts/` — 8 launchers, all tracked

| File | Lines | Role |
|---|---:|---|
| `launch_llamacpp_brain.ps1` | 64 | Shared llama.cpp launcher |
| `start_big_brain_llamacpp.ps1` | 3 | shim → `-Role Big` |
| `start_small_brain_llamacpp.ps1` | 3 | shim → `-Role Small` |
| `launch_lm_studio.ps1` | 27 | LM Studio, 5060 Ti only |
| `launch_lm_studio.bat` | 6 | wrapper |
| `start_dual_brain.ps1` | 26 | LM Studio, both GPUs visible |
| `start_small_brain_ollama.ps1` | 22 | Ollama on the 1660 Super |
| `start_small_brain_ollama.bat` | 4 | wrapper |

**These correctly encode the stated hardware policy.** `launch_llamacpp_brain.ps1`
is a single shared launcher with `[ValidateSet("Big", "Small")]` and per-role
defaults — Big → `Qwen3.8-27B-UD-IQ3_XXS` on `CUDA0`, port 1234; Small →
`Qwen3.5-4B-UD-Q5_K_XL` on `CUDA1`, port 1235. The two 3-line shims provide role
selection without duplicating any launcher logic, which is the right factoring.
It fails closed when the binary is absent (`Write-Error` + `exit 1`), builds the
command as an array with `"--n-gpu-layers", "all"`, appends `$ExtraArgs` from
`ValueFromRemainingArguments`, and propagates `$LASTEXITCODE`.

`start_small_brain_ollama.ps1:13` sets **`OLLAMA_MAX_LOADED_MODELS = "1"`** — the
one-model-per-device rule enforced at the provider level rather than by convention.
Alongside `CUDA_VISIBLE_DEVICES=1`, `OLLAMA_HOST=127.0.0.1:11435` and
`OLLAMA_KEEP_ALIVE=5m`, this is the most policy-faithful file in the repository.

The banner prints **`GPU: $gpuLabel + RAM`** (`launch_llamacpp_brain.ps1:45`) —
the requirement that a GPU slot still consumes system RAM, made visible in the
operator's console.

### Findings

| ID | Sev | Finding |
|---|---|---|
| T-01 | low | **Two launchers named for the same app invoke different binaries and set GPU visibility differently.** `launch_lm_studio.ps1:13` targets `D:\LMStudio\Bionic\LM Studio.exe` and sets `$env:CUDA_VISIBLE_DEVICES = "0"`; `start_dual_brain.ps1:26` invokes `D:\LMStudio\Bionic\Bionic.exe` and sets no environment variable at all, relying instead on per-model GPU selection in LM Studio's GUI (documented at `:12-16`). One of those paths is stale, and the two scripts disagree about whether GPU isolation is environmental or configured by hand. An operator running the wrong one gets both GPUs visible to LM Studio, which is exactly the collision the hardware policy exists to prevent. |
| T-02 | info | **Operator-specific absolute paths are committed.** `D:\llama.cpp\llama-server.exe`, `D:\llama.cpp\models\…`, `D:\LMStudio\Bionic\…` appear in four launchers. Defensible for personal tooling, and `launch_llamacpp_brain.ps1` correctly parameterises `$LlamaServerPath` and `$Model` so the shared launcher is portable — but the three thin wrappers around it are not. |

---

## `tools/` — 4 files, 1 tracked

| File | Lines | Tracked |
|---|---:|---|
| `profile_lag.py` | 58 | **yes** |
| `gen_codemap.py` | 186 | no |
| `github_publish/github_upload.py` | 396 | no |
| `github_publish/sync_github_upload.py` | 285 | no |

The three untracked files are the operator's personal publishing and codemap
tooling. Their exclusion is **deliberate and tested**:
`tests/tools/test_github_publish_sync.py` asserts that `tools/` and
`tools/github_publish` never reach the public mirror, that `run_lead_routine.py`
is excluded, and that stale destination paths are actively purged so the copy
engine cannot reintroduce them. That test also `skipif`s cleanly when the tooling
is absent, which is why a fresh clone does not fail.

`profile_lag.py` is tracked and is a read-only py-spy wrapper with an unusually
good header: it states *"Run this WHILE the app is lagging… Read-only; touches
nothing"*, gives the exact `pip install` command for the interpreter in use, and
its usage banner reads *"Send me this output"* — written for the operator, not for
a future maintainer.

---

## `skills/` — 1 Python file, 7 markdown documents

`skills/__init__.py` (11 lines, tracked) plus seven skill documents, all tracked:
`document-qa.md`, `job-execution-plan.md`, `moltbook-agent.md`,
`opportunity-evaluation.md`, `opportunity-execution.md`, `opportunity-filtering.md`,
`opportunity-lifecycle.md`.

These are the documents the `platform_skill_urls.py` map points at and that the
`InstructionGate` quarantines on fetch (`agents/safety/instructions.py`, assessed
in `10o`). The separation is the point: the documents are reference material
fetched through a guard, and `registration.py`'s docstring states they are
*"reference material for the human, never executable authority."*

---

## `tmp/` — 6 debris scripts, all untracked

| File | Lines | Purpose (from its own docstring) |
|---|---:|---|
| `probe_review.py` | 103 | adversarial probes for ARCH-ENG-088..091 |
| `ae151_sweep.py` | 156 | ARCH-ENG-151 sweeper |
| `probe_concurrency2.py` | 34 | force 12+ threads inside `guard.check` |
| `probe_concurrency3.py` | 33 | widen the push→pop window |
| `probe_concurrency.py` | 27 | force ≥10 threads |
| `probe_repeat.py` | 10 | when the repeat rule fires |

**Recorded, not deleted**, per the standing instruction. All six are untracked
(`git ls-files` returns nothing), so they cannot reach the public mirror — this is
N-03 from `agents/safety/`, restated here as the owning area.

Also present and untracked: `tmp/dbl/` and `tmp/subtest/` (4 and 2 small JSON
files respectively — workshop subdirectories from practice-copy verification),
`tmp/lead_routine_prompt.txt` (15 KB), `tmp/suite_baseline.txt` and three
`suite_run*.txt` artifacts, and the two **zero-byte** entries `dbl` and `subtest`.

---

## Assessment

The launchers are the best-documented small artifacts in the repository. They are
parameterised where it matters, factored so role selection costs three lines,
fail closed on a missing binary, propagate exit codes, and — unusually for a shell
script — encode and *display* the hardware constraints they enforce.

T-01 is the only real finding and it is a genuine operational hazard rather than a
code defect: two scripts with near-identical names launch different binaries and
disagree about how GPU isolation is achieved, and running the wrong one defeats the
isolation the whole set exists to provide.

`tools/`, `skills/` and `tmp/` are correctly arranged. The personal publishing
tooling is excluded from the mirror by design *and* by test, which is a stronger
guarantee than the `.gitignore` entry alone. The `tmp/` debris is harmless to the
product and corrosive only to tree-wide analysis — which is why it is documented
rather than removed, and why the `.gitignore` line noted in N-03 is still worth
adding.