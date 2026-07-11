"""Leader-key command deck: a which-key chord strip over the live interface."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static

from tachyon import palette

# (chord, label, app action) — single keys pressed after the leader.
CHORDS: tuple[tuple[str, str, str], ...] = (
    ("s", "SHELL", "focus_terminal"),
    ("f", "FILES", "focus_files"),
    ("c", "CD HERE", "cd_selected"),
    ("r", "RESPAWN", "respawn"),
    ("t", "HOLD", "toggle_telemetry"),
    (".", "DOTFILES", "toggle_hidden"),
    ("k", "MATRIX", "toggle_keys"),
    ("g", "GLOBE", "toggle_globe"),
    ("y", "THEME", "theme_deck"),
    ("z", "FOCUS", "zen"),
    ("o", "SENSORS", "overview"),
    ("?", "INDEX", "operator_index"),
    ("q", "EXIT", "quit"),
)

# Keys the deck's own priority bindings own; on_key must leave them alone.
_STAND_DOWN_KEYS = frozenset(("escape", "ctrl+space", "ctrl+at"))


class CommandDeck(ModalScreen[None]):
    """Chord listener opened by the leader key.

    The deck is a bottom strip over the live, undimmed interface — you can
    see where you're going — and stays armed indefinitely.  The next
    keypress resolves to a control action; a chord typed with CTRL still
    held (the tmux habit) counts as the plain chord; an unrecognised key
    names the miss and stays armed.  ESC or the leader again stands down.
    """

    BINDINGS = [
        Binding("escape", "stand_down", "cancel", show=False, priority=True),
        Binding("ctrl+space", "stand_down", "cancel", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    CommandDeck {
        background: transparent;
    }
    CommandDeck #deck-strip {
        dock: bottom;
        width: 100%;
        height: auto;
        padding: 0 2 1 2;
        border-top: heavy $accent-dim;
        background: $panel-bg;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._miss: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._render_strip(), id="deck-strip")

    def _render_strip(self) -> Text:
        out = Text(no_wrap=True, overflow="crop")
        out.append("◢ COMMAND DECK ◣", style=f"bold {palette.HOT}")
        if self._miss is None:
            out.append("  awaiting chord — ESC stands down\n\n", style=palette.DIM)
        else:
            out.append(f"  no chord bound to {self._miss} — still armed\n\n", style=palette.HOT)

        for index, (key, label, _action) in enumerate(CHORDS):
            if index and index % 5 == 0:
                out.append("\n")
            out.append(f" {key} ", style=f"bold {palette.CHIP} on {palette.ACCENT}")
            out.append(f" {label:<12}", style=palette.TEXT)
        out.append("\n\n")

        panels = getattr(self.app, "PANEL_REGISTRY", ())[:10]
        for number, (_panel_id, name) in enumerate(panels, start=1):
            out.append(f" {number % 10} ", style=f"bold {palette.TEXT} on {palette.ACCENT_DIM}")
            out.append(" MAGNIFY ", style=palette.DIM)
            out.append(f"{name:<12}", style=palette.TEXT)
            if number % 3 == 0:
                out.append("\n")
        return out

    def _dispatch(self, action: str, *args: object) -> None:
        method = getattr(self.app, f"action_{action}", None)
        self.dismiss()
        if method is not None:
            self.app.call_after_refresh(method, *args)

    def _mark_miss(self, key: str) -> None:
        self._miss = key.upper()
        self.query_one("#deck-strip", Static).update(self._render_strip())

    def on_key(self, event: events.Key) -> None:
        if event.key in _STAND_DOWN_KEYS:
            return  # priority bindings stand the deck down
        event.stop()
        event.prevent_default()

        character = event.character
        if (
            (character is None or not character.isprintable())
            and event.key.startswith("ctrl+")
            and len(event.key) == 6
        ):
            # tmux muscle memory: the chord arrives with CTRL still held.
            character = event.key[5]
        if character is not None:
            character = character.lower()

        if character is not None and character.isdigit():
            index = 10 if character == "0" else int(character)
            if index <= len(getattr(self.app, "PANEL_REGISTRY", ())):
                self._dispatch("magnify", index)
            else:
                self._mark_miss(character)
            return
        for key, _label, action in CHORDS:
            if character == key:
                self._dispatch(action)
                return
        self._mark_miss(event.key)

    def action_stand_down(self) -> None:
        self.dismiss()


class ThemeDeck(ModalScreen[None]):
    """Palette picker: a digit applies a theme live, ESC stands down."""

    BINDINGS = [
        Binding("escape", "stand_down", "cancel", show=False, priority=True),
        Binding("ctrl+space", "stand_down", "cancel", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ThemeDeck {
        background: transparent;
    }
    ThemeDeck #theme-strip {
        dock: bottom;
        width: 100%;
        height: auto;
        padding: 0 2 1 2;
        border-top: heavy $accent-dim;
        background: $panel-bg;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(self._render_strip(), id="theme-strip")

    def _render_strip(self) -> Text:
        out = Text(no_wrap=True, overflow="crop")
        out.append("◢ THEME DECK ◣", style=f"bold {palette.HOT}")
        out.append("  pick a palette — ESC stands down\n\n", style=palette.DIM)
        current = palette.theme().name
        for number, name in enumerate(palette.THEMES, start=1):
            entry = palette.THEMES[name]
            out.append(f" {number} ", style=f"bold {palette.CHIP} on {palette.ACCENT}")
            marker = "▶" if name == current else " "
            out.append(f" {marker} ", style=palette.ACCENT)
            out.append(f"{name.upper():<10}", style=f"bold {palette.TEXT}")
            for swatch in (entry.accent, entry.hot, entry.ok, entry.warn):
                out.append("██", style=swatch)
            out.append(f"  {entry.description}\n", style=palette.DIM)
        return out

    def on_key(self, event: events.Key) -> None:
        if event.key in _STAND_DOWN_KEYS:
            return
        event.stop()
        event.prevent_default()
        character = event.character
        if character and character.isdigit():
            index = int(character)
            names = list(palette.THEMES)
            if 1 <= index <= len(names):
                name = names[index - 1]
                self.dismiss()
                self.app.call_after_refresh(
                    getattr(self.app, "action_set_theme", lambda _n: None), name
                )
                return
        self.dismiss()

    def action_stand_down(self) -> None:
        self.dismiss()
