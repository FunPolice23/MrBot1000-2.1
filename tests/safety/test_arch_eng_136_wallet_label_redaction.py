"""ARCH-ENG-136 — the wallet's own crown jewels survived `redact_secrets`.

Found by the Architect's independent adversarial review of the ARCH-ENG-135
pattern extension, not by the implementer's own tests. Four leaks, all the same
root cause: the module's pre-existing *bare-marker* rule matched the WORD
`mnemonic` / `seed_phrase` / `private_key` / `WALLET_ENC_KEY` and replaced the
LABEL, leaving the value beside it fully readable.

Reproduced pre-fix, via the real `redact_secrets`:

    in : mnemonic: abandon ability able about above absent
    out: [REDACTED-SECRET]: abandon ability able about above absent

A seed phrase IS the wallet, so this was the highest-value leak in the module —
and it was reachable through every consumer of `redact_secrets`
(`handlers._tool_file_read`, `legacy_tools._redact`,
`handlers._tool_workshop_read`).

The fix is two-part and ORDER IS LOAD-BEARING:

1. the wallet labels joined the *labelled* rule set, so the VALUE after the
   separator is what gets replaced;
2. the labelled rules now run BEFORE the value-shaped rules — otherwise the
   bare-marker rule replaces the label first and the labelled rule never sees
   the pair again (which is exactly how the bug arose).

Every test below asserts on substrings rather than on whole output strings, so
a change to the marker text cannot silently weaken them.
"""

import unittest

from agents.integrations.wallet_crypto import (
    contains_secret,
    redact_secrets,
)

# The module's single documented marker. Referenced by name so a future marker
# rename fails these tests loudly instead of silently passing.
REDACTED = "[REDACTED-SECRET]"


class TestWalletLabelLeaks(unittest.TestCase):
    """The four reproduced leaks: the VALUE must not survive."""

    def test_mnemonic_value_is_redacted(self):
        """A BIP39 seed phrase is the wallet; it must never be readable."""
        text = "mnemonic: abandon ability able about above absent absorb abstract"
        out = redact_secrets(text)
        self.assertNotIn("abandon ability able", out)
        self.assertIn(REDACTED, out)

    def test_seed_phrase_value_is_redacted(self):
        text = ("seed_phrase = gravity machine north sort system female filter "
                "attitude volume fold club stay")
        out = redact_secrets(text)
        self.assertNotIn("gravity machine north", out)
        self.assertIn(REDACTED, out)

    def test_private_key_value_is_redacted(self):
        text = "private_key: MIIBOgIBAAJBAKj34GWiHcLo"
        out = redact_secrets(text)
        self.assertNotIn("MIIBOgIBAAJBAKj34", out)

    def test_wallet_enc_key_value_is_redacted(self):
        text = ("WALLET_ENC_KEY=dE23Hpd6xTHPkcRs9UELcHXhZWui2"
                "_VZfdI7SaEKXMc=")
        out = redact_secrets(text)
        self.assertNotIn("dE23Hpd6xTHPkcRs9UEL", out)


class TestWholeSeedPhraseIsRedacted(unittest.TestCase):
    """A second leak found by the Architect while fixing the first.

    A BIP39 seed phrase is SPACE-SEPARATED WORDS. The labelled rule's
    ``\\S{6,}`` matches a single token, so it captured only the FIRST word. Reproduced
    mid-fix:

        in : mnemonic: abandon ability able about above absent
        out: mnemonic: [REDACTED-SECRET] ability able about above absent

    11 of the 12 words survived — which is the entire wallet. `_SEED_PHRASE_RE`
    now matches the whole word list and must run before `_LABELLED_RE`.
    """

    PHRASES = [
        "mnemonic: abandon ability able about above absent absorb abstract",
        "seed_phrase = gravity machine north sort system female filter "
        "attitude volume fold club stay",
        "mnemonic: legal winner thank year wave sausage worth useful",
        "seed-phrase: zombie mass erupt vendor pool trial fatal glove cluster",
    ]

    def _phrase_words(self, text):
        """The words AFTER the label's separator, whatever it is."""
        import re as _re
        body = _re.split(r"(?i)\b(?:mnemonic|seed[_-]?phrase)\b\s*[:=]\s*",
                         text, maxsplit=1)
        self.assertEqual(len(body), 2, "fixture has no label+value shape")
        return [w for w in body[1].replace("-", " ").split() if len(w) >= 3]

    def test_no_word_of_the_phrase_survives(self):
        for text in self.PHRASES:
            with self.subTest(text=text[:32]):
                out = redact_secrets(text)
                words = self._phrase_words(text)
                self.assertGreaterEqual(len(words), 3)
                for w in words[:3]:
                    self.assertNotIn(w, out,
                                     "phrase word %r survived redaction" % w)
                self.assertIn(REDACTED, out)

    def test_value_is_gone_and_label_is_fail_safe_redacted(self):
        """The VALUE must be gone. The label is ALSO redacted, by design.

        `mnemonic`/`seed_phrase`/`private_key` are in the module's pre-existing
        *bare-marker* rule, which replaces the WORD wherever it appears (the
        documented fail-safe: it must still catch `the mnemonic is abandon
        ability able ...` with no `label:` shape at all). So after the
        seed-phrase rule redacts the value, the marker rule also redacts the
        label, giving `[REDACTED-SECRET]: [REDACTED-SECRET]`.

        That is a cosmetic cost, accepted deliberately: dropping the word from
        the marker list would re-open the unlabelled-phrase case, and a model
        that loses the word "mnemonic" is a far smaller problem than a model
        that reads a seed phrase. What is NOT negotiable — and what this test
        pins — is that no word of the phrase survives.
        """
        for text in (
            "mnemonic: abandon ability able about above absent",
            "seed_phrase = gravity machine north sort system female",
        ):
            with self.subTest(text=text[:28]):
                out = redact_secrets(text)
                for w in self._phrase_words(text):
                    self.assertNotIn(w, out,
                                     "phrase word %r survived" % w)
                self.assertIn(REDACTED, out)

    def test_unlabelled_or_is_separated_phrase_is_a_residual_risk(self):
        """No `label:`/`label=` shape => not caught. Documented, not hidden.

        Both a bare word list and a `the mnemonic is <phrase>` sentence are
        deliberately NOT matched: matching either shape also matched ordinary
        English (see TestOverRedactionIsRefused and _SEED_PHRASE_RE's comment).
        The bare-marker rule still redacts the WORD `mnemonic`. This test pins
        the boundary so a later change cannot claim the gap is closed.
        """
        for text in (
            "abandon ability able about above absent absorb abstract",
            "the mnemonic is abandon ability able about above absent today",
        ):
            with self.subTest(text=text[:36]):
                out = redact_secrets(text)
                self.assertNotIn(REDACTED + " " + REDACTED, out)

    def test_hyphen_separated_phrase_is_redacted(self):
        text = "seed-phrase: legal-winner-thank-year-wave-sausage-worth-useful"
        out = redact_secrets(text)
        self.assertNotIn("legal-winner-thank-year", out)

    def test_word_list_rule_alone_leaves_nothing_behind(self):
        """Negative control: _SEED_PHRASE_RE by itself catches the phrase."""
        from agents.integrations import wallet_crypto as wc
        for text in (
            "mnemonic: abandon ability able about above absent",
            "seed_phrase = gravity machine north sort system female",
            "seed-phrase: legal-winner-thank-year-wave-sausage-worth-useful",
        ):
            with self.subTest(text=text[:32]):
                out = wc._SEED_PHRASE_RE.sub(r"\1" + REDACTED, text)
                self.assertNotIn("abandon", out)
                self.assertNotIn("gravity", out)
                self.assertNotIn("legal-winner", out)

    def test_single_word_after_label_is_not_a_phrase(self):
        """Three+ words is the documented shape; one word is not a seed list."""
        out = redact_secrets("mnemonic: abandon")
        # not treated as a multi-word phrase, but the labelled rule and the
        # bare-marker rule still cover the value -- nothing readable survives
        self.assertNotIn("abandon", out)


class TestOverRedactionIsRefused(unittest.TestCase):
    """The word-list rule must NOT match ordinary prose.

    An earlier revision of `_SEED_PHRASE_RE` matched a bare word list with no
    label, and "3+ lowercase words" is also the shape of an English sentence —
    so it redacted normal documentation. `redact_secrets` runs on every file the
    model reads, so that would have gutted the module and pushed callers to
    bypass it. The label is therefore mandatory, and this class pins that.
    """

    PROSE = [
        "See https://example.com/docs for the API key rotation policy.",
        "Run pytest -q and check reports/report.md",
        "The quick brown fox jumps over the lazy dog again",
        "install the package then run the test suite locally first",
        "Discussing seed phrase security in the README.",
        "we should rotate every credential before the next release ships",
    ]

    def test_ordinary_sentences_are_not_redacted(self):
        for text in self.PROSE:
            with self.subTest(text=text[:44]):
                out = redact_secrets(text)
                self.assertNotIn(REDACTED, out,
                                 "prose was over-redacted: %r" % out[:60])

    def test_all_four_are_detected_as_secrets(self):
        """contains_secret is the caller-side gate; it must agree."""
        for text in (
            "mnemonic: abandon ability able about above absent",
            "seed_phrase = gravity machine north sort system female",
            "private_key: MIIBOgIBAAJBAKj34",
            "WALLET_ENC_KEY=dE23Hpd6xTHPkcRs9UELcHXhZWui2_VZfdI7SaEKXMc=",
        ):
            with self.subTest(text=text[:24]):
                self.assertTrue(contains_secret(text), text)


class TestRuleOrderIsLoadBearing(unittest.TestCase):
    """The bug was an ORDERING bug, so the order must be pinned by a test.

    If the value-shaped rules run first, the bare-marker rule eats the label and
    the labelled rule never matches — which is precisely the pre-fix behaviour.
    """

    def test_labelled_rules_run_before_value_shaped_rules(self):
        from agents.integrations import wallet_crypto as wc
        labelled_ids = {id(p) for p in wc._LABELLED_SECRET_PATTERNS}
        order = [id(p) for p, _ in wc._REDACT_RULES]
        labelled_positions = [i for i, pid in enumerate(order)
                              if pid in labelled_ids]
        self.assertEqual(len(labelled_positions), len(labelled_ids),
                         "every labelled rule must be in _REDACT_RULES")
        # all labelled rules must precede every value-shaped rule
        first_value_shaped = next(
            i for i, pid in enumerate(order) if pid not in labelled_ids)
        self.assertLess(max(labelled_positions), first_value_shaped)
        # and the seed-phrase rule must precede the general labelled rule,
        # otherwise `\S{6,}` eats the first word of the phrase
        self.assertLess(order.index(id(wc._SEED_PHRASE_RE)),
                        order.index(id(wc._LABELLED_RE)))

    def test_bare_marker_alone_would_still_leak(self):
        """Negative control: the value-shaped marker rule on its own leaks.

        Proves the fix is the labelled rule + the ordering, not some accidental
        match by an unrelated pattern.
        """
        from agents.integrations import wallet_crypto as wc
        marker = next(
            p for p in wc._SECRET_PATTERNS
            if "mnemonic" in p.pattern)
        text = "mnemonic: abandon ability able about above absent"
        marker_only = marker.sub(wc._REDACTED, text)
        # The marker rule alone replaces the WORD and leaves the phrase.
        self.assertIn("abandon ability able", marker_only)
        # The full rule list, correctly ordered, does not.
        self.assertNotIn("abandon ability able", redact_secrets(text))


class TestFalsePositivesStillHold(unittest.TestCase):
    """Widening the labelled set must not redact ordinary prose or code.

    NOTE: the bare-marker rule (pre-existing, before ARCH-ENG-136) replaces the
    WORD `mnemonic`/`seed_phrase`/`private_key` even in ordinary prose. That is
    the module's documented deliberate fail-safe: a false redaction costs the
    model a word, a false pass costs the operator a wallet. ARCH-ENG-136 does
    NOT change it — verified against the HEAD version of this module. So these
    tests assert the value is not over-redacted where no value exists, not that
    the marker word survives.
    """

    def test_prose_with_no_value_is_only_marker_redacted(self):
        """Only the marker word goes; nothing else in the sentence changes.

        `is` is NOT an accepted separator (see _SEED_PHRASE_RE's comment: it
        matched `mnemonic is stored encrypted and never logged verbatim`),
        so this sentence loses only the marker word.
        """
        text = "The mnemonic is stored encrypted and never logged verbatim."
        out = redact_secrets(text)
        self.assertIn("is stored encrypted and never logged verbatim", out)
        self.assertNotIn("mnemonic", out)

    def test_code_naming_mnemonic_keeps_its_signature(self):
        out = redact_secrets("def check(mnemonic: str) -> bool: return True")
        self.assertIn("def check(", out)
        self.assertIn("-> bool: return True", out)

    def test_short_placeholder_values_are_not_secret_redacted(self):
        """A 3-char placeholder is not a secret value.

        The marker word itself may still be replaced (pre-existing fail-safe);
        what must NOT happen is a marker appearing where there is no secret.
        """
        for text in ("password: none", "mnemonic: n/a", "private_key: TBD"):
            with self.subTest(text=text):
                out = redact_secrets(text)
                self.assertNotIn(REDACTED + " " + REDACTED, out)

    def test_previously_verified_clean_strings_stay_clean(self):
        for text in (
            "pip install PySide6>=6.5.0 requests==2.31.0",
            r"C:\Users\cecil\Projects\MrBot1000_2.0\README.md",
            "email us at support@example.com",
        ):
            with self.subTest(text=text[:40]):
                self.assertEqual(redact_secrets(text), text)

    def test_doc_prose_redacts_only_the_marker_word(self):
        """URLs/prose that merely mention a key name keep their content."""
        cases = (
            ("See https://example.com/docs for the API key rotation policy.",
             "https://example.com/docs"),
            ("Run pytest -q and check reports/report.md",
             "reports/report.md"),
        )
        for text, must_keep in cases:
            with self.subTest(text=text[:40]):
                out = redact_secrets(text)
                self.assertIn(must_keep, out)


class TestPreviouslyFixedPatternsStillHold(unittest.TestCase):
    """ARCH-ENG-135's coverage must not regress while fixing 136."""

    def test_value_shaped_credentials_are_redacted(self):
        cases = {
            "OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOP1234": "sk-proj-ABCDEFGHIJKLMNOP1234",
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
            "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE": "AKIAIOSFODNN7EXAMPLE",
            "SLACK=xoxb-123456789012-ABCDEFGHIJKL": "xoxb-123456789012-ABCDEFGHIJKL",
            "UPWORK_CLIENT_SECRET=abc123def456ghi": "abc123def456ghi",
        }
        for text, secret in cases.items():
            with self.subTest(text=text[:32]):
                out = redact_secrets(text)
                self.assertNotIn(secret, out)
                self.assertIn(REDACTED, out)

    def test_pem_block_is_redacted_whole(self):
        text = ("-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34\n"
                "-----END RSA PRIVATE KEY-----")
        out = redact_secrets(text)
        self.assertNotIn("MIIBOgIBAAJBAKj34", out)

    def test_label_survives_so_model_learns_which_key(self):
        out = redact_secrets("OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOP1234")
        self.assertIn("OPENAI_API_KEY=", out)

    def test_redaction_is_idempotent(self):
        for text in (
            "mnemonic: abandon ability able about above absent",
            "OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOP1234",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc",
        ):
            with self.subTest(text=text[:32]):
                once = redact_secrets(text)
                self.assertEqual(redact_secrets(once), once)


if __name__ == "__main__":
    unittest.main()
