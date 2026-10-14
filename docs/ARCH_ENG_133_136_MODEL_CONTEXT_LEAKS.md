# ARCH-ENG-133/134/135/136 — the model-context boundary leaked credentials through four more doors

**Status:** FIXED and verified (v2.1.99)
**Found:** continuous engineering cycle, 2026-10-14, by auditing the *consumers*
of the v2.1.98 `file_read` fix rather than the fix itself.
**Severity:** CRITICAL (134), HIGH (133/135/136)

## Why these four exist

v2.1.98 (ARCH-ENG-132) hardened exactly one function: `_tool_file_read` in
`agents/safety/handlers.py`. The audit that found it recorded the right lesson —
"the vault's own contract was defeated by a tool that never touches the vault" —
but the fix still treated the boundary as *one function* instead of *one
invariant*. Four sibling paths returned file content to the model with no guard.

**Lesson recorded: a security invariant hardened in one function is not hardened.
Every path that crosses the same trust boundary must be enumerated and fixed, or
the next cycle will find the same class of defect somewhere else.**

Nothing below is inferred from reading. Every claim was reproduced by executing
the real dispatcher or the real function.

## ARCH-ENG-133 — `legacy_tools` had a second, ungated file reader

`agents/safety/legacy_tools.py` implements its own tool set with its own private
`_read_file()`. The Big Brain tool loop (`agents/brains/big_brain.py:240
_execute_tool_calls`) classifies names with `SafetyGate`, which maps the alias
`read_file` → canonical `file_read` = READONLY = ALLOWED, then dispatches to
`legacy_tools.execute_tool` — **not** to the hardened `_tool_file_read`.

Pre-fix, executed:

```
execute_tool('read_file', {'path':'.env'})     -> 13,418 chars of .env
execute_tool('read_file', {'path':'wallet.key'}) -> 'dE23Hpd6...EKXMc='  (raw Fernet key)
```

**Fix:** `_read_file` reuses `_is_secret_file` (imported from `handlers`; verified
no circular import) plus `redact_secrets`. `_write_file`, `_run_command` and
`analyze_document` also refuse secret paths. Gate decisions verified unchanged:
`read_file` ALLOWED, `write_file`/`run_command` NEEDS_APPROVAL,
`analyze_document` still BLOCKED-as-unknown.

**Known limit (recorded, not fixed):** `run_command` refuses a command that
*names* a secret file. `python -c "print(open('.env').read())"` would still
exfiltrate it into command output. Closing that needs output-level scanning,
which belongs with the approval layer, not here.

## ARCH-ENG-134 — `workshop_read` read the whole workshop tree raw (CRITICAL)

`workshop_read` is READONLY/auto-allowed, and the workshop root
(`D:\ai_workshop`, `MRBOT_WORKSHOP_ROOT`) is **outside `PROJECT_ROOT`**, so
`resolve_project_path`/`_is_secret_file` never applied. `Workshop.read_file`
does a bare `open(path).read()`. The workshop's own `accounts/accounts.json`
stores a plaintext `password` (`Workshop.add_account`).

Pre-fix, executed against a populated workshop root:

```
workshop_read '.env'               -> 'OPENAI_API_KEY=sk-ZZZ...'
workshop_read 'wallet.key'         -> 'RAWFERNETKEYMATERIAL=='
workshop_read 'accounts/accounts.json' -> {"Upwork": {..., "password": "P@ssw0rd-abcdef"}}
workshop_read 'notes.md'           -> an unredacted sk-proj- key in prose
```

**Fix:** `_tool_workshop_read` applies the same two layers, via a new
`_is_workshop_secret_path()` that reuses `_is_secret_file` for everything and
adds a small workshop-only frozenset (`accounts.json`, `payments.json`,
`payment_methods.json`). Deliberately kept **separate** from `_SECRET_FILE_NAMES`
rather than merged: those names are credential-bearing only inside the
workshop's own schema, and merging them would have widened `file_read` for files
that do not exist in the project tree.

**Sibling tools verified clean by execution, no change made:** `workshop_list`
(name/size/mtime), `workshop_storage` (byte counts), `workshop_search`
(filename + match marker, never the matched text), `workshop_write` (approval
queued, nothing echoed).

## ARCH-ENG-135 — `redact_secrets` did not match this deployment's key formats

The pre-existing pattern set covered only wallet key material. The live `.env`
holds ~264 keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `UPWORK_CLIENT_SECRET`,
`UPWORK_REFRESH_TOKEN`, …) and **none** of those shapes matched. Executed
pre-fix — all six cases came back `redacted=False`:

```
OPENAI_API_KEY=sk-proj-AAAA...   password: P@ssw0rd-abcdef
token: ghp_HHHH...               Authorization: Bearer eyJhbG...
AWS_ACCESS_KEY_ID=AKIA...        api_key = "aGVsbG8..."
```

So the v2.1.98 "redact other content" layer was ineffective against the exact
secrets this deployment stores, and every consumer inherited the gap.

**Fix:** added value-shaped patterns (`sk-`, `gh[pousr]_`, `AKIA`, `xox[baprs]-`,
PEM blocks) and label-shaped patterns that replace only the VALUE and keep the
LABEL, so the model still learns *which* key is missing. Single marker
`[REDACTED-SECRET]`; idempotent; `contains_secret` extended to agree.

## ARCH-ENG-136 — the wallet's crown jewels survived anyway (found by review)

The Architect's independent adversarial review of 135 found the fix incomplete.
The pre-existing *bare-marker* rule matched the WORD `mnemonic` and replaced the
**label**, leaving the value readable:

```
in : mnemonic: abandon ability able about above absent
out: [REDACTED-SECRET]: abandon ability able about above absent
```

A seed phrase IS the wallet. Same for `seed_phrase`, `private_key`,
`WALLET_ENC_KEY`. Verified the four cases leaked, then fixed by adding the wallet
labels to the labelled rule set.

**A second leak found while fixing the first:** a BIP39 phrase is
SPACE-SEPARATED WORDS, so the labelled rule's `\S{6,}` captured only the first
word — 11 of 12 words still readable. Added `_SEED_PHRASE_RE` for the whole word
list.

**Two revisions were tried and REJECTED by execution**, and the rejections are
recorded in the code because they are the design rationale:

1. matching a bare word list with no label matched ordinary English prose
   ("3+ lowercase words" is also the shape of a sentence);
2. allowing `is/are/was` as the separator matched
   `The mnemonic is stored encrypted and never logged verbatim.`

`redact_secrets` runs on every file the model reads, so over-redaction would gut
the module and push callers to bypass it. The label plus `:`/`=` is mandatory.

**Residual risk, recorded honestly:** a phrase with no label, or after `is`, is
not caught. Pinned by
`test_unlabelled_or_is_separated_phrase_is_a_residual_risk` so a later change
cannot claim the gap is closed when it is not.

## Verification

- **Full suite (global Python 3.14, working tree): 2006 passed, 5 skipped,
  175 subtests passed.**
- `tests/safety`: **213 passed, 86 subtests passed** (baseline 128 at cycle
  start).
- New suites: `test_arch_eng_133_legacy_tools_secrets.py` (19),
  `test_arch_eng_134_workshop_read_secrets.py` (18),
  `test_arch_eng_135_redact_secrets_patterns.py` (25),
  `test_arch_eng_136_wallet_label_redaction.py` (23).
- Every suite carries a **behaviour-targeted negative control** — unwire the
  guard and prove the leak returns, then restore it. ARCH-ENG-136 additionally
  pins the *rule ordering*, which is load-bearing and was the original bug.
- No existing test was changed. Nothing asserted the old leaky behaviour.
- **Fresh-clone gate** (`git clone` + full suite): the first run **failed 2
  ARCH-ENG-133 tests** that the working tree passed, because both depended on
  the gitignored real `.env` existing. Fixed in commit 2664e00 by making both
  classes own their fixture (setUp writes a marker `.env` only when absent,
  tearDown removes only what the test created). Re-run: **208 passed, 5 skipped,
  86 subtests** in `tests/safety`, clean. The operator's real `.env` verified
  unchanged (15,027 bytes, 280 keys).

**This is why the fresh-clone gate exists and why it is never skipped.** The
working tree passed while the clone failed; the two contexts differ by exactly
the gitignored files, and a security test that silently depends on the presence
of the very secret store it is guarding is not testing the shipped system. The
fix also removed a real hazard: those tests previously `read_bytes()`'d and
compared the operator's live `.env`.

### Clone-context failures that are NOT this cycle's

The clone shows `9 errors` in `tests/tools/test_github_publish_sync.py` and some
`tests/engineering/test_arch_eng_113_env_fallback_bypass.py` failures.
**Reproduced identically on the pre-cycle parent commit `4ec6b46`** by cloning it
and running the same suite, so they are pre-existing clone-context issues, not
regressions from this work. The parent clone shows *more* failures than the
post-fix clone. Root cause (not fixed here, carried forward): these tests assume
operator-local state — a `.env`, a configured publish mirror, or both — that a
fresh clone does not have.

## Carried forward (open, from the same audit)

- **HIGH — `web_read`/`web_check` have no SSRF guard.** Model-supplied URL is
  fetched with no address validation; executed against a loopback server, an
  internal token was returned into model context, and `web_check` reported
  "Online (200)". `InstructionGate._is_safe_fetch_url` already exists and
  correctly blocks loopback/private/link-local — it is simply not applied on
  this path. Redirects are also followed without re-validation.
  (`agents/safety/handlers.py:105`, `agents/integrations/web_eyes.py:220,332`)
- **HIGH — `WorkerFilesystemMixin.research_all` blocklist misses realistic
  credential filenames.** Only the exact names `credentials.json`/`config.yaml`/
  `.env` are blocked; `credentials.yml`, `secrets.yaml`, `service-account.json`,
  `api_keys.yml`, `tokens.json`, `id_ed25519` all pass, and the text flows into
  the shared-context research snapshot and back into the prompt. Reproduced with
  a real PEM private key. (`agents/safety/filesystem.py:152,172`,
  `agents/brains/worker_safety.py:11`)
- **HIGH — `chat_router.build_runtime_context` inlines `.yaml`/`.yml`/`.json`
  file text into the prompt unredacted.** `.env` and `*.key` are correctly
  excluded by the dotfile/extension skip, but `credentials.yaml` is not.
  (`agents/dialogue/chat_router.py:183-213`)
- **MEDIUM — approval items persist raw model-supplied `arguments` to plaintext
  `~/.mrbot1000/approvals.json`** and the GUI renders them verbatim. A secret
  typed by the operator and echoed into a `file_write` proposal is written to
  disk. Not reachable via `file_read` (path is outside the workspace). Fix must
  redact for *display* only — `assert_approval_covers` must keep comparing the
  unredacted in-memory arguments, or the scope binding weakens.
  (`agents/safety/dispatch.py:77`, `agents/dialogue/chat_completion.py:376,491`,
  `agents/brains/big_brain.py:269`, `gui/panels/approval_panel.py:203`)
- **MEDIUM — clone-context test failures** in
  `tests/tools/test_github_publish_sync.py` (9 errors) and
  `tests/engineering/test_arch_eng_113_env_fallback_bypass.py`. Reproduced
  identically on the pre-cycle parent commit, so pre-existing, not a regression.
  They assume operator-local state a fresh clone lacks. Same class of problem
  the ARCH-ENG-133 hermeticity fix just addressed — worth the same treatment.
- **LOW — `run_command` output is not scanned** (see ARCH-ENG-133 known limit).
- **LOW — `RealCryptoOperator.confirm_and_send` takes `private_key` as a plain
  argument.** Unreachable in the wired path; carried since ARCH-ENG-132.
- **MEDIUM → INFORMATIONAL — `.env` is in git history** (~10 commits). Verified
  previously: zero real-length credential values were ever committed, so no
  rotation is required on current evidence.

## Not defects (verified sound, no change made)

- `query_db` exposes no credential-bearing columns — all 7 stores enumerated,
  every value swept for secret shapes; zero hits.
- The instruction-provenance gate fails closed and has a single human-only
  allowlist writer; a model-supplied URL cannot make itself trusted.
- No integration client logs a request/response body, header, or API key.
- `event_logger` writes no tool arguments or credentials.
