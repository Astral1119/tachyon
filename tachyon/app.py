"""Tachyon application shell: layout, controls, and theme wiring."""

from __future__ import annotations

import getpass
import os
import socket
from contextlib import suppress
from datetime import datetime
from pathlib import Path

import psutil
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Static

from tachyon import palette
from tachyon.config import TachyonConfig, parse_config
from tachyon.widgets.boot import BootScreen
from tachyon.widgets.deck import CommandDeck, ThemeDeck
from tachyon.widgets.files import FileBrowser
from tachyon.widgets.globe import GlobePanel
from tachyon.widgets.help import OperatorIndex
from tachyon.widgets.keys import KeysPanel
from tachyon.widgets.monitors import CpuPanel, MemPanel, ProcessPanel, SystemPanel
from tachyon.widgets.network import ConnectionsPanel, DiskPanel, NetPanel
from tachyon.widgets.repo import RepoPanel
from tachyon.widgets.term import Terminal


def _short_path(path: Path | str, limit: int = 44) -> str:
    shown = str(path)
    home = str(Path.home())
    if shown == home or shown.startswith(home + os.sep):
        shown = "~" + shown[len(home) :]
    if len(shown) > limit:
        shown = "…" + shown[-(limit - 1) :]
    return shown


class TachyonHeader(Static):
    """Top status rail with a width-aware identity and clock block."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        host = socket.gethostname().removesuffix(".local")
        self._identity = f"{getpass.getuser()}@{host}"
        self._boot_time = datetime.fromtimestamp(psutil.boot_time())
        self._cwd: Path | None = None

    def set_cwd(self, path: Path) -> None:
        self._cwd = path
        self.refresh()

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh)

    def render(self) -> Text:
        now = datetime.now()
        width = max(self.size.width, 1)

        left = Text()
        left.append(" ⬢ TACHYON ", style=f"bold {palette.HOT}")
        if width >= 42:
            left.append("// ", style=palette.ACCENT_DIM)
            left.append(self._identity, style=palette.ACCENT)

        right = Text()
        if width >= 76:
            uptime = max(int((now - self._boot_time).total_seconds()), 0)
            days, rem = divmod(uptime, 86400)
            hours, rem = divmod(rem, 3600)
            minutes = rem // 60
            right.append(f"UP {days}d {hours:02}:{minutes:02}", style=palette.ACCENT_DIM)

        if width >= 112:
            battery = psutil.sensors_battery()
            if battery is not None:
                right.append("  ▞▚▞  ", style=palette.ACCENT_DIM)
                plug = "⚡" if battery.power_plugged else "▷"
                low_battery = battery.percent < 20 and not battery.power_plugged
                color = palette.HOT if low_battery else palette.ACCENT
                right.append(f"{plug} {battery.percent:.0f}%", style=color)

        if width >= 58:
            right.append("  ▞▚▞  " if right else "", style=palette.ACCENT_DIM)
            right.append(now.strftime("%Y-%m-%d"), style=palette.TEXT)
            right.append("  ")
        right.append(now.strftime("%H:%M:%S"), style=f"bold {palette.ACCENT}")
        right.append(" ")

        available = max(width - right.cell_len - 1, 0)
        left.truncate(available, overflow="ellipsis")

        # The shell's working directory rides in the otherwise-empty middle.
        middle = Text()
        if self._cwd is not None and width >= 88:
            middle.append("⌁ ", style=palette.ACCENT_DIM)
            middle.append(_short_path(self._cwd, limit=36), style=palette.DIM)
        gap = width - left.cell_len - right.cell_len
        if middle.cell_len and middle.cell_len + 4 <= gap:
            lead = max((width - middle.cell_len) // 2 - left.cell_len, 2)
            lead = min(lead, gap - middle.cell_len - 2)
            left.append(" " * lead)
            left.append(middle)

        pad = max(width - left.cell_len - right.cell_len, 0)
        left.append(" " * pad)
        left.append(right)
        left.truncate(width)
        return left


class HintBar(Static):
    """Quiet status rail: current state (with its exit chord) and flashes.

    Deliberately not a keybinding guide — the command deck (ctrl+space) and
    operator index carry that. Modes advertise their own way back.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._message = ""
        self._message_style = palette.ACCENT
        self._clear_timer: Timer | None = None

    def flash(self, message: str, *, style: str = palette.ACCENT, duration: float = 2.5) -> None:
        self._message = message
        self._message_style = style
        if self._clear_timer is not None:
            self._clear_timer.stop()
        self._clear_timer = self.set_timer(duration, self._clear_message)
        self.refresh()

    def _clear_message(self) -> None:
        self._message = ""
        self._clear_timer = None
        self.refresh()

    def _state(self) -> tuple[str, str]:
        app = self.app
        if getattr(app, "telemetry_paused", False):
            return "Ⅱ TELEMETRY HOLD · ^␣ t RESUMES", palette.WARN
        if getattr(app, "magnified", None) is not None:
            return "◇ MAGNIFIED · ESC RESTORES", palette.ACCENT
        if getattr(app, "overview", False):
            return "◇ SENSOR DECK · ESC RESTORES", palette.ACCENT
        if getattr(app, "files_only", False):
            return "◇ FILE DECK · ESC RESTORES", palette.ACCENT
        if getattr(app, "zen", False):
            return "◇ SHELL FOCUS · ^␣ z RESTORES", palette.HOT
        mode = getattr(app, "layout_mode", "full")
        if mode != "full":
            return f"● LIVE / {mode.upper()}", palette.OK
        return "● SYSTEM LIVE", palette.OK

    def render(self) -> Text:
        width = max(self.size.width, 1)
        status, status_style = (
            (self._message, self._message_style) if self._message else self._state()
        )
        out = Text(no_wrap=True, overflow="ellipsis")
        out.append(f" {status}", style=f"bold {status_style}")
        out.truncate(width, overflow="ellipsis")
        return out


class TachyonApp(App):
    TITLE = "TACHYON"
    CSS_PATH = "theme.tcss"
    ENABLE_COMMAND_PALETTE = False

    # The deck number and display name of every instrument, in leader-chord
    # order. Index 1 is the shell, 2 the filesystem; the rest are telemetry.
    PANEL_REGISTRY: tuple[tuple[str, str], ...] = (
        ("term", "MAIN SHELL"),
        ("panel-files", "FILESYSTEM"),
        ("panel-system", "SYSTEM"),
        ("panel-cpu", "CPU CORES"),
        ("panel-mem", "MEMORY"),
        ("panel-proc", "PROCESSES"),
        ("panel-net", "NETWORK"),
        ("panel-conn", "CONNTRACK"),
        ("panel-disk", "DISK ARRAY"),
        ("panel-globe", "UPLINK GRID"),
    )

    # These keys are intentionally reserved by the control surface and must
    # win over the embedded terminal's own function-key translation.  The
    # function keys are aliases; the leader chord is the primary surface.
    BINDINGS = [
        Binding("ctrl+space", "leader", "command deck", show=False, priority=True),
        Binding("escape", "stand_down", "restore deck", show=False),
        # cmd+K arrives as super+k from kitty-protocol terminals (ghostty,
        # kitty, iTerm with CSI u); ctrl+shift+k is the everywhere fallback.
        Binding("super+k,ctrl+shift+k", "clear_shell", "clear buffer", show=False, priority=True),
        # cmd+/ (super+slash) opens the index on kitty-protocol terminals.
        Binding("f1,super+slash", "operator_index", "index", show=False, priority=True),
        Binding("f2", "focus_terminal", "terminal", show=False, priority=True),
        Binding("f3", "focus_files", "files", show=False, priority=True),
        Binding("f4", "cd_selected", "cd here", show=False, priority=True),
        Binding("f5", "respawn", "respawn shell", show=False, priority=True),
        Binding("f6", "toggle_telemetry", "hold telemetry", show=False, priority=True),
        Binding("f7", "toggle_hidden", "dotfiles", show=False, priority=True),
        Binding("f8", "overview", "sensor deck", show=False, priority=True),
        Binding("f9", "zen", "focus mode", show=False, priority=True),
        Binding("f10", "quit", "exit", show=False, priority=True),
        Binding("ctrl+c", "sigint", show=False, priority=True),
        Binding("ctrl+q", "quit", show=False, priority=True),
    ]

    def __init__(self, *args, config: TachyonConfig | None = None, **kwargs) -> None:
        self.config = config or TachyonConfig()
        starting_theme = palette.set_theme(self.config.theme)
        kwargs.setdefault("ansi_color", starting_theme.ansi)
        super().__init__(*args, **kwargs)
        self.telemetry_paused = False
        self.layout_mode = "full"
        self.layout_short = False
        self.zen = False
        self.overview = False
        self.files_only = False
        self.keys_visible = False
        self.magnified: str | None = None

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **palette.css_variables()}

    @property
    def telemetry_active(self) -> bool:
        if self.telemetry_paused:
            return False
        if self.overview or self.magnified is not None:
            return True
        return not (self.zen or self.files_only or self.layout_mode == "compact")

    def compose(self) -> ComposeResult:
        yield TachyonHeader(id="header")
        with Horizontal(id="body"):
            with Vertical(id="col-left"):
                yield SystemPanel(id="panel-system", classes="panel telemetry")
                yield CpuPanel(id="panel-cpu", classes="panel telemetry")
                yield MemPanel(id="panel-mem", classes="panel telemetry")
                yield ProcessPanel(id="panel-proc", classes="panel telemetry")
            with Vertical(id="col-center"):
                yield Terminal(
                    id="term",
                    cwd=self.config.shell_cwd,
                    history_lines=self.config.history_lines,
                )
                yield KeysPanel(id="panel-keys", classes="panel")
                with Horizontal(id="center-bottom"):
                    yield FileBrowser(
                        root=self.config.filesystem_root,
                        id="panel-files",
                        classes="panel",
                    )
                    yield RepoPanel(id="panel-repo", classes="panel")
            with Vertical(id="col-right"):
                yield GlobePanel(id="panel-globe", classes="panel telemetry")
                yield NetPanel(id="panel-net", classes="panel telemetry")
                yield ConnectionsPanel(id="panel-conn", classes="panel telemetry")
                yield DiskPanel(id="panel-disk", classes="panel telemetry")
        yield HintBar(id="hints")

    def on_mount(self) -> None:
        term = self.query_one(Terminal)
        self._apply_layout(self.size.width, self.size.height)
        self.call_after_refresh(self._stamp_panel_titles)
        self.query_one(RepoPanel).set_target(self.config.shell_cwd)
        if self.config.boot_enabled:
            self.push_screen(BootScreen())
        term.focus()

    def _stamp_panel_titles(self) -> None:
        for number, (panel_id, name) in enumerate(self.PANEL_REGISTRY, start=1):
            with suppress(NoMatches):
                self.query_one(f"#{panel_id}").border_title = f"◢ {number:02d} · {name} ◣"

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout(event.size.width, event.size.height)

    def _apply_layout(self, width: int, height: int) -> None:
        if width < 88 or height < 34:
            mode = "compact"
        elif width < 122:
            mode = "rail"
        else:
            mode = "full"
        short = height < 29
        self.layout_mode = mode
        self.layout_short = short
        try:
            body = self.query_one("#body")
        except NoMatches:
            return
        body.set_class(mode == "rail", "rail")
        body.set_class(mode == "compact", "compact")
        body.set_class(short, "short")
        self.query_one(HintBar).refresh()
        self.query_one(TachyonHeader).refresh()

    def _body_class(self, enabled: bool, name: str) -> None:
        self.query_one("#body").set_class(enabled, name)
        self.query_one(HintBar).refresh()

    def _flash(self, message: str, *, style: str = palette.ACCENT) -> None:
        self.query_one(HintBar).flash(message, style=style)

    def _leave_decks(self) -> None:
        self._clear_magnify(refocus=False)
        self.overview = False
        self.files_only = False
        self._body_class(False, "overview")
        self._body_class(False, "files-only")

    def on_terminal_title_changed(self, message: Terminal.TitleChanged) -> None:
        term = self.query_one(Terminal)
        setter = getattr(term, "set_context_title", None)
        if setter is not None:
            setter(message.title)

    def on_file_browser_path_changed(self, message: FileBrowser.PathChanged) -> None:
        self._flash(f"TARGET  {_short_path(message.path)}", style=palette.ACCENT_DIM)

    def on_terminal_cwd_changed(self, message: Terminal.CwdChanged) -> None:
        self.query_one(FileBrowser).follow(message.path)
        self.query_one(RepoPanel).set_target(message.path)
        self.query_one(TachyonHeader).set_cwd(message.path)

    def on_terminal_key_tapped(self, message: Terminal.KeyTapped) -> None:
        if self.keys_visible:
            self.query_one(KeysPanel).tap(message.key, message.character)

    def on_connections_panel_remotes_sampled(
        self, message: ConnectionsPanel.RemotesSampled
    ) -> None:
        self.query_one(GlobePanel).update_targets(message.ips)

    # ----------------------------------------------------------- leader deck

    def action_leader(self) -> None:
        if not isinstance(self.screen, CommandDeck):
            self.push_screen(CommandDeck())

    def action_stand_down(self) -> None:
        """ESC backs out: magnified instrument, expanded deck, then the shell.

        (In shell-focus mode the terminal owns ESC, so zen is normally left
        via ^SPC z — this branch covers ESC from an unfocused state.)
        """
        if self.magnified is not None:
            self._clear_magnify(refocus=True)
        elif self.overview:
            self.action_overview()
        elif self.files_only:
            self._leave_decks()
            self.query_one(Terminal).focus()
            self._flash("SHELL DECK RESTORED")
        elif self.zen:
            self.action_zen()
        elif self.focused is not None and not isinstance(self.focused, Terminal):
            self.query_one(Terminal).focus()

    # -------------------------------------------------------------- magnify

    def action_magnify(self, index: int) -> None:
        """Fill the deck with panel ``index`` (tmux zoom for instruments)."""
        if not 1 <= index <= len(self.PANEL_REGISTRY):
            return
        panel_id, name = self.PANEL_REGISTRY[index - 1]
        if panel_id == "term":
            self.action_zen()
        elif panel_id == "panel-files":
            self._magnify_files()
        elif self.magnified == panel_id:
            self._clear_magnify(refocus=True)
        else:
            self._set_magnify(panel_id, f"{index:02d} · {name}")

    def _magnify_files(self) -> None:
        if self.files_only:
            self._leave_decks()
            self.query_one(Terminal).focus()
            self._flash("SHELL DECK RESTORED")
            return
        self._leave_decks()
        self.zen = False
        self._body_class(False, "zen")
        self.files_only = True
        self._body_class(True, "files-only")
        self.query_one(FileBrowser).focus_tree()
        self._flash("MAGNIFY 02 · FILESYSTEM")

    def _set_magnify(self, panel_id: str, label: str) -> None:
        self._leave_decks()
        self.zen = False
        self._body_class(False, "zen")
        panel = self.query_one(f"#{panel_id}")
        if panel.parent is not None:
            panel.parent.add_class("zoom-host")
        panel.add_class("zoom-target")
        self.magnified = panel_id
        self._body_class(True, "zoomed")
        self.set_focus(None)
        self._flash(f"MAGNIFY {label}")

    def _clear_magnify(self, *, refocus: bool) -> None:
        if self.magnified is None:
            return
        with suppress(NoMatches):
            panel = self.query_one(f"#{self.magnified}")
            panel.remove_class("zoom-target")
            if panel.parent is not None:
                panel.parent.remove_class("zoom-host")
        self.magnified = None
        self._body_class(False, "zoomed")
        if refocus:
            self.query_one(Terminal).focus()
            self._flash("DECK RESTORED", style=palette.OK)

    # ---------------------------------------------------------------- actions

    def action_operator_index(self) -> None:
        self.push_screen(OperatorIndex())

    def action_focus_terminal(self) -> None:
        self._leave_decks()
        self.query_one(Terminal).focus()
        self._flash("SHELL CHANNEL ACTIVE")

    def action_focus_files(self) -> None:
        self._clear_magnify(refocus=False)
        if self.overview or self.zen:
            self.overview = False
            self.zen = False
            self._body_class(False, "overview")
            self._body_class(False, "zen")
        self.files_only = self.layout_short
        self._body_class(self.files_only, "files-only")
        self.query_one(FileBrowser).focus_tree()
        self._flash("FILESYSTEM CHANNEL ACTIVE")

    def action_cd_selected(self) -> None:
        browser = self.query_one(FileBrowser)
        target = browser.target_directory
        term = self.query_one(Terminal)
        changer = getattr(term, "change_directory", None)
        if changer is None or not changer(target):
            self._flash("SHELL BRIDGE UNAVAILABLE", style=palette.HOT)
            return
        self._leave_decks()
        self.zen = False
        self._body_class(False, "zen")
        term.focus()
        self._flash(f"CD  {_short_path(target)}")

    def action_clear_shell(self) -> None:
        self.query_one(Terminal).clear_buffer()
        self._flash("SHELL BUFFER CLEARED")

    def action_respawn(self) -> None:
        self.query_one(Terminal).restart()
        self._flash("SHELL CHANNEL RESPAWNING", style=palette.HOT)

    def action_sigint(self) -> None:
        self.query_one(Terminal).send_signal_char("\x03")

    def action_toggle_telemetry(self) -> None:
        self.telemetry_paused = not self.telemetry_paused
        state = "HELD" if self.telemetry_paused else "RESUMED"
        style = palette.WARN if self.telemetry_paused else palette.OK
        self._flash(f"TELEMETRY {state}", style=style)
        self.query_one(HintBar).refresh()

    def action_theme_deck(self) -> None:
        if not isinstance(self.screen, ThemeDeck):
            self.push_screen(ThemeDeck())

    def action_set_theme(self, name: str) -> None:
        """Hot-swap the palette: CSS re-derives from variables, renders re-read."""
        if name not in palette.THEMES:
            return
        applied = palette.set_theme(name)
        self.ansi_color = applied.ansi
        self.refresh_css()
        for widget in self.query("*"):
            widget.refresh()
        # Panels that cache pre-styled Rich content repaint on their next
        # sampling tick; the file browser has no tick, so rebuild it now.
        with suppress(NoMatches):
            self.query_one(FileBrowser)._update_path_chrome()
        self._flash(f"THEME {name.upper()} — {applied.description}")

    def action_toggle_globe(self) -> None:
        orbit = self.query_one(GlobePanel).toggle_mode()
        self._flash("UPLINK GRID · ORBIT" if orbit else "UPLINK GRID · CHART")

    def action_toggle_keys(self) -> None:
        self.keys_visible = not self.keys_visible
        self._body_class(self.keys_visible, "keys-on")
        state = "ON" if self.keys_visible else "OFF"
        style = palette.ACCENT if self.keys_visible else palette.ACCENT_DIM
        self._flash(f"INPUT MATRIX {state}", style=style)

    def action_toggle_hidden(self) -> None:
        browser = self.query_one(FileBrowser)
        browser.toggle_hidden()
        state = "VISIBLE" if browser.hidden_visible else "FILTERED"
        self._flash(f"DOTFILES {state}", style=palette.ACCENT_DIM)

    def action_overview(self) -> None:
        self._clear_magnify(refocus=False)
        entering = not self.overview
        self.overview = entering
        self.zen = False
        self.files_only = False
        self._body_class(False, "zen")
        self._body_class(False, "files-only")
        self._body_class(entering, "overview")
        if entering:
            self.set_focus(None)
            self._flash("SENSOR DECK EXPANDED")
        else:
            self.query_one(Terminal).focus()
            self._flash("SHELL DECK RESTORED")

    def action_zen(self) -> None:
        entering = not self.zen
        self._leave_decks()
        self.zen = entering
        self._body_class(entering, "zen")
        self.query_one(Terminal).focus()
        self._flash(
            "SHELL FOCUS" if entering else "DASHBOARD RESTORED",
            style=palette.HOT if entering else palette.OK,
        )


def main() -> None:
    TachyonApp(config=parse_config()).run()


if __name__ == "__main__":
    main()
