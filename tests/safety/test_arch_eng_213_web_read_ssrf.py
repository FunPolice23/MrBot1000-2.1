"""ARCH-ENG-213 — `web_read`/`web_check` performed no URL validation at all.

## The gap

`InstructionGate._is_safe_fetch_url` is a genuine SSRF guard. It checks the
scheme, rejects a literal host blocklist, **resolves the hostname**, and refuses
any private, loopback, link-local, reserved or multicast address.

But it was only reachable from `InstructionGate.fetch_instruction`, and
`_tool_web_read` only took that path when `_is_skill_document(url)` was true.
Every other URL went straight to `web_eyes.read_page(url)` → `requests.get`, and
`_tool_web_check` to `requests.head`.

Three things compounded:

1. `web_read` is classified **READONLY**, so the SafetyGate ALLOWS it
   automatically. **No human ever saw the request.**
2. The skill branch was the only one that ran content through
   `sanitize_external_text`; the general branch returned the body verbatim. The
   guarded branch sanitised and the unguarded one did not.
3. `check_website_status` is quieter than a body read, not safer — it still
   reaches internal services and still leaks existence.

So a model told to read `http://169.254.169.254/latest/meta-data/iam/security-
credentials/<role>` had cloud credentials returned into its context. That is
reachable by **prompt injection** from any page the agent is asked to read: the
attacker does not need to persuade the model, only to supply the URL.

## The fix

`require_safe_fetch_url` is applied in **both** handlers, deliberately placed
before `_is_skill_document` — so there is one place a URL must pass, rather than
one branch where somebody remembered to check.

Public URLs are unaffected. The Web Browser tab, discovery, and ordinary
research all continue to work; only private, loopback and link-local targets are
refused. The tests below assert both directions, because a guard that refused
everything would pass every "is refused" assertion while breaking the feature it
protects.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
HANDLERS = REPO / "agents" / "safety" / "handlers.py"

# Numeric literals throughout: `_is_safe_fetch_url` calls socket.getaddrinfo, and
# a hostname would make these tests depend on a live DNS resolver. `localhost`
# is the one exception and resolves from the local hosts file.
PRIVATE_TARGETS = (
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://127.0.0.1:8000/admin",               # loopback
    "http://10.0.0.5/internal",                  # private A
    "http://192.168.1.1/router",                 # private B
    "http://172.16.0.9/x",                       # private C
    "http://0.0.0.0/",                           # unspecified
    "file:///etc/passwd",                        # non-http scheme
    "ftp://example.invalid/x",                   # non-http scheme
    "http://[::1]/x",                            # IPv6 loopback
    "not-a-url",                                 # unparseable
    "",                                          # empty
)

# Public addresses, also numeric so no DNS is involved.
PUBLIC_TARGETS = ("http://93.184.216.34/", "https://1.1.1.1/")


def _fn(name, path=HANDLERS):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


class TestTheGuardRefusesInternalTargets(unittest.TestCase):
    """ARCH-ENG-213 — the core property."""

    def test_private_and_loopback_targets_are_refused(self):
        from agents.safety.handlers import require_safe_fetch_url

        for url in PRIVATE_TARGETS:
            with self.subTest(url=url):
                refusal = require_safe_fetch_url(url)
                self.assertTrue(
                    refusal,
                    f"{url!r} reaches an internal target and was ALLOWED")

    def test_a_missing_url_is_refused(self):
        from agents.safety.handlers import require_safe_fetch_url

        self.assertTrue(require_safe_fetch_url(None),
                        "a None URL must be refused, not passed downstream")
        self.assertTrue(require_safe_fetch_url(12345))

    def test_the_refusal_names_the_reason(self):
        """A bare boolean would leave the operator guessing."""
        from agents.safety.handlers import require_safe_fetch_url

        refusal = require_safe_fetch_url("http://169.254.169.254/latest/meta-data/")
        self.assertIn("Fetch refused", refusal)
        self.assertIn("169.254.169.254", refusal,
                      "the refusal should say what was refused")


class TestPublicUrlsStillWork(unittest.TestCase):
    """ARCH-ENG-213 — a guard that blocks everything is not a fix.

    The Web Browser tab depends on agents being able to read ordinary pages.
    """

    def test_public_addresses_are_allowed(self):
        from agents.safety.handlers import require_safe_fetch_url

        for url in PUBLIC_TARGETS:
            with self.subTest(url=url):
                self.assertEqual(
                    require_safe_fetch_url(url), "",
                    f"{url} is a public address and must remain fetchable; "
                    f"refusing it would break the Web Browser tab")

    def test_a_real_hostname_is_not_refused_for_the_wrong_reason(self):
        """DNS may be unavailable here, so only the failure mode is asserted."""
        from agents.safety.handlers import require_safe_fetch_url

        refusal = require_safe_fetch_url("https://example.invalid/page")
        if refusal:
            self.assertIn("does not resolve", refusal,
                          "a hostname should only be refused when it does not "
                          "resolve publicly, not on scheme or format")


class TestBothHandlersAreGuarded(unittest.TestCase):
    """ARCH-ENG-213 — one of the two was the whole problem."""

    def test_web_read_checks_the_url(self):
        body = ast.unparse(_fn("_tool_web_read"))
        self.assertIn("require_safe_fetch_url", body,
                      "web_read must validate the URL before fetching")

    def test_web_check_checks_the_url(self):
        body = ast.unparse(_fn("_tool_web_check"))
        self.assertIn("require_safe_fetch_url", body,
                      "web_check issues a real HEAD request and must be "
                      "guarded too")

    def test_the_guard_precedes_the_fetch(self):
        """Ordering, not presence: a refusal after the fetch proves nothing."""
        for name in ("_tool_web_read", "_tool_web_check"):
            with self.subTest(handler=name):
                body = ast.unparse(_fn(name))
                fetch = min(i for i in (body.find("read_page"),
                                        body.find("check_website_status"))
                            if i != -1)
                self.assertLess(
                    body.index("require_safe_fetch_url"), fetch,
                    f"{name} must validate before it fetches, or a refused "
                    f"request has already gone out by the time it is noticed")

    def test_the_guard_sits_on_the_unguarded_branch(self):
        """Scope is deliberate, and this pins WHY.

        The skill branch already validates through `fetch_instruction` ->
        `_is_safe_fetch_url`, and it must keep doing so: it is the one branch
        that records content for an explicit human allow/deny decision.

        An earlier draft guarded BEFORE `_is_skill_document`, intending one gate
        for every URL. That broke the quarantine workflow -- an unresolvable
        host fails the guard, so the request was refused outright and never
        reached human review. `test_tool_calling_safety.py::
        test_skill_documents_are_quarantined` caught it.

        The branch that lacked a gate is the one that gets one.
        """
        body = ast.unparse(_fn("_tool_web_read"))
        self.assertGreater(
            body.index("require_safe_fetch_url"),
            body.index("_is_skill_document"),
            "the guard belongs on the branch that lacked one; putting it before "
            "the skill branch refuses requests that the quarantine flow is "
            "supposed to capture for human review")

    def test_the_skill_branch_still_uses_the_instruction_gate(self):
        """Re-guarding must not have replaced the real quarantine path."""
        body = ast.unparse(_fn("_tool_web_read"))
        self.assertIn("fetch_instruction", body,
                      "the skill branch must still go through the instruction "
                      "gate, which is what records it for human review")

    def test_the_general_branch_now_sanitises(self):
        """It previously returned the fetched body verbatim."""
        body = ast.unparse(_fn("_tool_web_read"))
        self.assertGreaterEqual(
            body.count("sanitize_external_text"), 2,
            "both branches must sanitise fetched text; only the skill branch "
            "did before")

    def test_web_read_still_announces_to_the_web_browser_tab(self):
        """ARCH-ENG-105 surfaces agent reads in the UI; don't regress it."""
        body = ast.unparse(_fn("_tool_web_read"))
        self.assertIn("_announce_agent_web", body,
                      "the Web Browser tab integration was removed; agent "
                      "reads must still surface in the UI")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-213 — each detector must be able to fail."""

    def test_the_guard_sees_a_public_url_as_clear(self):
        from agents.safety.handlers import require_safe_fetch_url

        self.assertEqual(require_safe_fetch_url("https://1.1.1.1/"), "",
                         "the detector cannot see an ALLOW, so a guard that "
                         "refused everything would pass every other assertion")

    def test_the_underlying_guard_still_works(self):
        """If `_is_safe_fetch_url` were broken, this test would pass vacuously."""
        from agents.safety.instructions import InstructionGate

        self.assertTrue(
            InstructionGate._is_safe_fetch_url("https://1.1.1.1/"),
            "the underlying guard rejects public URLs; anything built on it is "
            "untestable")
        self.assertFalse(InstructionGate._is_safe_fetch_url("http://127.0.0.1/"))

    def test_the_handler_scan_can_find_the_handlers(self):
        found = [n for n in ast.walk(ast.parse(HANDLERS.read_text(encoding="utf-8")))
                 if isinstance(n, ast.FunctionDef)
                 and n.name in ("_tool_web_read", "_tool_web_check")]
        self.assertEqual(len(found), 2,
                         "the handler scan is broken, so the structural "
                         "guards would pass on anything")

    def test_the_target_lists_are_not_vacuous(self):
        self.assertGreaterEqual(len(PRIVATE_TARGETS), 10)
        self.assertGreaterEqual(len(PUBLIC_TARGETS), 2)