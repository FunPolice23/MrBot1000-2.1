"""ARCH-ENG-135: redact_secrets must match the credentials this deployment stores.

Pre-fix, `redact_secrets` only covered wallet key material (64-hex, base58, WIF,
fernet, mnemonic markers). Every API credential shape in the live .env --
OPENAI_API_KEY, ANTHROPIC_API_KEY, UPWORK_CLIENT_SECRET/REFRESH_TOKEN, GitHub
tokens, AWS keys, Slack tokens, bearer headers, PEM private keys -- passed
through UNREDACTED into the model's tool-result context (layer 2 of the
v2.1.98 model-context boundary, applied by handlers._tool_file_read and
legacy_tools._redact).

Pre-fix repro (all False -- nothing matched):

    python -c "from agents.integrations.wallet_crypto import redact_secrets as r; \
    cases={'openai':'OPENAI_API_KEY=sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGGHHHH', ...}; \
    [print(n, '[REDACTED]' in r(s)) for n,s in cases.items()]"

Design rules asserted here:
  * value-shaped secrets are replaced wholesale;
  * label-shaped secrets keep the LABEL and separator, replace only the VALUE,
    so the model still learns WHICH key is missing;
  * one marker only: [REDACTED-SECRET] (no second style);
  * idempotence: redact_secrets(redact_secrets(x)) == redact_secrets(x);
  * the deliberate 64-hex fail-safe (git SHAs / content hashes are redacted)
    is documented as a known, accepted over-match -- it is pre-existing
    behaviour, not something this change introduces.
"""
import unittest

from agents.integrations.wallet_crypto import (
    _REDACTED,
    contains_secret,
    redact_secrets,
)


class ValueShapedSecretsAreRedacted(unittest.TestCase):
    """Each credential format the deployment stores IS redacted."""

    def test_openai_style_key(self):
        out = redact_secrets("OPENAI_API_KEY=sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGGHHHH")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGGHHHH", out)
        # label survives
        self.assertTrue(out.startswith("OPENAI_API_KEY="), out)

    def test_anthropic_style_key(self):
        out = redact_secrets(
            "ANTHROPIC_API_KEY=sk-ant-api03-AAAAbbbbCCCCddddEEEEFFFFGGGGHHHH")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("sk-ant-api03-AAAAbbbb", out)

    def test_github_personal_access_token(self):
        out = redact_secrets("token: ghp_HHHHiiiijjjjKKKKllllmmmmnnnn")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("ghp_HHHHiiiijjjjKKKKllllmmmmnnnn", out)

    def test_github_oauth_token(self):
        out = redact_secrets("GITHUB_TOKEN=gho_16C7e42F292c6912E7710c838347Ae178B4a")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("gho_16C7e42F292c6912E7710c838347Ae178B4a", out)

    def test_aws_access_key_id(self):
        out = redact_secrets("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)

    def test_slack_bot_token(self):
        out = redact_secrets("SLACK=xoxb-123456789012-ABCDEFGHIJKL")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("xoxb-123456789012-ABCDEFGHIJKL", out)

    def test_pem_private_key_block_is_redacted_whole(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA7xQ9fakebase64bodyZZZZ\n"
            "moreBase64BodyContentHereAAAAAAAAAAAA\n"
            "-----END RSA PRIVATE KEY-----"
        )
        out = redact_secrets(pem)
        self.assertIn(_REDACTED, out)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", out)
        self.assertNotIn("END RSA PRIVATE KEY", out)
        self.assertNotIn("fakebase64bodyZZZZ", out)
        self.assertEqual(out, _REDACTED)


class LabelShapedSecretsKeepTheLabel(unittest.TestCase):
    """Only the VALUE is replaced; the label tells the model WHICH key."""

    def test_password_label_survives(self):
        out = redact_secrets("password: P@ssw0rd-abcdef")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("P@ssw0rd-abcdef", out)
        self.assertTrue(out.startswith("password: "), out)

    def test_env_style_api_key_label_survives(self):
        out = redact_secrets("OPENAI_API_KEY=sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGGHHHH")
        self.assertTrue(out.startswith("OPENAI_API_KEY="), out)
        self.assertEqual(out, "OPENAI_API_KEY=" + _REDACTED)

    def test_prefixed_env_labels_are_matched(self):
        """UPWORK_CLIENT_SECRET / NOUS_REFRESH_TOKEN must match too."""
        for line in (
            "UPWORK_CLIENT_SECRET=8f3a9c2e1b7d4f6a",
            "UPWORK_REFRESH_TOKEN=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payloaddata",
            "NOUS_ACCESS_TOKEN=eyJhbGciOiJIUzI1NiJ9.third.part",
        ):
            out = redact_secrets(line)
            name = line.split("=", 1)[0]
            self.assertTrue(out.startswith(name + "="), f"{line!r} -> {out!r}")
            self.assertIn(_REDACTED, out)
            self.assertNotIn(line.split("=", 1)[1], out)

    def test_labelled_value_inside_json_is_redacted(self):
        out = redact_secrets('{"api_key": "AKIAIOSFODNN7EXAMPLE", "note": "keep"}')
        self.assertIn(_REDACTED, out)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)
        self.assertIn('"api_key"', out)  # label survives

    def test_bearer_token_keeps_the_authorization_label(self):
        out = redact_secrets(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        self.assertIn(_REDACTED, out)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9.payload.sig", out)
        self.assertTrue(out.startswith("Authorization: Bearer "), out)

    def test_short_labelled_values_are_not_redacted(self):
        """`pwd=abc` is below the 6-char floor -- not credential-shaped."""
        out = redact_secrets("pwd=abc")
        self.assertEqual(out, "pwd=abc")


class FalsePositiveGuards(unittest.TestCase):
    """Ordinary model-readable content must come back unchanged."""

    PROSE = (
        "The quick brown fox jumps over the lazy dog. This paragraph mentions "
        "nothing sensitive at all, just ordinary English prose about the "
        "weather, the weekend plans and a walk in the park."
    )
    WINDOWS_PATH = (
        "Open the file at C:\\Users\\cecil\\Documents\\password-reset\\notes.md "
        "to read the setup instructions."
    )

    def test_ordinary_prose_unchanged(self):
        self.assertEqual(redact_secrets(self.PROSE), self.PROSE)
        self.assertFalse(contains_secret(self.PROSE))

    def test_windows_path_with_password_word_unchanged(self):
        self.assertEqual(redact_secrets(self.WINDOWS_PATH), self.WINDOWS_PATH)
        self.assertFalse(contains_secret(self.WINDOWS_PATH))

    def test_requirements_version_string_unchanged(self):
        self.assertEqual(redact_secrets("PySide6>=6.5.0"), "PySide6>=6.5.0")

    def test_markdown_link_unchanged(self):
        link = "See the [architecture notes](https://example.com/docs/arch-eng-135)."
        self.assertEqual(redact_secrets(link), link)

    def test_empty_string_returns_empty(self):
        self.assertEqual(redact_secrets(""), "")
        self.assertFalse(contains_secret(""))

    def test_non_ascii_text_unchanged(self):
        text = "héllo wörld — naïve café ☕ 日本語のテキスト"
        self.assertEqual(redact_secrets(text), text)

    def test_short_hashes_are_not_secret_shaped(self):
        """Pre-existing behaviour: only 64-hex is matched, short hashes pass."""
        self.assertIn("3f8a2b1c", redact_secrets("hash 3f8a2b1c here"))

    def test_git_sha_is_a_documented_deliberate_failsafe(self):
        """KNOWN ACCEPTED OVER-MATCH (pre-existing, ARCH-ENG-132/133): the
        64-hex rule redacts git SHAs and content hashes too. This is a
        deliberate fail-safe -- losing a SHA costs far less than leaking a key.
        It is asserted here so the behaviour stays documented, not accidental.
        """
        sha = "8f14e45fceea167a5a36dedd4bea2543e3f2a1b6b1c0d2e3f4a5b6c7d8e9f0a1"
        out = redact_secrets("commit " + sha)
        self.assertIn(_REDACTED, out)
        self.assertNotIn(sha, out)


class Idempotence(unittest.TestCase):
    """Redacting already-redacted text must be a no-op."""

    CASES = [
        "OPENAI_API_KEY=sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGGHHHH",
        "token: ghp_HHHHiiiijjjjKKKKllllmmmmnnnn",
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        "SLACK=xoxb-123456789012-ABCDEFGHIJKL",
        "password: P@ssw0rd-abcdef",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "-----BEGIN RSA PRIVATE KEY-----\nfakebody\n-----END RSA PRIVATE KEY-----",
        "mnemonic: abandon abandon art",
        "key: " + "a" * 64,
        "plain prose with no secrets at all",
    ]

    def test_double_redaction_is_stable(self):
        for case in self.CASES:
            once = redact_secrets(case)
            twice = redact_secrets(once)
            self.assertEqual(once, twice, f"not idempotent: {case!r}")

    def test_marker_itself_is_not_re_matched(self):
        self.assertEqual(redact_secrets(_REDACTED), _REDACTED)


class ContainsSecretAgreesWithRedaction(unittest.TestCase):
    """contains_secret must agree with redact_secrets on the new shapes."""

    def test_detects_every_redactable_shape(self):
        for case in Idempotence.CASES:
            if case == "plain prose with no secrets at all":
                continue
            self.assertTrue(contains_secret(case), f"missed: {case!r}")

    def test_rejects_clean_text(self):
        self.assertFalse(contains_secret("PySide6>=6.5.0"))
        self.assertFalse(contains_secret(""))


if __name__ == "__main__":
    unittest.main()
