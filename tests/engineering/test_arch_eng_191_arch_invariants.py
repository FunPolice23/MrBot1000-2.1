"""ARCH-ENG-191/192/193 — architectural invariants that were never enforced.

ARCH-ENG-191 — `chat_router` could silently delete a whole prompt section.

    ranked_items = sorted(
        lifecycle[-5:],
        key=lambda item: (..., -(float(item.get("last_amount") or 0.0))))

`last_amount` is operator- and model-written, so `"N/A"`, `"pending"`, `"$250"`
and `""` are all reachable. Any of them raised ValueError inside `sorted(...)` --
and because a sort key is evaluated before ANY line is emitted, one bad row
discarded the ENTIRE Opportunity Status Report.

The display path twenty-five lines below already guarded with
`isinstance(amount, (int, float))`: the author knew the field may be non-numeric
and defended one of the two places it is read. This guards the other one.

Why it mattered in a module with no production callers: all three call sites sit
inside `try/except Exception: pass`, so the failure was not a crash but the
SILENT DISAPPEARANCE of the whole opportunity section from the chat prompt. A
persona that cannot see the board reasons about it anyway.

ARCH-ENG-192 — `app/` WAS NOT Qt-FREE, AND NOT BECAUSE IT USED Qt.

`app/ui.py` imported 39 PySide6 names at module level while declaring ZERO
classes and instantiating ZERO widgets. Every single import was unused; an AST
check confirmed all 39 are unreferenced. The module broke the documented rule
that `app/` is Qt-free so the service layer can be imported and tested headless,
for 39 names that served no purpose.

It was MISFILED rather than architecturally leaking: nothing outside the GUI
path imported it. One site did -- `main.py`'s `apply_theme`, wrapped in
`try/except` -- and it used only `set_ui_theme` and `set_effects`. So the fix is
a move plus a deletion with no behaviour change, and the module now lives at
`gui/theme_ui_state.py`.

It also carried a false claim. `UI_ANIMATIONS` has no readers anywhere in the
repository -- only its own definition and its own assignment -- yet its comment
asserted "the toggle now actually does something". The operator's Appearance >
Animations toggle does reach the renderer, but through
`app.effects.EffectSettings.animations`, not through this flag. The false comment
was removed; the flag is kept for API compatibility.

`app/effects.py` was audited alongside it and is ALREADY compliant: its four
PySide6 imports are function-local and guarded.

ARCH-ENG-193 — A CALL THAT COULD NOT SUCCEED, HIDDEN BY A BARE `except`.

    try:
        names = WorkerAgent._ollama_model_names_static()
        _add_unique(self.ollama_model_combo, names or [])
    except Exception:
        pass

`WorkerAgent._ollama_model_names_static` does not exist anywhere. The real name is
`_ollama_model_names(self)` -- an instance method doing a blocking
`requests.get(..., timeout=3)`. So this raised AttributeError on every
Settings-tab build, the bare `except` swallowed it, and the combo always fell
through to its hardcoded list.

It was not a typo to be "fixed". `populate_ollama_model_combos()` already does
this job on a background thread, and its docstring records why: "v1 fix: runs the
HTTP fetch on a background thread so the Settings tab never freezes when Ollama is
down". Correcting the name here would reintroduce that exact freeze. The dead
attempt is deleted with that warning attached.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _module_level_qt_imports(path: pathlib.Path):
    """PySide6 imports at MODULE level only (function-local ones are fine)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:                      # module scope, deliberately
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if "PySide6" in a.name]
        elif isinstance(node, ast.ImportFrom):
            if node.module and "PySide6" in node.module:
                found.append(node.module)
    return found


# ── ARCH-ENG-192: app/ is Qt-free ─────────────────────────────────────────────

class TestAppLayerIsQtFree(unittest.TestCase):
    """ARCH-ENG-192 — the rule the architecture map documents."""

    def test_no_module_in_app_imports_pyside6(self):
        offenders = {}
        for path in sorted((REPO / "app").glob("*.py")):
            found = _module_level_qt_imports(path)
            if found:
                offenders[path.name] = found
        self.assertEqual(
            offenders, {},
            f"module-level PySide6 imports in the service layer: {offenders}. "
            f"`app/` must be importable and testable headless.")

    def test_app_effects_stays_compliant(self):
        """Its Qt imports are function-local and guarded -- verify that holds."""
        src = (REPO / "app" / "effects.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in tree.body:
            self.assertFalse(
                isinstance(node, (ast.Import, ast.ImportFrom))
                and "PySide6" in ast.dump(node),
                "app/effects.py gained a module-level Qt import; its Qt use is "
                "deliberately lazy")

    def test_the_old_module_path_is_gone(self):
        self.assertFalse(
            (REPO / "app" / "ui.py").exists(),
            "app/ui.py is back; it is misfiled GUI state, not service-layer code")

    def test_the_relocated_module_exists_and_is_qt_free(self):
        target = REPO / "gui" / "theme_ui_state.py"
        self.assertTrue(target.exists(), "the relocated module is missing")
        self.assertEqual(_module_level_qt_imports(target), [])

    def test_the_relocated_module_still_works(self):
        """A move must not lose the two functions main.py calls."""
        from gui import theme_ui_state
        theme_ui_state.UI_THEME = {}
        theme_ui_state.set_ui_theme({"bg": "#101010"})
        self.assertEqual(theme_ui_state.TH("bg"), "#101010")
        self.assertEqual(theme_ui_state.TH("nope"), "#888888")
        theme_ui_state.set_effects(animations=False)
        self.assertFalse(theme_ui_state.UI_ANIMATIONS)
        theme_ui_state.set_effects(animations=True)

    def test_nothing_imports_the_old_path_anymore(self):
        """A stale `from app import ui` would fail only at GUI startup."""
        offenders = []
        for path in REPO.rglob("*.py"):
            if any(s in path.parts for s in
                   (".venv", "__pycache__", ".git", ".mrbot_backups",
                    "code_patch_backups", "tests")):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue          # the historical note is fine
                if re.search(r"\bfrom\s+app\s+import\s+ui\b", line) or \
                        re.search(r"\bapp\.ui\b", line):
                    offenders.append(f"{path.relative_to(REPO)}:{i}")
        self.assertEqual(offenders, [],
                         f"stale references to the relocated module: {offenders}")

    def test_the_false_animations_claim_is_not_repeated(self):
        """It claimed the toggle gated the UI; it never has."""
        src = (REPO / "gui" / "theme_ui_state.py").read_text(encoding="utf-8")
        self.assertNotIn("the toggle now actually does something", src,
                         "the false claim about UI_ANIMATIONS is back")
