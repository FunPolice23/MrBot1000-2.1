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
_SECRET_PATTERNS = [
    # Bech32-ish / 64-hex private keys (eth/solana raw keys)
    re.compile(r"\b[0-9a-fA-F]{64}\b"),
    # base58 solana private keys (ed25519, ~88 chars) or 52-char
    re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{88}\b"),
    # WIF / 5-prefixed bitcoin-like
    re.compile(r"\b[5KL][1-9A-HJ-NP-Za-km-z]{50,52}\b"),
    # fernet tokens (our own encrypted form)
    re.compile(r"\bfernet:[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]*\b"),
    # key material markers
    re.compile(r"(?i)(wallet\.key|WALLET_ENC_KEY|private[_-]?key|mnemonic|seed[_-]?phrase)\b"),
]


def contains_secret(text: str) -> bool:
    """True if `text` looks like it contains a secret (key/seed/token)."""
    if not text:
        return False
    return any(p.search(text) for p in _SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    """Replace any detected secret in `text` with `[REDACTED-SECRET]`.

    Use this on ANY string before it enters an LLM prompt — especially anything
    derived from `WalletManager.get_private_key()`. Returns a redacted copy.
    """
    if not text:
        return ""
    out = text
    for p in _SECRET_PATTERNS:
        out = p.sub("[REDACTED-SECRET]", out)
    return out
