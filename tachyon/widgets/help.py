"""Operator index overlay for Tachyon's reserved controls."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from tachyon import palette


def _key_line(key: str, label: str, detail: str) -> Text:
    line = Text()
    line.append(f" {key:^12} ", style=f"bold {palette.TEXT} on {palette.ACCENT_DIM}")
    line.append(f"  {label:<15}", style=f"bold {palette.ACCENT}")
    line.append(detail, style=palette.TEXT)
    return line


class OperatorIndex(ModalScreen[None]):
    """Compact, scrollable help without enabling Textual's command palette."""

    BINDINGS = [
        Binding("escape", "close", "close", show=False, priority=True),
        Binding("f1", "close", "close", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    OperatorIndex {
        background: $bg 82%;
        align: center middle;
    }
    OperatorIndex #operator-index {
        width: 82;
        max-width: 94%;
        height: 44;
        max-height: 92%;
        padding: 1 2;
        border: round $accent;
        border-title-color: $hot;
        border-title-style: bold;
        border-subtitle-color: $accent-dim;
        background: $panel-bg;
        scrollbar-size-vertical: 1;
        scrollbar-color: $accent-dim;
        scrollbar-background: $panel-bg;
    }
    OperatorIndex .index-heading {
        height: 2;
        color: $hot;
        text-style: bold;
    }
    OperatorIndex .index-section {
        height: 2;
        padding-top: 1;
        color: $accent-dim;
        text-style: bold;
    }
    OperatorIndex .index-line { height: 1; }
    OperatorIndex #index-note {
        height: 3;
        padding-top: 1;
        color: $dim;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="operator-index") as index:
            index.border_title = "◢ OPERATOR INDEX ◣"
            index.border_subtitle = "F1 / ESC CLOSE"
            yield Static("TACHYON // SHELL CONTROL SURFACE", classes="index-heading")
            yield Static("COMMAND DECK — CTRL+SPACE, THEN A CHORD", classes="index-section")
            for key, label, detail in (
                ("^SPC s", "SHELL", "focus the live PTY session"),
                ("^SPC f", "FILES", "focus the filesystem lattice"),
                ("^SPC c", "CD HERE", "move the shell to the selected path"),
                ("^SPC r", "RESPAWN", "replace the current shell session"),
                ("^SPC t", "HOLD", "freeze / resume peripheral sampling"),
                ("^SPC .", "DOTFILES", "show / hide filesystem dotfiles"),
                ("^SPC k", "MATRIX", "show / hide the input matrix keyboard"),
                ("^SPC g", "GLOBE", "uplink grid: rotating orbit / flat chart"),
                ("^SPC y", "THEME", "open the theme deck (live palette swap)"),
                ("^SPC z", "FOCUS", "toggle a shell-only workspace"),
                ("^SPC o", "SENSORS", "toggle the expanded telemetry deck"),
                ("^SPC 1-9,0", "MAGNIFY", "fill the deck with a numbered panel"),
                ("^SPC ?", "INDEX", "open this operator index"),
                ("^SPC q", "EXIT", "shut down Tachyon"),
                ("ESC", "STAND DOWN", "restore the deck / return to the shell"),
            ):
                yield Static(_key_line(key, label, detail), classes="index-line")

            yield Static("GLOBAL MATRIX — FUNCTION-KEY ALIASES", classes="index-section")
            for key, label, detail in (
                ("F2", "SHELL", "alias of ^SPC s"),
                ("F3", "FILES", "alias of ^SPC f"),
                ("F4", "CD HERE", "alias of ^SPC c"),
                ("F5", "RESPAWN", "alias of ^SPC r"),
                ("F6", "HOLD", "alias of ^SPC t"),
                ("F7", "DOTFILES", "alias of ^SPC ."),
                ("F8", "SENSORS", "alias of ^SPC o"),
                ("F9", "FOCUS", "alias of ^SPC z"),
                ("F10", "EXIT", "alias of ^SPC q"),
            ):
                yield Static(_key_line(key, label, detail), classes="index-line")

            yield Static("FILESYSTEM LATTICE — VIM MOTIONS", classes="index-section")
            for key, label, detail in (
                ("j / k", "TRAVERSE", "cursor down / up"),
                ("h", "FOLD", "collapse / parent; at the root, re-root up"),
                ("l", "UNFOLD", "expand a directory, or select a file"),
                ("g / G", "WARP", "jump to the top / bottom of the tree"),
                (".", "DOTFILES", "show / hide dotfiles"),
                ("ENTER", "SELECT", "target the highlighted path"),
                ("⌁SH", "SHELL LINK", "the tree re-roots wherever the shell cd's"),
            ):
                yield Static(_key_line(key, label, detail), classes="index-line")

            yield Static("TERMINAL MEMORY", classes="index-section")
            for key, label, detail in (
                ("⌘K", "CLEAR", "wipe scrollback, repaint prompt (also ⌃⇧K)"),
                ("SHIFT+PGUP", "HISTORY", "move back through bounded scrollback"),
                ("SHIFT+PGDN", "HISTORY", "move toward the live tail"),
                ("CTRL+SHIFT+HOME", "OLDEST", "jump to the oldest retained page"),
                ("CTRL+SHIFT+END", "LIVE", "return to the live tail"),
            ):
                yield Static(_key_line(key, label, detail), classes="index-line")

            yield Static(
                "CTRL+SPACE arms the command deck; the next key is a chord (holding "
                "CTRL through the chord also works). Function keys remain as aliases. "
                "Drag any panel border with the mouse to resize the grid. All other "
                "keys, paste data, and control characters reach the embedded shell.",
                id="index-note",
            )

    def action_close(self) -> None:
        self.dismiss()
