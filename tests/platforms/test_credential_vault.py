"""Credential vault (Phase B) — encrypted-at-rest, never leaks cleartext.

The operator's hard requirement: passwords/login info are vulnerable and must
never be able to leak. These tests prove the store file contains only encrypted
tokens, that listing/metadata APIs never expose values, and that a malformed key
raises rather than silently degrading to cleartext.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")


def _vault():
    from agents.platforms.credential_vault import CredentialVault
    return CredentialVault(directory=tempfile.mkdtemp())


class TestVaultEncryption(unittest.TestCase):
    def test_roundtrip_and_no_cleartext_at_rest(self):
        v = _vault()
        v.set_many("ugig", {"email": "a@b.com", "password": "s3cret-pw"})
        self.assertEqual(v.get("ugig", "email"), "a@b.com")
        self.assertEqual(v.get("ugig", "password"), "s3cret-pw")
        # The store file must NOT contain the cleartext secret.
        raw = open(v._store_path, encoding="utf-8").read()
        self.assertNotIn("s3cret-pw", raw)
        self.assertNotIn("a@b.com", raw)
        self.assertIn("fernet:", raw)   # encrypted token marker

    def test_metadata_apis_never_expose_values(self):
        v = _vault()
        v.set("prolific", "password", "topsecret")
        self.assertEqual(v.list_platforms(), ["prolific"])       # names only
        self.assertEqual(v.fields_for("prolific"), ["password"])  # field names only
        # No public API serializes a value to text.
        self.assertNotIn("topsecret", json.dumps(v.list_platforms()))
        self.assertNotIn("topsecret", json.dumps(v.fields_for("prolific")))

    def test_empty_secret_not_stored(self):
        v = _vault()
        v.set("x", "password", "   ")
        self.assertFalse(v.has_platform("x"))

    def test_delete_field_and_platform(self):
        v = _vault()
        v.set_many("moltbook", {"email": "e@x.com", "password": "p"})
        v.delete("moltbook", "password")
        self.assertEqual(v.fields_for("moltbook"), ["email"])
        v.delete("moltbook")
        self.assertFalse(v.has_platform("moltbook"))

    def test_missing_returns_empty(self):
        v = _vault()
        self.assertEqual(v.get("nope", "password"), "")
        self.assertFalse(v.has_platform("nope"))


class TestVaultKeySafety(unittest.TestCase):
    def test_malformed_env_key_raises_not_cleartext(self):
        """A malformed PLATFORM_VAULT_KEY must RAISE, never fall back to
        cleartext storage (the wallet_crypto B1 lesson)."""
        os.environ["PLATFORM_VAULT_KEY"] = "not-a-valid-fernet-key"
        try:
            from agents.platforms.credential_vault import CredentialVault
            with self.assertRaises(Exception):
                CredentialVault(directory=tempfile.mkdtemp())
        finally:
            os.environ.pop("PLATFORM_VAULT_KEY", None)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
