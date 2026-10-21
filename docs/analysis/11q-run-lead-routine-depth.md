# 11q — `run_lead_routine.py` depth pass (688 lines, 0 functions)

> **AI-01 RESOLVED in v2.1.125 (ARCH-ENG-264).** The prompt was escaped with
> POSIX single-quote rules (`replace("'", "'\\''")`) but is passed to
> `subprocess.run` as an argv list with no shell, so every apostrophe reached
> `hermes` as four literal characters. The prompt is passed unchanged.
>

Depth-pass #17 of 83. **No methods to sweep** — this file is document-shaped, and
that is itself the finding. It also confirms R-02, recorded in the very first area of
the original sweep.

---

## Structure

```
L    2-2      docstring
L    4-5      imports
L    7-661    prompt = "..."            <-- 655 lines, one string constant
L  664-672    escaped_prompt + cmd list
L  674-675    banner
L  677-688    subprocess.run + error handling
```

**655 of 688 lines (95%) are a single string constant** — the scheduled
Project-Lead routine prompt, 14,950 characters. The executable code is 11 lines.

I checked whether any other file in the depth-pass backlog is document-shaped and
**this is the only one** — the check ran against the 22 largest files and found no other
where long-string assignments exceed 40% of line count. The rest of the backlog is
genuine code.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AI-01 | low | **Shell-escaping applied to a non-shell argument.** `:664` runs `escaped_prompt = prompt.replace("'", "'\\''")` — replacing every apostrophe with the four-character sequence `'\''`, which is POSIX shell escaping. But `cmd` is passed to `subprocess.run` as a **list** with `shell` absent (verified: no `shell=True`), so no shell is involved and no escaping is required. The prompt therefore reaches `hermes` with a literal backslash inserted before each apostrophe. **Currently latent rather than live**: the 655-line prompt contains exactly **1 apostrophe** (in *"the implementer's conclusion"*), so one character is corrupted per run. Recorded because the defect is wrong in principle and would become serious the first time the prompt gains an apostrophe — which, for prose written by a language model or a human, is likely. |
| AI-02 | info | **`_prompt` is stored under the bare name `prompt`** (`:7`), shadowing nothing but colliding with `prompting_engine`'s domain vocabulary. Cosmetic; noted only because the module has no other structure to navigate by. |

---

## R-02 CONFIRMED — and it is the only remaining production instance

R-02, recorded in `00-root` at the very start of the original sweep, noted a cp1252
decode risk at `run_lead_routine.py:678` and attributed it to *"ARCH-ENG-226's own gap."*
Confirmed at the call site:

```python
subprocess.run(cmd, capture_output=True, text=True, timeout=600)
```

`text=True` with no `encoding=` decodes with the **locale default**. `hermes` emits
UTF-8; on a machine whose preferred encoding is cp1252 this raises
`UnicodeDecodeError` inside `subprocess`, which is caught by neither of the two handlers
at `:683`/`:686` and so propagates.

I swept the whole tree for the same shape — `capture_output` or `text` without
`encoding=` — and **this is the only production instance**. The other hits are:

- **`tools/profile_lag.py` (3 sites) and `tools/github_publish/github_upload.py` (8
  sites)** — the operator's personal tooling, deliberately untracked and excluded from
  the public mirror by `tests/tools/test_github_publish_sync.py`. Out of production
  scope by design.
- **`agents/integrations/wallet_crypto.py:86` and
  `agents/platforms/credential_vault.py:86`** — these carry `capture_output` **without**
  `text=True`, so they return `bytes` and perform no locale decode. They are false
  positives of my scan, not defects.
- **`.hermes/**` (4 files)** — internal scratch, excluded from the sweep's production
  scope.

So R-02's count was right: ARCH-ENG-226 fixed 7 of 8 production call sites and left
this one. It is a one-line fix, and it is now confirmed by call-site inspection rather
than by inference from a line number.

---

## Verified as sound

**The executor handles both realistic failure modes explicitly**: `TimeoutExpired` →
`sys.exit(124)` (`:683-685`) and `FileNotFoundError` → `sys.exit(127)` (`:686-688`).
Distinct exit codes rather than a generic 1, so a calling scheduler can tell "the model
took too long" from "the binary is not installed". That is the right granularity for a
600-second timeout on an LLM call.

**`timeout=600`** is explicit and matches the nature of the workload.

---

## Assessment

No functional defect of substance, and one genuinely useful confirmation.

The value of this pass is twofold. First, R-02 — a finding recorded 17 areas and 20
commits ago, before any of the depth-pass machinery existed — **holds up at the call
site**, and the sweep now confirms it is the sole production instance of its class.
That is the kind of check that justifies re-verification rather than assuming: the
finding could easily have been wrong, or could have been fixed since.

Second, the document-shape check was worth running. `run_lead_routine.py` sat at
position 17 in a largest-first backlog because it is 688 lines, and a method sweep would
have returned "0 functions, nothing to examine" — which is not the same as "nothing
wrong". Running the check across the 22 largest files confirmed it is the only such
entry, so the remaining backlog is genuinely code and can keep using the method-level
sweep unchanged.

AI-01 is the one item with a live effect, and it is one character per run today. Worth
fixing before the prompt changes rather than after.