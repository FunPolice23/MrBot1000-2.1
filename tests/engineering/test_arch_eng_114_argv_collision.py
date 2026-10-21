"""ARCH-ENG-114 — main.py must not parse the HOST process's argv at import.

`main.py` defines a CLI parser for `-sm` / `--safe-mode` and used to call
`parse_known_args()` unconditionally at module scope. `parse_known_args` is
deliberately permissive, so importing main under a host that owns argv steals
that host's flags:

    python -m pytest -s        ->  -s + m  ==  -sm   ->  MRBOT_SAFE_MODE=true

Measured directly: `parse_known_args(['-s'])` returns `safe_mode=True`. So any
operator or CI run that added `-s` (pytest's no-capture flag) flipped safe mode
on for the WHOLE session. `ActionPipeline.__init__` reads `MRBOT_SAFE_MODE` from
the process env, so every pipeline built afterwards skipped its file writes, and
3 tests in tests/safety/test_safe_mode_pipeline.py failed — in a file that
passes 5/5 when run alone, purely because of the command line.

The fix: parse argv only when main.py is the entrypoint (`__name__ == "__main__"`).
"""
import argparse
import inspect
import os
import sys

from pathlib import Path
MAIN = str(Path(__file__).resolve().parents[2] / "main.py")


def _guarded_block():
    """The real source of the `-sm` parser + its guard, exactly as shipped.

    Sliced from the `import argparse` line so the extracted block defines
    `_parser` itself and is runnable standalone.
    """
    import main

    src = inspect.getsource(main)
    start = src.index("import argparse")
    end = src.index("import html", start)
    return src[start:end]


def test_pytest_dash_s_is_not_parsed_as_safe_mode():
    """The exact collision: argparse expands the `-s` `-m` cluster to `-sm`."""
    parser = argparse.ArgumentParser()
    parser.add_argument("-sm", "--safe-mode", action="store_true")
    parsed, _ = parser.parse_known_args(["-s"])
    assert parsed.safe_mode is True, (
        "argparse no longer expands `-s` to `-sm`; the collision this test "
        "guards against has changed shape and the guard may need revisiting")


def test_the_guarded_block_parses_only_as_the_entrypoint():
    """Structural lock: the parse must sit under a `__name__ == "__main__"` guard."""
    block = _guarded_block()
    assert '__name__ == "__main__"' in block, (
        "parse_known_args() is no longer guarded by the __main__ check, so a "
        "host process importing main.py will again consume its argv")
    assert block.count("_parser.parse_known_args()") == 1


def test_entrypoint_still_enables_safe_mode():
    """The operator-facing feature must survive: `python main.py -sm`."""
    block = _guarded_block()
    os.environ.pop("MRBOT_SAFE_MODE", None)
    saved_argv = sys.argv
    sys.argv = ["main.py", "-sm"]
    try:
        exec(compile(block, MAIN, "exec"),
             {"__name__": "__main__", "argparse": argparse, "os": os})
        assert os.environ.get("MRBOT_SAFE_MODE") == "true", (
            "`python main.py -sm` no longer enables safe mode — the CLI flag "
            "was lost in the __main__ guard")
    finally:
        sys.argv = saved_argv
        os.environ.pop("MRBOT_SAFE_MODE", None)


def test_import_is_inert_under_the_colliding_host_flag():
    """Same block, `__name__ != "__main__"`, argv = pytest's `-s`: nothing set."""
    block = _guarded_block()
    os.environ.pop("MRBOT_SAFE_MODE", None)
    saved_argv = sys.argv
    sys.argv = ["pytest", "-s", "-q", "tests/"]
    try:
        exec(compile(block, MAIN, "exec"),
             {"__name__": "main", "argparse": argparse, "os": os})
        assert os.environ.get("MRBOT_SAFE_MODE") is None, (
            "the guarded block still parsed argv while imported, so "
            "`pytest -s` re-enables safe mode for the whole session")
    finally:
        sys.argv = saved_argv
        os.environ.pop("MRBOT_SAFE_MODE", None)


def test_importing_main_does_not_set_safe_mode():
    """End-to-end: really execute main.py's module scope under a pytest argv.

    Boots the real module (importlib, not a subprocess — pytest on Windows
    cannot spawn one here), with `__name__` bound away from "__main__" so the
    GUI entrypoint block at the bottom of main.py is not reached.
    """
    import importlib.util

    os.environ.pop("MRBOT_SAFE_MODE", None)
    saved_argv = sys.argv
    saved_mod = sys.modules.get("main")
    sys.argv = ["pytest", "-s", "-q", "tests/"]
    try:
        spec = importlib.util.spec_from_file_location("main_probe", MAIN)
        module = importlib.util.module_from_spec(spec)
        sys.modules["main_probe"] = module
        spec.loader.exec_module(module)
        assert os.environ.get("MRBOT_SAFE_MODE") is None, (
            "importing main.py set MRBOT_SAFE_MODE from the host's argv — the "
            "import-time parse_known_args is back")
    finally:
        sys.argv = saved_argv
        sys.modules.pop("main_probe", None)
        if saved_mod is not None:
            sys.modules["main"] = saved_mod
        os.environ.pop("MRBOT_SAFE_MODE", None)


def test_action_pipeline_honours_an_explicit_safe_mode_argument():
    """The env read is legitimate in production; the constructor arg must still
    win so a caller can force safe mode off for an isolated pipeline."""
    import tempfile

    from app.action_pipeline import ActionPipeline

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MRBOT_SAFE_MODE"] = "false"
        try:
            assert ActionPipeline(
                root_folder=tmp, log_fn=lambda _: None,
                safe_mode=False).safe_mode is False
            assert ActionPipeline(
                root_folder=tmp, log_fn=lambda _: None,
                safe_mode=True).safe_mode is True
        finally:
            os.environ.pop("MRBOT_SAFE_MODE", None)
