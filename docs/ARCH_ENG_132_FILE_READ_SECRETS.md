# ARCH-ENG-132 — `file_read` returned the credential stores to the model

**Status:** FIXED and verified (v2.1.98, commit 0c261f7)
**Severity:** HIGH
**Found:** v2.1.97 cycle open-findings audit (docs/ARCH_ENG_129_APPROVAL_SCOPE.md)
**Fixed:** v2.1.98 engineering cycle

## The defect

`file_read` is classified READONLY by the gate and auto-allowed, and
`resolve_project_path` (`agents/safety/policy.py`) confines reads to
`PROJECT_ROOT` — which **contains the secret stores**. The credential vault's
own contract (`agents/platforms/credential_vault.py`: "never in `.env`, never
in logs, never in chat … metadata never exposes values") was defeated by a
tool that never touches the vault.

## Evidence — reproduced by EXECUTION, not inference

Pre-fix, via the real handler:

```
execute_tool('file_read', {'path':'.env'})                     -> 13,418 chars, 264 credential lines
execute_tool('file_read', {'path':'wallet.key'})               -> the raw Fernet wallet encryption key
execute_tool('file_read', {'path':'data/platform_vault.json'})  -> the encrypted platform vault
execute_tool('file_read', {'path':'data/platform_vault.key'})  -> the vault's own key
```

All four reachable by a plain model tool call with zero approval, feeding
straight into model context (and from there into any downstream LLM prompt).

## Fix — two layers in `agents/safety/handlers.py`

1. **Secret files refused outright** (`_is_secret_file`): the value *is* the
   whole file, so redaction is meaningless. Blocks `.env` at any directory
   depth (but NOT `.env.example`/`.template`/`.sample`, which hold
   placeholders the agent needs to discover key names), `*.key`, `*.pem`,
   `*.p12`, `*.pfx`, `*.keystore`, `wallet.key`, `platform_vault.key`,
   `platform_vault.json`, `wallets.json`, `credentials.json`, `secrets.json`,
   `.netrc`, `.npmrc`.
2. **Content redaction** — every other file passes through the existing
   `redact_secrets` (`agents/integrations/wallet_crypto.py`), so a credential
   pasted into a readable README/notes file is scrubbed before it returns.

`redact_secrets` also matches 64-hex strings (git SHAs / content hashes) — a
deliberate fail-safe: a false redaction costs the model a hash; a false pass
costs the operator a credential. Short hashes are unaffected.

## Verification

- `tests/safety/test_arch_eng_132_file_read_secrets.py` — 30 tests, incl. a
  **behavior-targeted negative control**: monkeypatching `_is_secret_file` to
  always-False re-leaks `.env` (proving the guard is what stops it), and
  restoring it re-refuses.
- Fresh-clone gate (`git clone` + `pytest tests/safety`): **124 passed, 4
  skipped**.
- Full suite (working tree, global Python 3.14): **1921 passed, 5 skipped**.
- 5 pre-existing clone-context failures in tests/engineering + tests/runtime
  reproduce identically on parent commit 4ec6b46 — not caused by this change.

## Carried forward

- **MEDIUM → INFORMATIONAL — `.env` is in git history** (~10 commits).
  Verified this cycle: **zero real-length credential values were ever
  committed** — every historical `.env` had empty/placeholder values. No
  rotation or `git filter-repo` is required on the current evidence. `.env`
  is correctly gitignored and absent from the HEAD tree.
- **LOW — `RealCryptoOperator.confirm_and_send` takes `private_key` as a plain
  argument.** Unreachable in the wired path (`try_real_payment` hard-returns
  `{"ok": False}`; only `propose_payment` is called from the GUI); also
  `__init__(safety_guard=None)` makes `propose_payment` silently return
  `status: "simulated"`.
