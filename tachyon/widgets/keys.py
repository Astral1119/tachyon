"""Input matrix: an eDEX-style keyboard that lights up as the operator types."""

from __future__ import annotations

from collections import deque
from time import monotonic

from rich.text import Text
from textual.widgets import Static

from tachyon import palette
from tachyon.widgets.resize import EdgeResize

_LIT_SECONDS = 0.45

# Rows of (display label, token) — tokens are what tap() lights up.
_ROWS: tuple[tuple[tuple[str, str], ...], ...] = (
    (
        ("⎋", "esc"),
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
        ("6", "6"),
        ("7", "7"),
        ("8", "8"),
        ("9", "9"),
        ("0", "0"),
        ("-", "-"),
        ("=", "="),
        ("⌫", "bsp"),
    ),
    (
        ("⇥", "tab"),
        ("q", "q"),
        ("w", "w"),
        ("e", "e"),
        ("r", "r"),
        ("t", "t"),
        ("y", "y"),
        ("u", "u"),
        ("i", "i"),
        ("o", "o"),
        ("p", "p"),
        ("[", "["),
        ("]", "]"),
        ("\\", "\\"),
    ),
    (
        ("⌃", "ctl"),
        ("a", "a"),
        ("s", "s"),
        ("d", "d"),
        ("f", "f"),
        ("g", "g"),
        ("h", "h"),
        ("j", "j"),
        ("k", "k"),
        ("l", "l"),
        (";", ";"),
        ("'", "'"),
        ("⏎", "ret"),
    ),
    (
        ("⇧", "sft"),
        ("z", "z"),
        ("x", "x"),
        ("c", "c"),
        ("v", "v"),
        ("b", "b"),
        ("n", "n"),
        ("m", "m"),
        (",", ","),
        (".", "."),
        ("/", "/"),
        ("⇧", "sft"),
    ),
    (
        ("␣ SPACE ␣", "space"),
        ("◁", "left"),
        ("▽", "down"),
        ("△", "up"),
        ("▷", "right"),
    ),
)

_SPECIAL_KEYS = {
    "enter": ("ret",),
    "backspace": ("bsp",),
    "delete": ("bsp",),
    "escape": ("esc",),
    "tab": ("tab",),
    "shift+tab": ("sft", "tab"),
    "space": ("space",),
    "left": ("left",),
    "right": ("right",),
    "up": ("up",),
    "down": ("down",),
}

# Shifted symbol → (base key it lives on).
_UNSHIFT = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
}


def tokens_for(key: str, character: str | None) -> tuple[str, ...]:
    """Map a Textual key event to the layout tokens it should light."""
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    if key.startswith("ctrl+"):
        rest = key[5:]
        return ("ctl", rest) if len(rest) == 1 else ("ctl",)
    if character:
        if character == " ":
            return ("space",)
        if character in _UNSHIFT:
            return ("sft", _UNSHIFT[character])
        if character.isupper():
            return ("sft", character.lower())
        if character.isprintable():
            return (character,)
    return ()


class KeysPanel(EdgeResize, Static):
    """Live keyboard telemetry for the embedded shell."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lit: dict[str, float] = {}
        self._taps: deque[float] = deque(maxlen=400)

    def on_mount(self) -> None:
        self.border_title = "◢ INPUT MATRIX ◣"
        self.border_subtitle = "0 KPM"
        self.set_interval(0.15, self._tick)

    def tap(self, key: str, character: str | None) -> None:
        now = monotonic()
        lit = tokens_for(key, character)
        if not lit:
            return
        for token in lit:
            self._lit[token] = now + _LIT_SECONDS
        self._taps.append(now)
        self.border_subtitle = f"{self._rate(now)} KPM"
        self.refresh()

    def _rate(self, now: float) -> int:
        return sum(1 for stamp in self._taps if now - stamp <= 60.0)

    def _tick(self) -> None:
        if not self._lit:
            return
        now = monotonic()
        self._lit = {token: deadline for token, deadline in self._lit.items() if deadline > now}
        self.border_subtitle = f"{self._rate(now)} KPM"
        self.refresh()

    def render(self) -> Text:
        now = monotonic()
        width = max(self.content_size.width, 20)
        out = Text(no_wrap=True, overflow="crop")
        for index, row in enumerate(_ROWS):
            if index:
                out.append("\n")
            line = Text(no_wrap=True)
            for label, token in row:
                hot = self._lit.get(token, 0.0) > now
                style = f"bold {palette.CHIP} on {palette.ACCENT}" if hot else palette.DIM
                line.append(f" {label} ", style=style)
                line.append(" ")
            pad = max((width - line.cell_len) // 2, 0)
            out.append(" " * pad)
            out.append(line)
        return out


__all__ = ["KeysPanel", "tokens_for"]
