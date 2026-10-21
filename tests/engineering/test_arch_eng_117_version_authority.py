"""ARCH-ENG-117 — no competing version authorities.

`app/version.py` is the single source of truth for the release version. Two
other places carried their own copy and had drifted:

* `main.py` had a last-resort literal `"2.1.31"` — sixty-one releases stale. It
  is unreachable in practice (`app/version.py` has no dependencies), which is
  exactly why the drift went unnoticed: nothing ever executed it, so nothing
  ever compared it.
* `README.md`'s file-map table documented the authority as `2.1.86`.

A stale literal is not harmless. It only runs when the import fails, i.e. in a
broken install — the one moment the operator is already trying to work out what
they are running — and it then reports a confidently wrong version.

These tests keep the copies in step.

Hermeticity (why the authority is read FRESH, not import-cached): a concurrent
agent bumps the version mid-suite, rewriting CHANGELOG.md and app/version.py
~45s apart. `from app.version import __version__` is cached at session start,
so a cross-file comparison would see a fresh-on-disk CHANGELOG against a
minutes-stale cached version and red-line the whole run on a transient race —
not a real drift. Reading the authority straight from app/version.py at
assertion time (parsing the file, NOT importlib.reload, which would mutate the
session-wide module symbol) keeps the comparison honest without introducing a
new contamination source. REPO is derived from the installed `app` package so
the test runs in any checkout (worktree, CI, fresh clone) — never a hardcoded
path.

"""
import ast
import inspect
import re
from pathlib import Path

import app


def _repo_root() -> Path:
    """Repo root derived from the installed `app` package (checkout-agnostic)."""
    return Path(app.__file__).resolve().parents[1]


def _authority_version() -> str:
    """The release version, read FRESH from app/version.py at call time.

    Parses the file rather than importing the cached symbol, so a concurrent
    mid-run version bump can't make a cross-file comparison see a stale
    authority. Returns "" if the literal can't be found (the caller asserts).
    """
    version_file = _repo_root() / "app" / "version.py"
    m = re.search(
        r'^__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']',
        version_file.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return m.group(1) if m else ""


def test_app_version_is_the_authority():
    from app.version import VERSION, __version__

    assert __version__ == VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_main_py_fallback_literal_matches_the_authority():
    """The unreachable fallback must not report a stale release."""
    import main

    authority = _authority_version()
    assert authority, "could not read VERSION from app/version.py"

    src = inspect.getsource(main)
    tree = ast.parse(src)
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"\d+\.\d+\.\d+", node.value)
    ]
    assert literals, "no version literal found in main.py"
    stale = [v for v in literals if v != authority]
    assert not stale, (
        f"main.py carries version literal(s) {stale} that disagree with the "
        f"authority {authority} (app/version.py). A wrong version reported "
        f"during a broken install is worse than none.")


def test_readme_documents_the_current_authority():
    authority = _authority_version()
    assert authority, "could not read VERSION from app/version.py"

    readme = (_repo_root() / "README.md").read_text(encoding="utf-8")
    m = None
    for line in readme.splitlines():
        if "`app/version.py`" in line:
            # The cell reads "... (`2.1.92`)" — version inside backticks.
            found = re.search(r"\(`?(\d+\.\d+\.\d+)`?\)", line)
            if found:
                m = found
                break
    assert m, "README.md no longer documents the app/version.py authority"
    assert m.group(1) == authority, (
        f"README.md documents the version authority as {m.group(1)} but "
        f"app/version.py says {authority}")


def test_changelog_top_entry_matches_the_authority():
    authority = _authority_version()
    assert authority, "could not read VERSION from app/version.py"

    changelog = (_repo_root() / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    assert m, "CHANGELOG.md has no version heading"
    assert m.group(1) == authority, (
        f"CHANGELOG.md's top entry is {m.group(1)} but app/version.py says "
        f"{authority} — the release history and the shipped version disagree")
