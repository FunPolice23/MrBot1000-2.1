"""agents/wallet_crypto.py — Encrypt wallet secrets at rest (B1).

Implements Section B's #1 security debt: private keys must not sit in cleartext in
`wallets.json`. Uses `cryptography.Fernet` (AES-128-CBC + HMAC, authenticated) with a
32-byte key sourced from the `WALLET_ENC_KEY` env var, or auto-generated into a
`wallet.key` file (mode 0o600) when absent.

The key file is itself sensitive: 0o600 + never committed. If it's lost, the encrypted
keys are unrecoverable — that is the intended property of encryption-at-rest.
"""

import os
import re
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
    _HAS_CRYPTO = True
except Exception:  # pragma: no cover - cryptography is a hard dep in this env
    Fernet = None
    _HAS_CRYPTO = False

_FERNET_PREFIX = "fernet:"


def _require_fernet():
    if not _HAS_CRYPTO or Fernet is None:
        raise RuntimeError("cryptography is required for wallet encryption (B1)")
    return Fernet


def generate_key() -> str:
    """Return a new Fernet key (urlsafe-base64 32-byte) as a string."""
    return _require_fernet().generate_key().decode("utf-8")


def _validate_key(key: str) -> str:
    """Validate `key` is a usable Fernet key; raise otherwise.

    A malformed key must not be silently accepted — that path previously led to the
    secret being stored in cleartext (defeats B1). Callers treat a raise as "encryption
    unavailable" and MUST NOT fall back to plaintext.
    """
    if not key or not key.strip():
        raise ValueError("empty WALLET_ENC_KEY")
    try:
        _require_fernet()(key.strip())
    except Exception as e:
        raise ValueError(f"WALLET_ENC_KEY is not a valid Fernet key: {e}")
    return key.strip()


def load_or_create_key(key_path: "str | Path") -> str:
    """Load the Fernet key from `key_path`, or generate + persist it (mode 0o600).

    Falls back to the `WALLET_ENC_KEY` env var if set (operator-managed, preferred).
    The env key is validated; a malformed value raises rather than falling back to
    cleartext storage.
    """
    env_key = os.getenv("WALLET_ENC_KEY", "").strip()
    if env_key:
        return _validate_key(env_key)

    p = Path(key_path)
    if p.exists():
        raw = p.read_text().strip()
        if raw:
            # Validate existing key file too (in case it was hand-edited).
            return _validate_key(raw)

    key = generate_key()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass  # best-effort on POSIX
    # On Windows, mode bits are ignored — restrict the file to the current user via ACLs
    # so other local accounts / processes can't read the key (H36). Best-effort; icacls
    # is present on every modern Windows. We grant only the owner Full and strip inherited
    # and group/other access.
    if os.name == "nt":
        try:
            import subprocess
            subprocess.run(
                ["icacls", str(p), "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', '*')}:F"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            pass
    return key


def is_encrypted(value: str) -> bool:
    """True if `value` looks like one of our Fernet tokens (not cleartext)."""
    if not value:
        return False
    return value.startswith(_FERNET_PREFIX) and len(value) > len(_FERNET_PREFIX)


def encrypt_str(key: str, plaintext: str) -> str:
    """Encrypt a secret string → a stored token. Empty/whitespace stays empty."""
    if not plaintext or not plaintext.strip():
        return ""
    f = _require_fernet()(key)
    token = f.encrypt(plaintext.encode("utf-8"))
    return _FERNET_PREFIX + token.decode("utf-8")


def decrypt_str(key: str, token: str) -> str:
    """Decrypt a stored token → secret. Non-encrypted input is returned as-is
    (backward compatible with legacy cleartext files). Empty → "".
    """
    if not token:
        return ""
    if not is_encrypted(token):
        return token  # legacy cleartext — transparent passthrough
    f = _require_fernet()(key)
    raw = token[len(_FERNET_PREFIX):] if token.startswith(_FERNET_PREFIX) else token
    return f.decrypt(raw.encode("utf-8")).decode("utf-8")


def encrypt_if_needed(key: str, value: str) -> str:
    """Encrypt `value` only if it's non-empty AND not already encrypted."""
    if not value or is_encrypted(value):
        return value
    return encrypt_str(key, value)


def decrypt_if_needed(key: str, value: str) -> str:
    """Decrypt `value` if it's an encrypted token, else return it unchanged."""
    if not is_encrypted(value):
        return value
    return decrypt_str(key, value)


# --- B2: secret isolation for LLM context ---
# A private key (or any high-entropy secret) must NEVER be placed into an LLM prompt.
# `redact_secrets` scrubs known secret shapes before any text is sent to a model;
# `contains_secret` lets callers assert/block before prompt assembly.
#
# ARCH-ENG-135: the original pattern set only covered wallet key material, so the
# API credentials this deployment ACTUALLY stores (OPENAI_API_KEY, ANTHROPIC_API_KEY,
# UPWORK_CLIENT_SECRET, GitHub tokens, AWS keys, Slack tokens, bearer headers and
# PEM private keys) passed through unredacted. Two families are added:
#   * value-shaped patterns -- the whole match IS the secret (sk-..., ghp_...);
#   * label-shaped patterns -- only the VALUE after a credential label is redacted,
#     the label itself survives, so the model still learns WHICH key is missing.
# Both use the single marker [REDACTED-SECRET]; do not invent a second style.
_REDACTED = "[REDACTED-SECRET]"

# --- value-shaped: the entire match is a secret ---
_SECRET_PATTERNS = [
    # PEM private key blocks (RSA / EC / DSA / OPENSSH / PGP / ENCRYPTED): the
    # WHOLE block is redacted, header through footer. Runs first so the base64
    # body is never scanned line-by-line by the rules below.
    re.compile(
        r"-----BEGIN ((?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY)"
        r"-----.*?-----END \1-----",
        re.DOTALL,
    ),
    # Bech32-ish / 64-hex private keys (eth/solana raw keys). Known fail-safe:
    # this also matches git SHAs and content hashes -- deliberate, see the
    # ARCH-ENG-135 false-positive guards in tests/safety.
    re.compile(r"\b[0-9a-fA-F]{64}\b"),
    # base58 solana private keys (ed25519, ~88 chars) or 52-char
    re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{88}\b"),
    # WIF / 5-prefixed bitcoin-like
    re.compile(r"\b[5KL][1-9A-HJ-NP-Za-km-z]{50,52}\b"),
    # fernet tokens (our own encrypted form)
    re.compile(r"\bfernet:[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]*\b"),
    # key material markers
    re.compile(r"(?i)(wallet\.key|WALLET_ENC_KEY|private[_-]?key|mnemonic|seed[_-]?phrase)\b"),
    # OpenAI-style API keys (covers sk-proj-, sk-ant-, sk-or-, ...)
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    # GitHub personal access / OAuth / user-to-server / refresh tokens
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    # AWS access key id
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Slack bot / user / app / legacy tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
]

# --- label-shaped: redact the VALUE, keep the LABEL ---
# `(?<![A-Za-z0-9])` rather than `\b` before the label so a prefixed env name
# still matches (UPWORK_CLIENT_SECRET, NOUS_REFRESH_TOKEN, ...) while an
# ordinary identifier like `xpassword=` does not. Group 1 = label, group 2 =
# separator, so `password: hunter2` -> `password: [REDACTED-SECRET]` and the
# model still learns WHICH key was in the file.
_BEARER_RE = re.compile(
    r"(?i)\b(authorization\s*:\s*bearer\s+)"
    r"[A-Za-z0-9._~+/-]{20,}=*"
)
_LABELLED_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])"
    r"(api[_-]?key|client[_-]?secret|client[_-]?id|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token|secret[_-]?key|"
    # ARCH-ENG-136: the wallet's own crown jewels must be in the LABELLED set,
    # not only in the bare-marker set below. Reproduced before this fix, via
    # redact_secrets: `mnemonic: abandon ability able about above absent` came
    # back as `[REDACTED-SECRET]: abandon ability able about above absent` --
    # the marker pattern matched the WORD `mnemonic` and replaced the label,
    # leaving the seed phrase itself fully readable. Same for seed_phrase,
    # private_key and WALLET_ENC_KEY. A seed phrase IS the wallet, so this was
    # the highest-value leak in the module.
    r"password|passwd|pwd|mnemonic|seed[_-]?phrase|"
    r"private[_-]?key|wallet[_-]?enc[_-]?key)"
    r"\b(\s*[:=]\s*)\S{6,}"
)

# ARCH-ENG-136: a BIP39 seed phrase is SPACE-SEPARATED WORDS, so a single-token
# rule cannot see it. Reproduced mid-fix with a labelled value only:
#   `mnemonic: abandon ...` -> `mnemonic: [REDACTED-SECRET] ability able ...`
# i.e. 11 of the 12 words still readable, which is the whole wallet.
#
# THE LABEL *AND* A `:`/`=` SEPARATOR ARE MANDATORY, deliberately. Two looser
# revisions of this rule were tried and REJECTED by execution:
#   1. matching a bare word list with no label matched ordinary English prose,
#      because "3+ lowercase words" is also the shape of a sentence;
#   2. allowing `is/are/was` as the separator matched
#      `The mnemonic is stored encrypted and never logged verbatim.` --
#      "stored encrypted and never logged verbatim" is a lowercase word run.
# `redact_secrets` is applied to every file the model reads, so over-redaction
# would gut the module's usefulness and push callers to bypass it entirely.
# Requiring `mnemonic`/`seed_phrase` followed by `:` or `=` holds the
# false-positive rate at zero while still catching how a phrase is written down.
#
# Residual risk, recorded honestly: a phrase with no label, or after `is`, is not
# caught. The bare-marker rule below still redacts the WORD `mnemonic`, the
# strongest signal available short of matching prose.
_SEED_PHRASE_RE = re.compile(
    r"(?i)((?<![A-Za-z0-9])(?:mnemonic|seed[_-]?phrase)\s*[:=]\s*)"
    r"([a-z]{3,}(?:[ \-]+[a-z]{3,}){2,})"
)

_LABELLED_SECRET_PATTERNS = [_BEARER_RE, _SEED_PHRASE_RE, _LABELLED_RE]

# One ordered rule list: (pattern, replacement). Label-shaped rules carry a
# backreference so the label survives; value-shaped rules replace the whole match.
#
# ORDER IS LOAD-BEARING (ARCH-ENG-136), and the three labelled rules have a
# required order among themselves too:
#   1. _SEED_PHRASE_RE  -- a seed phrase is a WORD LIST; it must match before
#      _LABELLED_RE, whose `\S{6,}` would otherwise consume the first word and
#      leave the remaining 11 readable.
#   2. _LABELLED_RE     -- redacts the value after a credential label.
#   3. then the value-shaped rules -- the bare-marker rule matches the WORD
#      `mnemonic`/`seed_phrase`/`private_key`, so if it ran first it would
#      replace the LABEL and leave the value readable (the original defect:
#      `mnemonic: abandon ...` -> `[REDACTED-SECRET]: abandon ...`).
# Do not reorder this list without re-running
# tests/safety/test_arch_eng_136_wallet_label_redaction.py.
_REDACT_RULES = [
    # group 1 = optional label+separator (kept), group 2 = the word list.
    (_BEARER_RE, r"\1" + _REDACTED),
    (_SEED_PHRASE_RE, r"\1" + _REDACTED),
    # group 1 = label, group 2 = separator -> `LABEL<sep> [REDACTED-SECRET]`
    (_LABELLED_RE, r"\1\2" + _REDACTED),
] + [(p, _REDACTED) for p in _SECRET_PATTERNS]


def contains_secret(text: str) -> bool:
    """True if `text` looks like it contains a secret (key/seed/token)."""
    if not text:
        return False
    return any(p.search(text) for p in _SECRET_PATTERNS + _LABELLED_SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    """Replace any detected secret in `text` with `[REDACTED-SECRET]`.

    Use this on ANY string before it enters an LLM prompt -- especially anything
    derived from `WalletManager.get_private_key()` or any credential a tool read
    off disk. Returns a redacted copy.

    Idempotent: redacting already-redacted text is a no-op, because the marker
    `[REDACTED-SECRET]` matches none of the patterns above.
    """
    if not text:
        return ""
    out = text
    for pattern, replacement in _REDACT_RULES:
        out = pattern.sub(replacement, out)
    return out
