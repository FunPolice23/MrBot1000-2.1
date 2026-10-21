"""Theme token state for widget-level styling.

Moved from ``app/ui.py`` in ARCH-ENG-192.

That file imported 39 PySide6 names at module level -- 28 of them Qt widget,
painter and geometry classes -- while declaring ZERO classes and instantiating
ZERO widgets. Every single import was unused. It broke the documented rule that
``app/`` is Qt-free so the service layer can be imported and tested headless, and
it did so for 39 names that served no purpose at all.

It was also misfiled rather than architecturally leaking: nothing outside the GUI
path imported it. Exactly one site did, ``main.py``'s ``apply_theme``, wrapped in
``try/except Exception``, and it used only ``set_ui_theme`` and ``set_effects``.

So the fix is a move plus a deletion, with no behaviour change.

``app/effects.py`` was audited alongside this file and is ALREADY compliant: its
four PySide6 imports are all function-local and guarded. They stay.

What remains here is pure module state and four small functions, with no Qt
dependency of any kind.
"""

# ARCH-ENG-192: every import that used to be here was UNUSED. The module
# declared no classes and instantiated no widgets, so the 39 PySide6 names were
# dead weight that made `import app.ui` fail on any machine without Qt installed
# -- which is the opposite of what a file in the service layer is for.
#
# Nothing here needs `from __future__ import annotations` either: the surviving
# definitions use no annotations.

# v2.0.27: theme color tokens for widget-level HTML/CSS styling (Phase E).
# main.apply_theme() calls set_ui_theme() so chat colors follow the active theme.
UI_THEME = {}
# Registry of (widget, restyle_fn) so a theme switch re-colors every widget
# whose inline stylesheet was built from TH() tokens. Without this, widgets
# styled once at creation keep their old colors when the theme changes.
UI_THEMEABLE = []


def ui_style(widget, restyle_fn):
    """Apply a TH()-token stylesheet AND register it for live re-styling.

    restyle_fn() must re-issue the widget's setStyleSheet(f"...{TH('x')}...")
    so that, when UI_THEME changes, replaying it picks up the new tokens.

    ARCH-ENG-192: NO CALL SITES, anywhere in the repository. Consequently
    `UI_THEMEABLE` is always empty and `restyle_ui()` is always a no-op -- the
    live re-styling this module documents cannot happen, because nothing ever
    registers. The mechanism is kept because it is a public helper and a
    complete fix belongs with whoever owns widget styling, but the absence of
    callers is recorded here rather than left for the next reader to assume is a
    bug in the theme switch.
    """
    try:
        restyle_fn()
        UI_THEMEABLE.append((widget, restyle_fn))
    except Exception:
        pass


def restyle_ui():
    """Re-apply every registered tokenized stylesheet (call on theme change)."""
    for widget, restyle_fn in UI_THEMEABLE:
        try:
            restyle_fn()
        except Exception:
            pass


def set_ui_theme(theme: dict):
    global UI_THEME
    UI_THEME = theme or {}
    # Re-color all previously-styled tokenized widgets live.
    restyle_ui()


# v2.0.34ap (H67): master switch for sprite/particle animations, driven by the
# Appearance > "Animations" toggle.
#
# ARCH-ENG-192: THE COMMENT HERE USED TO CLAIM "the toggle now actually does
# something". IT DOES NOT, and never has since this flag was introduced.
# `UI_ANIMATIONS` has NO READERS: the only two references in the repository are
# its own assignment here and its own definition. Setting it to False changes
# nothing observable.
#
# The real animations path is `app/effects.py`: `EffectSettings.animations`
# (MRBOT_FX_ANIMATIONS) IS consumed, and `main.py` already applies it separately.
# So the operator's Appearance > Animations toggle does reach the renderer -- it
# simply does so through `effects`, and this flag is a dead parallel copy.
#
# The flag is kept because `set_effects` is called by `main.py` and is public API.
# What was removed is the false claim.
UI_ANIMATIONS = True


def set_effects(*, animations: bool = True):
    """Record the animation preference for ui.py's own drawing.

    ARCH-ENG-192: see the note on `UI_ANIMATIONS` -- nothing reads it. The
    effective switch is `app.effects.EffectSettings.animations`.
    """
    global UI_ANIMATIONS
    UI_ANIMATIONS = bool(animations)


def TH(key: str, fallback: str = "#888888") -> str:
    """Look up a theme token, falling back to a neutral grey."""
    return str(UI_THEME.get(key, fallback))
