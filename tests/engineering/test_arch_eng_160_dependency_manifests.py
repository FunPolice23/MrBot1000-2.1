"""ARCH-ENG-160 — every third-party import must be declared in a manifest.

Two defects, one root cause: the dependency manifests were curated by hand and
nothing verified them against the code.

1. `cryptography` was absent from `requirements.txt` while
   `agents/integrations/wallet_crypto.py` imports Fernet at module level. On a
   fresh clone `CredentialVault.__init__` raises
   `RuntimeError("cryptography is required for wallet encryption")`, so every
   wallet and platform-secret path was dead on arrival. The package WAS present
   in `requirements.lock.txt` — so the lock and the curated set disagreed, and
   the curated set is what a fresh install actually reads. This is the same gap
   ARCH-ENG-108 closed for `openai`/`psutil`, recurring because nothing asserted
   the invariant.

2. `ccxt` appeared in NEITHER file, and `requirements-cloud.txt` /
   `requirements-live.txt` were referenced by README.md but had never been
   written. Both documented install commands failed with a pip path error, and
   there was no documented way to install the exchange SDK at all.

The mechanism that lets this recur is a pure convention: "keep requirements.txt
in sync when you add an import". This suite replaces the convention with a check.

METHOD
Parse each manifest's pinned names, then AST-parse the tracked tree and collect
every top-level `import X` / `from X import ...` where X is not a relative
import, not `__future__`, not stdlib, and not a local top-level package. A module
no manifest declares is reported.

Two normalisations matter, and getting them wrong produces exactly the false
alarms that train an operator to ignore a guard:
  * Import names and DISTRIBUTION names differ. `beautifulsoup4` provides
    `bs4`, `python-dotenv` provides `dotenv`, `ddgs` also provides the legacy
    `duckduckgo_search`. `_ALIASES` maps distribution -> import name.
  * Module names use underscores; distributions may use hyphens. Both sides are
    canonicalised to lowercase-hyphen BEFORE the stdlib test, because
    `py_compile` canonicalises to `py-compile` which is NOT in
    `sys.stdlib_module_names`.

SCOPE
This asserts DECLARATION, not installation or importability. A declared package
may still be absent from a given environment; that is a runtime question. What
this closes is the specific failure where a package the code imports is
documented nowhere.

`ALLOWED_UNDECLARED` lists imports that are genuinely optional. Each was checked
to fail SOFT — guarded by try/except, or a function-local (lazy) import reached
only when the operator has configured that provider. None of them can break a
default install, which is the property `cryptography` lacked.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# ARCH-ENG-113/149 class: never hardcode `D:\MrBot1000_2.0`. A fresh clone must
# probe ITSELF, not the live operator repo.
assert (REPO / "agents" / "safety").is_dir(), f"repo root misresolved: {REPO}"

MANIFESTS = (
    "requirements.txt",
    "requirements-cloud.txt",
    "requirements-live.txt",
    "requirements.lock.txt",
)

# The repo's own top-level modules/packages. Not third-party.
LOCAL_PACKAGES = {"agents", "app", "gui", "skills", "tests", "tools", "main"}

# distribution name -> additional import name(s) it provides.
_ALIASES = {
    "beautifulsoup4": {"bs4"},
    "python-dotenv": {"dotenv"},
    "ddgs": {"duckduck_search", "duckduckgo-search"},
}

# Optional imports, each verified to fail SOFT (guarded try/except, or a lazy
# function-local import only reached when that provider is configured).
ALLOWED_UNDECLARED = {
    # ARCH-ENG-164: the last `hermes_tools` import was removed, so this package
    # is no longer referenced by any module and needs no exemption.
    # ARCH-ENG-160: never a real dependency. It was referenced only by the
    # `agents/safety/legacy_tools.py` web_search branch, dead on every stock
    # install since the project began.
    # agents/earning/live_trading.py — raises LiveTradingError when absent.
    # Now declared in requirements-live.txt; exempted for a minimal install.
    "ccxt",
    # agents/providers/anthropic_adapter.py — guarded by
    # `AnthropicAdapter.available()`. Declared in requirements-cloud.txt.
    "anthropic",
    # agents/integrations/crypto.py — wrapped in try/except ImportError; the
    # wallet/crypto features degrade to unavailable without them.
    "web3", "eth-account", "solana",
    # agents/integrations/browser.py — try/except around the DDGS import.
    "duckduckgo-search",
    # agents/integrations/web.py:120 — function-local import inside
    # `_search_tavily`, reached only when WEB_PROVIDER=tavily is configured.
    "tavily",
    # agents/evidence/document_scanner.py — try/except per PDF backend.
    "pypdf2", "fitz",
    # agents/runtime/llm.py — try/except; token counting falls back.
    "tiktoken",
    # agents/runtime/llm.py:52 — try/except around cuda detection.
    "torch",
    # agents/brains/base_worker.py — try/except sets GROQ_AVAILABLE = False.
    "groq",
    # agents/core/notifications.py — try/except; desktop toasts are skipped.
    "win10toast",
}


def _canon(name: str) -> str:
    """Canonical comparison form: lowercase, underscores to hyphens."""
    return name.strip().lower().replace("_", "-")


def _declared_packages() -> set:
    """Canonical import names declared across every manifest."""
    names = set()
    for manifest in MANIFESTS:
        path = REPO / manifest
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            token = line.split("==")[0].split(">=")[0].split("<=")[0]
            token = token.split("[")[0].split(";")[0].strip()
            if not token or token.startswith("-"):
                continue
            dist = _canon(token)
            names.add(dist)
            for extra in _ALIASES.get(dist, ()):
                names.add(_canon(extra))
    return names


def _top_level_imports() -> dict:
    """{canonical module name: first path that imports it} across the tree.

    Includes `tools/` (a developer package the manifests must still cover).
    Reuses the single-pass site index where possible.
    """
    found = {}
    for root in ("agents", "app", "gui", "tools"):
        for path in (REPO / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"),
                                 filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.setdefault(_canon(alias.name.split(".")[0]), path)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:                       # relative — local
                        continue
                    if node.module == "__future__":      # language directive
                        continue
                    if node.module:
                        found.setdefault(_canon(node.module.split(".")[0]), path)
    return found


def _is_stdlib(canon_name: str) -> bool:
    """True iff `canon_name` is a stdlib module (canonicalised for comparison)."""
    stdlib = {_canon(m) for m in sys.stdlib_module_names}
    return canon_name in stdlib


class TestDependencyManifests(unittest.TestCase):
    """ARCH-ENG-160 — declared in a manifest, or the manifest is wrong."""

    @classmethod
    def setUpClass(cls):
        cls.declared = _declared_packages()
        cls.imports = _top_level_imports()

    def test_manifests_exist(self):
        """ARCH-ENG-160: README referenced two files that were never written."""
        for manifest in ("requirements.txt", "requirements-cloud.txt",
                         "requirements-live.txt"):
            self.assertTrue((REPO / manifest).is_file(),
                            f"{manifest} is referenced by the README but does not exist")

    def test_cryptography_is_a_hard_requirement(self):
        """The wallet/credential encryption path is not optional.

        `wallet_crypto.py` imports Fernet at module level, so an undeclared
        `cryptography` makes `CredentialVault` unconstructible — 6 tests in
        tests/platforms/test_credential_vault.py and
        tests/earning/test_moltbook_registration.py failed on exactly this.
        """
        self.assertIn("cryptography", self.declared,
                      "cryptography is imported at module level by "
                      "agents/integrations/wallet_crypto.py and must be declared "
                      "in requirements.txt, not left to the lock file")

    def test_beautifulsoup_and_dotenv_aliases_resolve(self):
        """Import-name/distribution-name differences must not read as gaps.

        A guard that flags `bs4` on a repo whose manifest says `beautifulsoup4`
        is a false-alarm machine; that is how the ARCH-ENG-150 test's own
        docstring describes a control losing its value.
        """
        self.assertIn("bs4", self.declared)
        self.assertIn("dotenv", self.declared)
        self.assertNotIn("bs4", self.undeclared())
        self.assertNotIn("dotenv", self.undeclared())

    def undeclared(self) -> dict:
        out = {}
        for module, path in self.imports.items():
            if module in LOCAL_PACKAGES or _is_stdlib(module):
                continue
            if module in self.declared or module in ALLOWED_UNDECLARED:
                continue
            out[module] = path
        return out

    def test_every_third_party_import_is_declared(self):
        """No module-scope third-party import may be undeclared."""
        gaps = self.undeclared()
        self.assertEqual(
            gaps, {},
            "these third-party modules are imported but declared in no manifest "
            "(add them to requirements.txt, or to requirements-cloud.txt / "
            "-live.txt if optional, or document them in ALLOWED_UNDECLARED with "
            "a reason): "
            + ", ".join(f"{m} ({p.relative_to(REPO)})" for m, p in sorted(gaps.items())))

    def test_curated_set_is_a_subset_of_the_lock(self):
        """ARCH-ENG-160: requirements.txt must not drift from the lock.

        `cryptography` was in the lock but not the curated set — the curated set
        is what a fresh install reads, so a package present only in the lock is
        a package a fresh clone does not have.
        """
        curated = set()
        for raw in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            token = line.split("==")[0].split(">=")[0].strip()
            if token:
                curated.add(_canon(token))
        missing = sorted(curated - _declared_packages())
        self.assertEqual(
            missing, [],
            "pinned in requirements.txt but absent from requirements.lock.txt — "
            "refresh it with `pip freeze > requirements.lock.txt` "
            "(ARCH-ENG-108 procedure): " + ", ".join(missing))

    def test_allowed_undeclared_are_actually_soft(self):
        """Each exemption must be an import that cannot break a default install.

        Exemptions rot: a package can be promoted from lazy/guarded to a bare
        module-scope import and the exemption would silently permit the exact
        ARCH-ENG-160 defect. This asserts, via AST (not regex), that every
        module-scope import of an exempted package sits inside a `try` block,
        and that each package has at least one lazy-or-guarded site.
        """
        for mod in sorted(ALLOWED_UNDECLARED):
            sites = list(_import_sites(mod))

            self.assertTrue(sites, f"{mod} is exempted but never imported; "
                                   f"ALLOWED_UNDECLARED has rotted")

            bare = [p for p, guarded, lazy in sites if not guarded and not lazy]
            self.assertEqual(
                bare, [],
                f"{mod} is imported at unguarded module scope in "
                f"{[str(b.relative_to(REPO)) for b in bare]} — "
                f"this is the ARCH-ENG-160 failure mode (a module-scope import "
                f"that breaks a default install). Wrap it in try/except, make it "
                f"lazy, declare it, or drop the exemption.")

    def test_cryptography_is_not_exempt(self):
        """The defect this suite exists for must never become an exemption."""
        self.assertNotIn("cryptography", ALLOWED_UNDECLARED,
                         "cryptography is a HARD requirement — it must be "
                         "declared in requirements.txt, never exempted")


_SITE_INDEX = None


def _site_index():
    """One AST pass over agents/app/gui -> {canonical module: [(path, guarded, lazy)]}.

    Built ONCE. The naive version recomputed the guarded/lazy node sets per
    queried module, which turned a sub-second check into a two-minute one — a
    guard slow enough to be skipped is not a guard.
    """
    global _SITE_INDEX
    if _SITE_INDEX is not None:
        return _SITE_INDEX

    index = {}
    for root in ("agents", "app", "gui"):
        for path in (REPO / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue

            guarded, lazy = set(), set()
            # An import directly inside a `try:` body is guarded.
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for stmt in node.body:
                        for sub in ast.walk(stmt):
                            guarded.add(id(sub))
            # An import nested inside a function/lambda/class body is lazy.
            for parent in ast.walk(tree):
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef, ast.Lambda)):
                    for sub in ast.walk(parent):
                        lazy.add(id(sub))

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod = _canon((node.module or "").split(".")[0])
                elif isinstance(node, ast.Import):
                    mod = _canon(node.names[0].name.split(".")[0])
                else:
                    continue
                if not mod:
                    continue
                index.setdefault(mod, []).append(
                    (path, id(node) in guarded, id(node) in lazy))

    _SITE_INDEX = index
    return index


def _import_sites(canon_module: str):
    """(path, guarded_by_try, is_lazy) for every import of `canon_module`.

    AST-based rather than regex-based: a text match cannot distinguish
    `import groq` from `from groq import Groq`, nor tell a module-scope import
    from one nested in a function body.
    """
    return _site_index().get(canon_module, ())


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-160 — the probe must fail when the invariant is broken.

    A guard that only ever passes on a healthy tree proves nothing. This asserts
    the DETECTOR works, by feeding the collector a synthetic import that no
    manifest declares and confirming it is both seen and reported.
    """

    @classmethod
    def setUpClass(cls):
        cls.declared = _declared_packages()

    def test_collector_sees_and_reports_an_undeclared_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "fakepkg"
            pkg.mkdir()
            (pkg / "mod.py").write_text(
                "import definitely_not_a_real_package_xyz\n", encoding="utf-8")
            tree = ast.parse((pkg / "mod.py").read_text(encoding="utf-8"))
            mods = {_canon(a.name.split(".")[0]) for n in ast.walk(tree)
                    if isinstance(n, ast.Import) for a in n.names}
        self.assertIn("definitely-not-a-real-package-xyz", mods)
        self.assertNotIn("definitely-not-a-real-package-xyz", self.declared)
        # It is not stdlib, not local, not exempt -> the guard would report it.
        self.assertNotIn("definitely-not-a-real-package-xyz",
                         LOCAL_PACKAGES | ALLOWED_UNDECLARED)
        self.assertFalse(_is_stdlib("definitely-not-a-real-package-xyz"))

    def test_future_directive_is_not_reported(self):
        """`from __future__ import ...` is a language directive, not a package."""
        tree = ast.parse("from __future__ import annotations\n")
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level or node.module == "__future__":
                    continue
                found.add(node.module)
        self.assertEqual(found, set())

    def test_stdlib_detection_survives_underscore_canonicalisation(self):
        """`py_compile` canonicalises to `py-compile`; the stdlib test must cope.

        Getting this wrong makes every underscore-named stdlib module look like
        an undeclared dependency — the false alarm that disarms a guard.
        """
        for mod in ("py_compile", "os", "sys", "ast", "pathlib", "tempfile",
                    "sqlite3", "threading"):
            self.assertTrue(_is_stdlib(_canon(mod)),
                            f"{mod} misclassified as third-party")


if __name__ == "__main__":
    unittest.main()