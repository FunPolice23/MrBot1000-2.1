"""Platform credential vault (Phase B).

Stores per-platform login secrets (email, username, password) ENCRYPTED AT REST,
never in `.env`, never in logs, never in chat. Reuses the proven Fernet
primitives from `wallet_crypto` (AES-128-CBC + HMAC, authenticated) with the
same key handling: `PLATFORM_VAULT_KEY` env var (operator-managed, preferred),
else a `platform_vault.key` file (0o600 + Windows owner-only ACL).

Design rules (the operator's explicit requirement — credentials are vulnerable):
- **Encrypted at rest, always.** A missing/malformed key RAISES; it never falls
  back to cleartext (the wallet_crypto B1 lesson).
- **Never logged, never printed, never returned to a model.** `get()` returns the
  secret only to an in-process caller that then feeds it straight to a browser
  form; there is no API that serializes a vault entry to text/JSON.
- **Scoped per platform.** Each platform's credentials are a separate record;
  listing platforms never exposes values.
- **The registration service consumes this** so the human enters a password once
  (into the vault, via a masked GUI field) and the agent never sees it in chat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from agents.integrations import wallet_crypto

# Separate key + store from the wallet so a platform credential compromise does
# not touch wallet keys and vice-versa.
_VAULT_KEY_ENV = "PLATFORM_VAULT_KEY"
_VAULT_KEY_FILE = "platform_vault.key"
_VAULT_STORE_FILE = "platform_vault.json"


def _default_dir() -> Path:
    # Same convention as the wallet store: a local, gitignored data dir.
    base = os.getenv("MRBOT_DATA_DIR", "").strip()
    root = Path(base) if base else Path(__file__).resolve().parents[2] / "data"
    return root


class CredentialVault:
    """Encrypted-at-rest store for per-platform login secrets."""

    def __init__(self, directory: "str | Path | None" = None):
        self._dir = Path(directory) if directory else _default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self._dir / _VAULT_KEY_FILE
        self._store_path = self._dir / _VAULT_STORE_FILE
        self._key = self._load_key()

    # ── key ────────────────────────────────────────────────────────────────
    def _load_key(self) -> str:
        env_key = os.getenv(_VAULT_KEY_ENV, "").strip()
        if env_key:
            # Validate; a malformed key raises rather than silently degrading to
            # cleartext storage.
            return wallet_crypto._validate_key(env_key)
        return wallet_crypto.load_or_create_key(self._key_path)

    # ── store I/O (values encrypted) ─────────────────────────────────────────
    def _read_store(self) -> Dict[str, Dict[str, str]]:
        if not self._store_path.exists():
            return {}
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _write_store(self, store: Dict[str, Dict[str, str]]) -> None:
        self._store_path.write_text(
            json.dumps(store, indent=2), encoding="utf-8")
        self._restrict_file(self._store_path)

    @staticmethod
    def _restrict_file(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if os.name == "nt":
            try:
                import subprocess
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r",
                     f"{os.environ.get('USERNAME', '*')}:F"],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass

    # ── public API ───────────────────────────────────────────────────────────
    def set(self, platform: str, field: str, secret: str) -> None:
        """Store one encrypted secret for a platform field. Empty secret is a
        no-op (never stores blanks)."""
        if not platform or not field or not secret or not secret.strip():
            return
        store = self._read_store()
        entry = store.setdefault(platform.lower(), {})
        entry[field] = wallet_crypto.encrypt_str(self._key, secret)
        self._write_store(store)

    def set_many(self, platform: str, secrets: Dict[str, str]) -> None:
        """Store several fields at once (e.g. email + password)."""
        if not platform or not secrets:
            return
        store = self._read_store()
        entry = store.setdefault(platform.lower(), {})
        for field, secret in secrets.items():
            if secret and secret.strip():
                entry[field] = wallet_crypto.encrypt_str(self._key, secret)
        self._write_store(store)

    def get(self, platform: str, field: str) -> str:
        """Return the DECRYPTED secret for in-process use only.

        The caller must feed it straight to a form and must NOT log, print,
        serialize, or send it to a model. Returns "" when absent.
        """
        store = self._read_store()
        token = store.get(platform.lower(), {}).get(field, "")
        if not token:
            return ""
        return wallet_crypto.decrypt_str(self._key, token)

    def get_all(self, platform: str) -> Dict[str, str]:
        """Return all DECRYPTED secrets for a platform (in-process use only)."""
        store = self._read_store()
        enc = store.get(platform.lower(), {})
        return {f: wallet_crypto.decrypt_str(self._key, t)
                for f, t in enc.items()}

    def has_platform(self, platform: str) -> bool:
        return bool(self._read_store().get(platform.lower()))

    def list_platforms(self) -> List[str]:
        """Platform names only — NEVER any secret value."""
        return sorted(self._read_store().keys())

    def fields_for(self, platform: str) -> List[str]:
        """Field names stored for a platform — names only, no values."""
        return sorted(self._read_store().get(platform.lower(), {}).keys())

    def delete(self, platform: str, field: Optional[str] = None) -> None:
        store = self._read_store()
        if field is None:
            store.pop(platform.lower(), None)
        else:
            store.get(platform.lower(), {}).pop(field, None)
            if not store.get(platform.lower()):
                store.pop(platform.lower(), None)
        self._write_store(store)
