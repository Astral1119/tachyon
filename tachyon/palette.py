"""Tachyon color language — themable, hot-swappable, one vocabulary everywhere.

Widgets read colors as module attributes (``palette.ACCENT``) so a theme
switch takes effect on the next render, and layout CSS reads them as
``$accent``-style variables served by ``TachyonApp.get_css_variables`` so a
switch plus ``refresh_css()`` restyles the chrome live.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Theme:
    name: str
    description: str
    bg: str  # screen ground
    panel_bg: str  # panel interiors
    chrome_bg: str  # header / hint rails
    term_bg: str  # terminal ground (Rich color, "default" = terminal's own)
    term_fg: str
    text: str
    dim: str
    accent: str  # live data signal
    accent_dim: str  # borders, labels, chrome
    hot: str  # alarm / emphasis
    warn: str  # elevated
    ok: str  # healthy
    chip: str  # foreground on accent-colored key chips
    ansi: bool = False  # render with the terminal's own palette (transparency)


THEMES: dict[str, Theme] = {
    "tron": Theme(
        name="tron",
        description="cyan signal on near-black void (default)",
        bg="#050a0e",
        panel_bg="#060d12",
        chrome_bg="#0a1419",
        term_bg="#04080b",
        term_fg="#a8d8e0",
        text="#a8d8e0",
        dim="#3c6470",
        accent="#18e0e8",
        accent_dim="#0b6e78",
        hot="#ff2e88",
        warn="#ffb454",
        ok="#39d353",
        chip="#050a0e",
    ),
    # Ghost's foregrounds are lifted from moonfly (bluz71/vim-moonfly-colors),
    # so it blends with a moonfly neovim setup in the same terminal.
    "ghost": Theme(
        name="ghost",
        description="transparent, moonfly colors — your terminal shows through",
        bg="transparent",
        panel_bg="transparent",
        chrome_bg="transparent",
        term_bg="default",
        term_fg="#c6c6c6",  # moonfly white
        text="#c6c6c6",
        dim="#808080",  # grey50
        accent="#adadf3",  # moonfly lavender — calmer than purple #ae81ff
        accent_dim="#373c4d",  # grey1 — moonfly's charcoal border
        hot="#ff5189",  # crimson
        warn="#e3c78a",  # yellow
        ok="#36c692",  # emerald
        chip="#080808",  # moonfly black
        ansi=True,
    ),
    # Community palettes, mapped onto the instrument vocabulary.
    "catppuccin": Theme(
        name="catppuccin",
        description="catppuccin mocha — soothing pastel mauve",
        bg="#11111b",  # crust
        panel_bg="#181825",  # mantle
        chrome_bg="#1e1e2e",  # base
        term_bg="#11111b",
        term_fg="#cdd6f4",  # text
        text="#cdd6f4",
        dim="#6c7086",  # overlay0
        accent="#cba6f7",  # mauve
        accent_dim="#585b70",  # surface2
        hot="#f38ba8",  # red
        warn="#f9e2af",  # yellow
        ok="#a6e3a1",  # green
        chip="#11111b",
    ),
    # Mapping principle for community palettes: borders and labels
    # (accent_dim) take the theme's *neutral* UI border color, not a
    # saturated tint — hue is reserved for accent/hot/warn/ok highlights,
    # matching how these themes actually look in editors.
    "tokyo-night": Theme(
        name="tokyo-night",
        description="tokyo night — calm blue over deep indigo",
        bg="#16161e",
        panel_bg="#1a1b26",
        chrome_bg="#292e42",  # bg_highlight
        term_bg="#16161e",
        term_fg="#c0caf5",
        text="#c0caf5",
        dim="#565f89",  # comment
        accent="#7aa2f7",  # blue
        accent_dim="#3b4261",  # fg_gutter — the subtle border blue-gray
        hot="#f7768e",
        warn="#e0af68",
        ok="#9ece6a",
        chip="#16161e",
    ),
    "gruvbox": Theme(
        name="gruvbox",
        description="gruvbox dark — warm grays, restrained color",
        bg="#1d2021",  # bg0_h
        panel_bg="#282828",  # bg0
        chrome_bg="#3c3836",  # bg1
        term_bg="#1d2021",
        term_fg="#ebdbb2",
        text="#ebdbb2",
        dim="#928374",  # gray
        accent="#83a598",  # blue — gruvbox's calm signal color
        accent_dim="#504945",  # bg2 — warm neutral borders
        hot="#fb4934",  # red
        warn="#fabd2f",  # yellow
        ok="#b8bb26",  # green
        chip="#1d2021",
    ),
}

_current: Theme = THEMES["tron"]


def theme() -> Theme:
    return _current


def set_theme(name: str) -> Theme:
    global _current
    _current = THEMES[name]
    return _current


def css_variables() -> dict[str, str]:
    """The current theme as $kebab-case CSS variables.

    Rich's "default" (terminal's own color) isn't a CSS value; it maps to
    "transparent" for stylesheet purposes.
    """
    out = {}
    for field in fields(Theme):
        if field.type == "str" and field.name not in ("name", "description"):
            value = getattr(_current, field.name)
            out[field.name.replace("_", "-")] = "transparent" if value == "default" else value
    return out


# Module attributes (palette.ACCENT and friends) resolve against the current
# theme at access time, so render() code stays hot-swappable.  Keep reading
# them as attributes — `from tachyon.palette import ACCENT` freezes the boot
# theme and must not be reintroduced.
_ATTRS = {
    "BG": "bg",
    "PANEL_BG": "panel_bg",
    "CHROME_BG": "chrome_bg",
    "TERM_BG": "term_bg",
    "TERM_FG": "term_fg",
    "TEXT": "text",
    "DIM": "dim",
    "ACCENT": "accent",
    "ACCENT_DIM": "accent_dim",
    "HOT": "hot",
    "WARN": "warn",
    "OK": "ok",
    "CHIP": "chip",
}


def __getattr__(name: str) -> str:
    try:
        return getattr(_current, _ATTRS[name])
    except KeyError:
        raise AttributeError(f"module 'tachyon.palette' has no attribute {name!r}") from None
