import os
from pathlib import Path
from dotenv import set_key


# v2.0.26: expanded token set. Each preset exposes a full palette so every UI
# region can use an EXPLICIT token (no color bleed). New keys derive from the
# legacy keys when a preset omits them, so old presets still load.
CUSTOM_THEME_KEYS = (
    "bg", "panel", "surface", "surface2", "fg", "muted", "accent", "highlight",
    "border", "shadow", "success", "warning", "error", "disabled", "radius",
)

# Preset theme names exposed in the UI (Theme menu + Settings combobox).
# "Custom" is handled specially by resolve_theme_definition() using MRBOT_THEME_*.
THEME_PRESETS = [
    "Dark", "Light", "Midnight-Blue", "Ocean", "Solar",
    "Forest", "Rose", "Lavender", "Neon-Cyberpunk", "Gradient-Mix",
]
CUSTOM_THEME_NAME = "Custom"

# Defaults used to fill any missing token so callers always get a complete dict.
_TOKEN_DEFAULTS = {
    "bg": "#121212", "panel": "#18181c", "surface": "#1f1f24", "surface2": "#26262c",
    "fg": "#e0e0e0", "muted": "#9aa0a6", "caption": "#c2c7cc", "accent": "#4fc3f7",
    "highlight": "#7c4dff",
    "border": "#33343a", "shadow": "rgba(0,0,0,0.45)", "success": "#22c55e",
    "warning": "#f59e0b", "error": "#ef4444", "disabled": "#6b7280", "radius": "6",
}


def _fill(theme: dict) -> dict:
    """Ensure every token is present and non-empty, deriving new ones from legacy keys."""
    t = dict(theme)
    for k, v in _TOKEN_DEFAULTS.items():
        # Treat empty/missing as absent so we always produce valid (non-empty) CSS.
        if not str(t.get(k, "")).strip():
            t[k] = v
    # Derive sensible surfaces if a preset only gave bg/panel.
    if not str(t.get("surface", "")).strip():
        t["surface"] = t.get("panel", _TOKEN_DEFAULTS["surface"])
    if not str(t.get("surface2", "")).strip():
        t["surface2"] = t.get("surface", _TOKEN_DEFAULTS["surface2"])
    if not str(t.get("border", "")).strip():
        t["border"] = t["accent"]
    if not str(t.get("muted", "")).strip():
        t["muted"] = t["disabled"]
    if not str(t.get("radius", "")).strip():
        t["radius"] = "6"
    if not str(t.get("shadow", "")).strip():
        t["shadow"] = "rgba(0,0,0,0.45)"
    if not str(t.get("success", "")).strip():
        t["success"] = "#22c55e"
    if not str(t.get("warning", "")).strip():
        t["warning"] = "#f59e0b"
    if not str(t.get("error", "")).strip():
        t["error"] = "#ef4444"
    t.setdefault("qss_extra", "")
    # caption: helper/instruction text — brighter than `muted` (which is too dim
    # for long notes) but softer than `fg`. Derived as a 55% lerp from muted→fg so
    # it stays readable on every theme without hand-tuning each preset.
    if not str(t.get("caption", "")).strip():
        t["caption"] = _lerp_color(t.get("muted", "#9aa0a6"), t.get("fg", "#e0e0e0"), 0.55)
    return t


def _lerp_color(a: str, b: str, t: float) -> str:
    """Linear-interpolate two #rrggbb colors; t=0 -> a, t=1 -> b."""
    def _hx(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return (0x99, 0xa0, 0xa6)
    ar, ag, ab = _hx(a)
    br, bg, bb = _hx(b)
    r = int(ar + (br - ar) * t)
    g = int(ag + (bg - ag) * t)
    b2 = int(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{b2:02x}"


def resolve_theme_definition(theme_name: str, env=None) -> dict:
    """Return a complete theme definition for a builtin preset or the custom theme."""
    env = os.environ if env is None else env
    if theme_name == "Custom":
        raw = {
            "bg": env.get("MRBOT_THEME_BG", _TOKEN_DEFAULTS["bg"]),
            "panel": env.get("MRBOT_THEME_PANEL", _TOKEN_DEFAULTS["panel"]),
            "surface": env.get("MRBOT_THEME_SURFACE", ""),
            "surface2": env.get("MRBOT_THEME_SURFACE2", ""),
            "fg": env.get("MRBOT_THEME_FG", _TOKEN_DEFAULTS["fg"]),
            "muted": env.get("MRBOT_THEME_MUTED", ""),
            "accent": env.get("MRBOT_THEME_ACCENT", _TOKEN_DEFAULTS["accent"]),
            "highlight": env.get("MRBOT_THEME_HIGHLIGHT", _TOKEN_DEFAULTS["highlight"]),
            "border": env.get("MRBOT_THEME_BORDER", ""),
            "shadow": env.get("MRBOT_THEME_SHADOW", _TOKEN_DEFAULTS["shadow"]),
            "success": env.get("MRBOT_THEME_SUCCESS", _TOKEN_DEFAULTS["success"]),
            "warning": env.get("MRBOT_THEME_WARNING", _TOKEN_DEFAULTS["warning"]),
            "error": env.get("MRBOT_THEME_ERROR", _TOKEN_DEFAULTS["error"]),
            "disabled": env.get("MRBOT_THEME_DISABLED", _TOKEN_DEFAULTS["disabled"]),
            "radius": env.get("MRBOT_THEME_RADIUS", _TOKEN_DEFAULTS["radius"]),
            "qss_extra": "",
        }
        return _fill(raw)

    defaults = {
        "Dark": {
            "bg": "#121212", "panel": "#18181c", "surface": "#1f1f24", "surface2": "#26262c",
            "fg": "#e0e0e0", "muted": "#9aa0a6", "accent": "#bb86fc", "highlight": "#03dac6",
            "border": "#33343a", "shadow": "rgba(0,0,0,0.45)", "success": "#22c55e",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#555", "radius": "6",
            "qss_extra": (
                "QProgressBar::chunk{background:qlineargradient("
                "x1:0,y1:0,x2:1,y2:0,stop:0 #bb86fc,stop:1 #03dac6);}"),
        },
        "Light": {
            "bg": "#f5f5f5", "panel": "#ffffff", "surface": "#eceff1", "surface2": "#e0e0e0",
            "fg": "#212121", "muted": "#616161", "accent": "#6200ee", "highlight": "#3700b3",
            "border": "#cfcfcf", "shadow": "rgba(0,0,0,0.18)", "success": "#2e7d32",
            "warning": "#ed6c02", "error": "#d32f2f", "disabled": "#aaaaaa", "radius": "6",
            "qss_extra": "",
        },
        "Midnight-Blue": {
            "bg": "#07111f", "panel": "#0c1728", "surface": "#10203a", "surface2": "#15294a",
            "fg": "#d7e8ff", "muted": "#8aa0bf", "accent": "#4fc3f7", "highlight": "#7c4dff",
            "border": "#1c3358", "shadow": "rgba(0,0,0,0.5)", "success": "#22c55e",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#5c6b7f", "radius": "6",
            "qss_extra": "QProgressBar::chunk{background:#4fc3f7;}",
        },
        "Ocean": {
            "bg": "#06272d", "panel": "#0a3b45", "surface": "#0d4753", "surface2": "#115663",
            "fg": "#b8f4ff", "muted": "#7fc4d0", "accent": "#24d1d1", "highlight": "#2bb4ff",
            "border": "#115663", "shadow": "rgba(0,0,0,0.45)", "success": "#22c55e",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#4f7a84", "radius": "6",
            "qss_extra": "QProgressBar::chunk{background:#2bb4ff;}",
        },
        "Solar": {
            "bg": "#2d1600", "panel": "#4a2500", "surface": "#5c2f00", "surface2": "#6e3900",
            "fg": "#ffe3b3", "muted": "#c79a5e", "accent": "#ff8c00", "highlight": "#ff5d44",
            "border": "#6e3900", "shadow": "rgba(0,0,0,0.5)", "success": "#7cb342",
            "warning": "#f59e0b", "error": "#ef5350", "disabled": "#8a6d3b", "radius": "6",
            "qss_extra": "QProgressBar::chunk{background:#ff8c00;}",
        },
        "Forest": {
            "bg": "#102214", "panel": "#18311f", "surface": "#1e3d27", "surface2": "#244a2f",
            "fg": "#dff6dd", "muted": "#90b894", "accent": "#38b000", "highlight": "#9ef01a",
            "border": "#244a2f", "shadow": "rgba(0,0,0,0.45)", "success": "#38b000",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#5b6f5d", "radius": "6",
            "qss_extra": "QProgressBar::chunk{background:#38b000;}",
        },
        "Rose": {
            "bg": "#221018", "panel": "#321827", "surface": "#3d1e30", "surface2": "#4a243b",
            "fg": "#ffe0eb", "muted": "#c79aab", "accent": "#f45b7a", "highlight": "#ff7f50",
            "border": "#4a243b", "shadow": "rgba(0,0,0,0.45)", "success": "#22c55e",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#7a5c67", "radius": "6",
            "qss_extra": "QProgressBar::chunk{background:#f45b7a;}",
        },
        "Lavender": {
            "bg": "#1d1730", "panel": "#2b2144", "surface": "#34285a", "surface2": "#3e2f6b",
            "fg": "#efe8ff", "muted": "#b3a8d6", "accent": "#9b87ff", "highlight": "#c084fc",
            "border": "#3e2f6b", "shadow": "rgba(0,0,0,0.45)", "success": "#22c55e",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#756d91", "radius": "6",
            "qss_extra": "QProgressBar::chunk{background:#9b87ff;}",
        },
        "Neon-Cyberpunk": {
            "bg": "#0d001a", "panel": "#1d0028", "surface": "#26003a", "surface2": "#33004d",
            "fg": "#00ffea", "muted": "#7afff0", "accent": "#ff00aa", "highlight": "#ffea00",
            "border": "#ff00aa", "shadow": "rgba(255,0,170,0.35)", "success": "#00ff88",
            "warning": "#ffd000", "error": "#ff2d55", "disabled": "#444", "radius": "6",
            "qss_extra": (
                "*{font-family:'Consolas',monospace;}"
                "QPushButton{border:1px solid #ff00aa;"
                "background:#1a0033;color:#00ffea;}"
                "QPushButton:hover{background:#ff00aa;color:black;}"
                "QProgressBar::chunk{background:#ff00aa;}"),
        },
        "Gradient-Mix": {
            "bg": "#1e0033", "panel": "#2b0a4a", "surface": "#34105c", "surface2": "#3e1470",
            "fg": "#d4a5ff", "muted": "#a878d6", "accent": "#ff6ec7", "highlight": "#00f2ff",
            "border": "#ff6ec7", "shadow": "rgba(0,0,0,0.5)", "success": "#22c55e",
            "warning": "#f59e0b", "error": "#ef4444", "disabled": "#663399", "radius": "6",
            "qss_extra": (
                "QWidget{background:qlineargradient("
                "x1:0,y1:0,x2:1,y2:1,stop:0 #1e0033,stop:1 #330066);}"
                "QLabel{color:#d4a5ff;}"
                "QProgressBar{background:#330066;border:1px solid #ff6ec7;}"
                "QProgressBar::chunk{background:qlineargradient("
                "x1:0,y1:0,x2:1,y2:0,stop:0 #ff6ec7,stop:1 #00f2ff);}"),
        },
    }
    theme = defaults.get(theme_name, defaults["Dark"])
    return _fill(theme)


def save_custom_theme(theme_values: dict, env=None, env_path: str | None = None) -> dict:
    """Persist custom theme colors to the environment and .env file."""
    env = os.environ if env is None else env
    project_root = Path(__file__).resolve().parent
    env_path = env_path or str(project_root / ".env")
    normalized = {}
    for key in CUSTOM_THEME_KEYS:
        fallback = _TOKEN_DEFAULTS.get(key, "#121212")
        value = str(theme_values.get(key, fallback)).strip()
        if not value:
            value = fallback
        normalized[key] = value
        env[f"MRBOT_THEME_{key.upper()}"] = value
        set_key(env_path, f"MRBOT_THEME_{key.upper()}", value)
    return normalized
