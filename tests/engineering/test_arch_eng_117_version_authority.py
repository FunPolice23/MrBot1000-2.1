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
"""
import re
from pathlib import Path

REPO = Path(r"D:\MrBot1000_2.0")


def test_app_version_is_the_authority():
    from app.version import VERSION, __version__

    assert __version__ == VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_main_py_fallback_literal_matches_the_authority():
    """The unreachable fallback must not report a stale release."""
    import ast
    import inspect

    from app.version import __version__

    import main

    src = inspect.getsource(main)
    tree = ast.parse(src)
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"\d+\.\d+\.\d+", node.value)
    ]
    assert literals, "no version literal found in main.py"
    stale = [v for v in literals if v != __version__]
    assert not stale, (
        f"main.py carries version literal(s) {stale} that disagree with the "
        f"authority {__version__} (app/version.py). A wrong version reported "
        f"during a broken install is worse than none.")


def test_readme_documents_the_current_authority():
    from app.version import __version__

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    m = None
    for line in readme.splitlines():
        if "`app/version.py`" in line:
            # The cell reads "... (`2.1.92`)" — version inside backticks.
            found = re.search(r"\(`?(\d+\.\d+\.\d+)`?\)", line)
            if found:
                m = found
                break
    assert m, "README.md no longer documents the app/version.py authority"
    assert m.group(1) == __version__, (
        f"README.md documents the version authority as {m.group(1)} but "
        f"app/version.py says {__version__}")


def test_changelog_top_entry_matches_the_authority():
    from app.version import __version__

    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    assert m, "CHANGELOG.md has no version heading"
    assert m.group(1) == __version__, (
        f"CHANGELOG.md's top entry is {m.group(1)} but app/version.py says "
        f"{__version__} — the release history and the shipped version disagree")
