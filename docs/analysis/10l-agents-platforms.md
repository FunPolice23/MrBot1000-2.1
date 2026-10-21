# 10l — `agents/platforms/`

3 scripts, 468 lines. The credential vault and the gated registration flow.

---

## Structure

| File | Lines | Role |
|---|---:|---|
| `__init__.py` | 41 | ARCH-ENG-205: eager adapter re-export removed |
| `credential_vault.py` | 154 | Fernet-encrypted per-platform credential store |
| `registration.py` | 273 | Five-step gated sign-up flow |

Both modules are genuinely live. `CredentialVault` has three production
consumers — `agents/earning/moltbook_agent.py:116/147`,
`agents/platforms/registration.py:237` and `agents/runtime/provider_keys.py:65`
— and `registration.py` is driven from `gui/panels/registration_panel.py`.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| K-01 | low | **The workshop keeps a parallel plaintext credential store.** `Workshop.add_account` (`workshop.py:560`) writes `{"password": password, ...}` to `accounts.json`, and `add_payment_method` (`:643`) writes payment identifiers to `payments.json`. Both are protected from the agent by ARCH-ENG-134 (see below), so this is **not** a vulnerability. It is a design observation: `CredentialVault` exists as the designated encrypted home for exactly this data and is used by three other subsystems, while the workshop maintains its own plaintext copy with no encryption, no key management and no vault integration. Worth an operator decision — migrating it would consolidate three credential homes into one — rather than a defect to fix. |
| K-02 | info | **`agents/platforms/__init__.py` documents a fix for the same class of finding.** It records that the module *"used to import all five platform adapters plus the registry at import time"* and that *"Every one of those eleven names had ZERO references anywhere outside this package. They were not dead by accident — they were unreachable."* ARCH-ENG-205 removed the eager re-export. Recorded because it is direct in-repo evidence that the dead-code class this sweep is finding has been recognised before — and that the previous fix addressed the *re-export*, not the adapter modules themselves, which are not in this package any more. |

---

## A near-miss worth recording

I nearly filed a **high-severity** finding on the workshop credential store, and
the reasoning was correct at every step until the last one:

1. `add_account` writes a plaintext `password` field. ✓
2. It goes to `accounts/accounts.json`. ✓
3. `handlers.py` has a secret-file blocklist (`_SECRET_FILE_NAMES`,
   ARCH-ENG-132) guarding `file_read`. ✓
4. That blocklist contains `.env`, `wallet.key`, `platform_vault.key`,
   `platform_vault.json`, `wallets.json`, `credentials.json`, `secrets.json`,
   `.netrc`, `.npmrc`, plus `.key`/`.pem`/`.pfx`/`.p12`/`.keystore`/`.env`
   suffixes — and **not** `accounts.json`. ✓

Stopped there, that is a plaintext platform-password file readable by the agent
through an auto-allowed read tool. It is already fixed. `handlers.py:548-568`
introduces a **second**, workshop-specific blocklist:

```
_WORKSHOP_SECRET_FILE_NAMES = frozenset({
    "accounts.json",           # add_account: plaintext `password` field
    "payments.json",           # add_payment_method: payment identifiers
    "payment_methods.json",
})
```

and `_is_workshop_secret_path` (`:571`) checks **every path segment** and then
delegates to `_is_secret_file` for everything else, so there is one authority
with a workshop-specific extension rather than two blocklists that could drift.

The lesson generalises past this area: **a blocklist audit must enumerate every
blocklist in the codebase, not just the first one found.** I had found a real
gap in blocklist A and assumed it was a gap in the system's coverage. It was a
gap in blocklist A only, and blocklist B existed precisely because someone had
already made this exact mistake.

---

## Verified as sound — the strongest security work in the project

**ARCH-ENG-132 (`handlers.py:499-514`) documents a breach it reproduced by
execution, not by inspection.** The docstring gives the pre-fix evidence
verbatim: `file_read('.env')` → *"13,418 chars, 264 credential lines"*;
`file_read('wallet.key')` → *"the raw Fernet wallet key"*;
`file_read('data/platform_vault.json')` → *"encrypted vault blobs"*. Then the
observation that matters:

> *"The credential vault's own contract ('metadata never exposes values, the
> model never sees a password') was defeated by a tool that never touches the
> vault."*

That is the correct diagnosis — a strong guarantee inside the vault, bypassed by
a tool outside it. The fix is two-layered: secret files refused outright, and
every other file's content passed through `redact_secrets`. It also documents a
**deliberate** false-positive trade-off: `redact_secrets` matches 64-hex strings,
so git SHAs and content hashes are redacted too — *"a false redaction costs the
model a hash; a false pass costs the operator a credential."* Naming the cost of
being wrong in both directions is what makes a security trade-off reviewable.

**ARCH-ENG-134 (`:548-563`) repeats that discipline.** Same by-execution
evidence (`workshop_read '.env'` → the raw `OPENAI_API_KEY` line;
`workshop_read 'wallet.key'` → raw Fernet key material; `workshop_read 'notes.md'`
→ an unredacted `sk-proj-` key pasted in prose), and — unusually — it explains
**why it did not merge into `_SECRET_FILE_NAMES`**:

> *"Kept as its OWN small frozenset … so the two blocklists stay independently
> reviewable: these names are only credential-bearing INSIDE the workshop's own
> schema … and adding the names there would widen `file_read` for no reason.
> `proposals.json` is deliberately NOT listed — it holds proposal titles/clients,
> not credentials."*

A security patch that documents both what it blocks **and** what it
deliberately does not block, with reasons, is close to the ideal form for this
kind of change.

**`CredentialVault` fails closed on key problems.** Its docstring states the
contract — *"Encrypted at rest, always. A missing/malformed key RAISES; it never
falls back to cleartext"* — with `PLATFORM_VAULT_KEY` preferred and a
`platform_vault.key` file at `0o600` plus Windows owner-only ACL as the fallback.
Reusing `wallet_crypto`'s Fernet primitives rather than inventing new crypto is
the right call.

**`register_with_vault` cannot be driven without a recorded approval.** It
requires `approval_id`, then `queue.find_by_id(approval_id)`, then checks
`item.status != ApprovalStatus.APPROVED`, failing closed with
*"a recorded, APPROVED create_account approval is required"*. It then fails closed
again if the vault has no entry (`"the human must enter them first"`) and again
if any requested field is missing — three independent fail-closed checks before a
single secret is read.

---

## Assessment

This is the smallest area analysed so far and it contains the highest-quality
security engineering in the repository. Three separate ARCH-ENG remediations
(132, 134, 066) appear here or in code this area depends on, and all three share
a method: reproduce the breach by execution, write the exact evidence into the
docstring, fix in layers, and document the deliberate trade-offs in both
directions.

K-01 is the one open item and it is not urgent — the data is protected, so the
question is only whether plaintext workshop credentials should migrate to the
vault that already exists for that purpose. That is an operator decision about
credential consolidation, not a defect.

The near-miss is the more valuable output. It is the second time this sweep has
been stopped by an in-repo comment explaining a fix that a code reading missed —
the first was ARCH-ENG-156's DB isolation. Both times the evidence had been
written down carefully by someone who had already done the work.