"""Embedded terminal: a real PTY-backed shell rendered through pyte into Textual.

Architecture:
  ptyprocess spawns $SHELL attached to a pty.  A daemon thread blocks on
  os.read() of the pty master and coalesces bytes for the Textual event loop,
  where they are fed to a pyte ByteStream/HistoryScreen pair.  The widget
  renders the pyte screen buffer line-by-line via render_line(), and translates
  Textual key events back into the byte sequences a terminal would send.
"""

from __future__ import annotations

import os
import shlex
import shutil
import string
import sys
import threading
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any

import psutil
import ptyprocess
import pyte
from pyte.screens import StaticDefaultDict
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

from tachyon import palette
from tachyon.widgets.resize import EdgeResize

# pyte stores private DEC modes shifted left by 5 bits.
DECCKM = 1 << 5  # application cursor keys
BRACKETED_PASTE = 2004 << 5

_ALT_SCREEN_MODES = frozenset((47, 1047, 1049))
_HISTORY_LINES = 3000
_OUTPUT_BUFFER_LIMIT = 2 * 1024 * 1024
_OUTPUT_FEED_CHUNK = 256 * 1024

_HEX_DIGITS = set(string.hexdigits)

_PYTE_COLOR_TO_RICH = {
    "black": "black",
    "red": "red",
    "green": "green",
    "brown": "yellow",  # pyte's historical name for ANSI yellow
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "brightblack": "bright_black",
    "brightred": "bright_red",
    "brightgreen": "bright_green",
    "brightbrown": "bright_yellow",
    "brightyellow": "bright_yellow",
    "brightblue": "bright_blue",
    "brightmagenta": "bright_magenta",
    "brightcyan": "bright_cyan",
    "brightwhite": "bright_white",
}


def _rich_color(pyte_color: str) -> str | None:
    if pyte_color == "default":
        return None
    mapped = _PYTE_COLOR_TO_RICH.get(pyte_color)
    if mapped is not None:
        return mapped
    if len(pyte_color) == 6 and all(c in _HEX_DIGITS for c in pyte_color):
        return f"#{pyte_color}"
    return None


@lru_cache(maxsize=8)
def _empty_style(term_fg: str, term_bg: str) -> Style:
    return Style(color=term_fg, bgcolor=term_bg)


# The theme's terminal colors are part of the cache key, so a theme switch
# naturally re-derives styles without an explicit cache flush.
@lru_cache(maxsize=4096)
def _char_style(
    fg: str,
    bg: str,
    bold: bool,
    italics: bool,
    underscore: bool,
    strikethrough: bool,
    reverse: bool,
    term_fg: str,
    term_bg: str,
) -> Style:
    color = _rich_color(fg)
    background = _rich_color(bg)
    return Style(
        color=term_fg if fg == "default" else color,
        bgcolor=term_bg if bg == "default" else background,
        bold=bold,
        italic=italics,
        underline=underscore,
        strike=strikethrough,
        reverse=reverse,
    )


class _TerminalScreen(pyte.HistoryScreen):
    """History screen with lightweight xterm alternate-buffer semantics.

    pyte records private DEC modes but doesn't implement buffer switching for
    47/1047/1049.  Keeping two complete pyte state bundles lets the stream keep
    a single listener while primary history and cursor state survive a
    full-screen program.  Mode 47 retains its alternate buffer; 1047 and 1049
    use a freshly cleared buffer, and 1049 restores the complete primary cursor
    state when leaving.
    """

    _STATE_ATTRIBUTES = (
        "history",
        "savepoints",
        "columns",
        "lines",
        "buffer",
        "dirty",
        "margins",
        "mode",
        "title",
        "icon_name",
        "charset",
        "g0_charset",
        "g1_charset",
        "tabstops",
        "cursor",
        "saved_columns",
    )

    def __init__(
        self,
        columns: int,
        lines: int,
        *,
        history: int = _HISTORY_LINES,
        ratio: float = 0.5,
    ) -> None:
        self._history_limit = history
        self._history_ratio = ratio
        self._primary_state: dict[str, Any] | None = None
        self._alternate_state: dict[str, Any] | None = None
        self._alternate_mode: int | None = None
        super().__init__(columns, lines, history=history, ratio=ratio)

    @property
    def in_alternate_screen(self) -> bool:
        return self._alternate_mode is not None

    def _capture_state(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self._STATE_ATTRIBUTES}

    def _apply_state(self, state: dict[str, Any]) -> None:
        for name in self._STATE_ATTRIBUTES:
            setattr(self, name, state[name])

        # Screen's defaultdict factory closes over the instance that created
        # it.  Rebind transferred buffers so future sparse lines use *this*
        # screen's current default character and modes.
        self.buffer.default_factory = lambda: StaticDefaultDict(self.default_char)
        self.dirty.update(range(self.lines))

    def _blank_alternate_state(self, columns: int, lines: int) -> dict[str, Any]:
        # Alternate-screen output must not pollute primary scrollback.  A
        # one-line HistoryScreen retains pyte's event wrappers without exposing
        # meaningful pagination inside the alternate buffer.
        blank = pyte.HistoryScreen(columns, lines, history=1, ratio=self._history_ratio)
        return {name: getattr(blank, name) for name in self._STATE_ATTRIBUTES}

    def _enter_alternate_screen(self, mode: int) -> None:
        if self.in_alternate_screen:
            return

        columns, lines = self.columns, self.lines
        title, icon_name = self.title, self.icon_name
        self._primary_state = self._capture_state()

        if mode == 47 and self._alternate_state is not None:
            state = self._alternate_state
        else:
            state = self._blank_alternate_state(columns, lines)
        self._apply_state(state)
        super().resize(lines=lines, columns=columns)
        self.title, self.icon_name = title, icon_name
        self._alternate_mode = mode

    def _leave_alternate_screen(self) -> None:
        if not self.in_alternate_screen or self._primary_state is None:
            return

        mode = self._alternate_mode
        columns, lines = self.columns, self.lines
        title, icon_name = self.title, self.icon_name
        if mode == 47:
            self._alternate_state = self._capture_state()
        else:
            self._alternate_state = None

        primary = self._primary_state
        self._primary_state = None
        self._alternate_mode = None
        self._apply_state(primary)
        # The primary screen may have been parked while the widget resized.
        super().resize(lines=lines, columns=columns)
        self.title, self.icon_name = title, icon_name

    def set_mode(self, *modes: int, **kwargs: Any) -> None:
        if kwargs.get("private"):
            alt_modes = [mode for mode in modes if mode in _ALT_SCREEN_MODES]
            if alt_modes:
                # Prefer the modern save/clear/restore mode if a sequence ever
                # supplies more than one alternate-screen flag.
                mode = max(alt_modes, key=lambda value: (value == 1049, value == 1047))
                self._enter_alternate_screen(mode)
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs: Any) -> None:
        super().reset_mode(*modes, **kwargs)
        if kwargs.get("private") and any(mode in _ALT_SCREEN_MODES for mode in modes):
            self._leave_alternate_screen()


# Textual key name -> escape sequence (normal-mode cursor keys).
_KEY_SEQUENCES = {
    "enter": "\r",
    "tab": "\t",
    "backspace": "\x7f",
    "escape": "\x1b",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "insert": "\x1b[2~",
    "delete": "\x1b[3~",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
    "shift+tab": "\x1b[Z",
    "ctrl+up": "\x1b[1;5A",
    "ctrl+down": "\x1b[1;5B",
    "ctrl+right": "\x1b[1;5C",
    "ctrl+left": "\x1b[1;5D",
    "shift+up": "\x1b[1;2A",
    "shift+down": "\x1b[1;2B",
    "shift+right": "\x1b[1;2C",
    "shift+left": "\x1b[1;2D",
    "f1": "\x1bOP",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
    "f4": "\x1bOS",
    "f5": "\x1b[15~",
    "f6": "\x1b[17~",
    "f7": "\x1b[18~",
    "f8": "\x1b[19~",
    "f9": "\x1b[20~",
    "f10": "\x1b[21~",
    "f11": "\x1b[23~",
    "f12": "\x1b[24~",
}


def _sanitized_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The inherited environment minus the venv Tachyon itself runs in.

    ``uv run tachyon`` executes inside the project's virtualenv, and a plainly
    inherited environment would trap every spawned shell in that venv.  The
    embedded shell should feel like a freshly opened terminal instead.
    """
    env = dict(os.environ if base is None else base)
    if sys.prefix == sys.base_prefix:
        return env
    for name in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME"):
        env.pop(name, None)
    prefix = os.path.abspath(sys.prefix)
    env["PATH"] = os.pathsep.join(
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if entry and not os.path.abspath(entry).startswith(prefix + os.sep)
    )
    return env


_APPLICATION_CURSOR = {
    "up": "\x1bOA",
    "down": "\x1bOB",
    "right": "\x1bOC",
    "left": "\x1bOD",
    "home": "\x1bOH",
    "end": "\x1bOF",
}


class Terminal(EdgeResize, Widget, can_focus=True):
    """A shell session embedded in the TUI."""

    class Data(Message):
        """A generation's coalesced output buffer is ready to drain."""

        def __init__(self, generation: int) -> None:
            self.generation = generation
            super().__init__()

    class Exited(Message):
        def __init__(self, generation: int) -> None:
            self.generation = generation
            super().__init__()

    class TitleChanged(Message):
        def __init__(self, title: str) -> None:
            self.title = title
            super().__init__()

    class CwdChanged(Message):
        """The shell process moved to a new working directory."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    class KeyTapped(Message):
        """A key was delivered to the shell (for the input matrix)."""

        def __init__(self, key: str, character: str | None) -> None:
            self.key = key
            self.character = character
            super().__init__()

    def __init__(
        self,
        command: list[str] | None = None,
        *,
        cwd: str | Path | None = None,
        history_lines: int = _HISTORY_LINES,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._command = command or [os.environ.get("SHELL") or shutil.which("zsh") or "/bin/sh"]
        self._cwd = Path(cwd).expanduser() if cwd is not None else Path.home()
        self._history_lines = max(int(history_lines), 1)
        self._pty: ptyprocess.PtyProcess | None = None
        self._reader: threading.Thread | None = None
        self._screen = _TerminalScreen(80, 24, history=self._history_lines)
        self._stream = pyte.ByteStream(self._screen)
        self._dead = False
        self._last_title = ""
        self._context_title = ""
        self._last_cwd: str | None = None

        self._generation = 0
        self._active_generation: int | None = None
        self._output_condition = threading.Condition()
        self._output_generation: int | None = None
        self._output_buffer = bytearray()
        self._pending_data_generation: int | None = None

        self.border_title = "◢ MAIN SHELL ◣"
        self._update_border_subtitle()

    # ------------------------------------------------------------- lifecycle

    def on_mount(self) -> None:
        self._spawn()
        self.set_interval(1.0, self._poll_cwd)

    def _poll_cwd(self) -> None:
        """Track the shell's working directory so other modules can follow it."""
        pty = self._pty
        if pty is None or self._dead:
            return
        try:
            cwd = psutil.Process(pty.pid).cwd()
        except (psutil.Error, OSError):
            return
        if cwd and cwd != self._last_cwd:
            self._last_cwd = cwd
            self.post_message(self.CwdChanged(Path(cwd)))

    def _content_dimensions(self) -> tuple[int, int]:
        """Return rows/columns for the drawable area, never the outer border."""
        rows = self.size.height or self._screen.lines
        columns = self.size.width or self._screen.columns
        return max(rows, 1), max(columns, 1)

    def _invalidate_session(
        self,
    ) -> tuple[ptyprocess.PtyProcess | None, threading.Thread | None]:
        pty, self._pty = self._pty, None
        reader, self._reader = self._reader, None
        self._dead = True
        with self._output_condition:
            self._active_generation = None
            self._output_generation = None
            self._output_buffer.clear()
            self._pending_data_generation = None
            self._output_condition.notify_all()
        return pty, reader

    @staticmethod
    def _close_pty(pty: ptyprocess.PtyProcess | None, reader: threading.Thread | None) -> None:
        if pty is None or pty.closed:
            return

        # PtyProcess.close() closes the file object *before* terminating the
        # child.  Another thread blocked in os.read() can hold that file
        # object's lock indefinitely (notably with /bin/sh).  Terminating first
        # produces EOF/EIO, lets the reader leave, and makes the final close
        # non-contentious.
        try:
            terminated = not pty.isalive() or pty.terminate(force=True)
        except (OSError, ptyprocess.PtyProcessError):
            try:
                terminated = not pty.isalive()
            except (OSError, ptyprocess.PtyProcessError):
                terminated = True  # Already reaped elsewhere.
        if not terminated:
            return

        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.5)
        if reader is None or not reader.is_alive():
            with suppress(OSError, ptyprocess.PtyProcessError):
                pty.close(force=False)

    def _spawn(self) -> None:
        old_pty, old_reader = self._invalidate_session()
        self._close_pty(old_pty, old_reader)

        rows, cols = self._content_dimensions()
        screen = _TerminalScreen(cols, rows, history=self._history_lines)
        stream = pyte.ByteStream(screen)
        env = _sanitized_environment()
        env.update(TERM="xterm-256color", COLORTERM="truecolor", TACHYON="1")
        pty = ptyprocess.PtyProcess.spawn(
            self._command, dimensions=(rows, cols), env=env, cwd=str(self._cwd)
        )

        self._generation += 1
        generation = self._generation
        self._screen = screen
        self._stream = stream
        self._pty = pty
        self._dead = False
        self._last_cwd = None
        with self._output_condition:
            self._active_generation = generation
            self._output_generation = generation
            self._output_buffer.clear()
            self._pending_data_generation = None

        had_title = bool(self._last_title)
        self._last_title = ""
        self.set_context_title("")
        if had_title:
            self.post_message(self.TitleChanged(""))

        self._reader = threading.Thread(
            target=self._read_loop,
            args=(pty, generation),
            name=f"tachyon-pty-{generation}",
            daemon=True,
        )
        self._reader.start()
        self._update_border_subtitle()
        self.refresh()

    def restart(self) -> None:
        """Immediately replace the active PTY with a clean generation."""
        self._spawn()

    def on_unmount(self) -> None:
        pty, reader = self._invalidate_session()
        self._close_pty(pty, reader)

    def _post_data_message(self, generation: int) -> bool:
        try:
            posted = self.post_message(self.Data(generation))
        except RuntimeError:
            posted = False
        if not posted:
            with self._output_condition:
                if self._pending_data_generation == generation:
                    self._pending_data_generation = None
                self._output_condition.notify_all()
        return posted

    def _queue_output(self, generation: int, data: bytes) -> bool:
        should_post = False
        with self._output_condition:
            while (
                self._active_generation == generation
                and self._output_generation == generation
                and len(self._output_buffer) >= _OUTPUT_BUFFER_LIMIT
            ):
                # Bound memory and let the PTY provide natural backpressure if
                # rendering can't keep up with a noisy process.
                self._output_condition.wait(timeout=0.1)

            if self._active_generation != generation or self._output_generation != generation:
                return False
            self._output_buffer.extend(data)
            if self._pending_data_generation != generation:
                self._pending_data_generation = generation
                should_post = True

        return not should_post or self._post_data_message(generation)

    def _take_output(
        self, generation: int, limit: int | None = _OUTPUT_FEED_CHUNK
    ) -> tuple[bytes, bool]:
        """Take output for a generation and reserve at most one follow-up."""
        with self._output_condition:
            if self._active_generation != generation or self._output_generation != generation:
                if self._pending_data_generation == generation:
                    self._pending_data_generation = None
                return b"", False

            count = (
                len(self._output_buffer) if limit is None else min(len(self._output_buffer), limit)
            )
            data = bytes(self._output_buffer[:count])
            del self._output_buffer[:count]
            self._pending_data_generation = None
            more = bool(self._output_buffer)
            if more:
                self._pending_data_generation = generation
            self._output_condition.notify_all()
            return data, more

    def _read_loop(self, pty: ptyprocess.PtyProcess, generation: int) -> None:
        while True:
            try:
                data = os.read(pty.fd, 65536)
            except OSError:
                break
            if not data:
                break
            if not self._queue_output(generation, data):
                break
        with suppress(RuntimeError):
            self.post_message(self.Exited(generation))

    # -------------------------------------------------------------- messages

    def _sync_title(self) -> None:
        title = self._screen.title
        if title == self._last_title:
            return
        self._last_title = title
        self.set_context_title(title)
        self.post_message(self.TitleChanged(title))

    def on_terminal_data(self, message: Terminal.Data) -> None:
        message.stop()
        data, more = self._take_output(message.generation)
        if more:
            self._post_data_message(message.generation)
        if not data:
            return

        self._stream.feed(data)
        self._sync_title()
        self._update_border_subtitle()
        self.refresh()

    def on_terminal_exited(self, message: Terminal.Exited) -> None:
        message.stop()
        if message.generation != self._active_generation:
            return

        # The reader may finish after queueing a follow-up behind this message;
        # drain its finite remainder before showing the dead-session state.
        data, _more = self._take_output(message.generation, limit=None)
        if data:
            self._stream.feed(data)
            self._sync_title()
        self._dead = True
        if not self.is_running:
            return
        # eDEX never dies: respawn the shell after a beat.
        self.set_timer(0.7, lambda: self._respawn_if_dead(message.generation))
        self._update_border_subtitle()
        self.refresh()

    def _respawn_if_dead(self, generation: int) -> None:
        if self._dead and self.is_running and generation == self._active_generation:
            self._spawn()

    # --------------------------------------------------------------- chrome

    def set_context_title(self, title: str) -> None:
        """Set the compact OSC/context label shown in the border subtitle.

        The main border title intentionally stays stable so live shell titles,
        history position, and dimensions don't cause the panel chrome to jump.
        """
        self._context_title = " ".join(title.split())[:48]
        self._update_border_subtitle()

    def _history_offset(self) -> int:
        history = self._screen.history
        return max(history.size - history.position, 0)

    def _update_border_subtitle(self) -> None:
        offset = self._history_offset()
        if offset:
            state = f"HISTORY -{offset}"
        elif self._dead:
            state = "RESTARTING"
        else:
            state = "LIVE"
        if self._screen.in_alternate_screen:
            state += " / ALT"

        parts = []
        if self._context_title:
            parts.append(self._context_title)
        parts.extend((state, f"{self._screen.columns}×{self._screen.lines}"))
        self.border_subtitle = "  •  ".join(parts)

    # -------------------------------------------------------------- history

    def _history_page(self, previous: bool) -> None:
        before = self._screen.history.position
        if previous:
            self._screen.prev_page()
        else:
            self._screen.next_page()
        if self._screen.history.position != before:
            self._update_border_subtitle()
            self.refresh()

    def _history_home(self) -> None:
        before = self._screen.history.position
        while self._screen.history.top:
            position = self._screen.history.position
            self._screen.prev_page()
            if self._screen.history.position == position:
                break
        if self._screen.history.position != before:
            self._update_border_subtitle()
            self.refresh()

    def _history_end(self) -> None:
        before = self._screen.history.position
        while self._screen.history.bottom:
            position = self._screen.history.position
            self._screen.next_page()
            if self._screen.history.position == position:
                break
        if self._screen.history.position != before:
            self._update_border_subtitle()
            self.refresh()

    # ----------------------------------------------------------------- input

    def _write(self, data: str | bytes) -> bool:
        if self._pty is None or self._dead:
            return False
        if isinstance(data, str):
            data = data.encode("utf-8", "ignore")
        try:
            return self._pty.write(data) == len(data)
        except (OSError, ValueError):
            return False

    def send_signal_char(self, char: str) -> None:
        """Write a control character (e.g. \\x03 for SIGINT) to the shell."""
        self._write(char)

    def execute(self, command: str, clear_line: bool = False) -> bool:
        """Submit a command to the shell, optionally clearing typed input."""
        self._history_end()
        prefix = "\x15" if clear_line else ""  # readline/zle kill-to-start
        return self._write(prefix + command + "\r")

    def change_directory(self, path: str | os.PathLike[str]) -> bool:
        """Safely submit a ``cd`` to an absolute, shell-quoted path."""
        absolute = os.path.abspath(os.path.expanduser(os.fspath(path)))
        return self.execute(f"cd {shlex.quote(absolute)}", clear_line=True)

    def clear_buffer(self) -> None:
        """cmd+K semantics: wipe scrollback and let the shell repaint its prompt.

        Inside the alternate screen there is no scrollback to wipe; the
        form feed is still forwarded so full-screen apps can redraw.
        """
        screen = self._screen
        if not screen.in_alternate_screen:
            screen.history.top.clear()
            screen.history.bottom.clear()
            self._screen.history = screen.history._replace(position=screen.history.size)
        self._write("\x0c")
        self._update_border_subtitle()
        self.refresh()

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key in {"shift+pageup", "shift+pagedown", "ctrl+shift+home", "ctrl+shift+end"}:
            event.stop()
            event.prevent_default()
            if key == "shift+pageup":
                self._history_page(previous=True)
            elif key == "shift+pagedown":
                self._history_page(previous=False)
            elif key == "ctrl+shift+home":
                self._history_home()
            else:
                self._history_end()
            return

        if self._dead:
            return
        self._history_end()
        seq: str | None = None
        if DECCKM in self._screen.mode and key in _APPLICATION_CURSOR:
            seq = _APPLICATION_CURSOR[key]
        elif key in _KEY_SEQUENCES:
            seq = _KEY_SEQUENCES[key]
        elif key.startswith("ctrl+") and len(key) == 6 and key[5] in string.ascii_lowercase:
            seq = chr(ord(key[5]) - 96)
        elif event.character:
            seq = event.character
        if seq is not None:
            event.stop()
            event.prevent_default()
            self._write(seq)
            self.post_message(self.KeyTapped(key, event.character))

    def on_paste(self, event: events.Paste) -> None:
        event.stop()
        self._history_end()
        text = event.text
        if BRACKETED_PASTE in self._screen.mode:
            self._write("\x1b[200~" + text + "\x1b[201~")
        else:
            self._write(text)

    # ---------------------------------------------------------------- sizing

    def on_resize(self, event: events.Resize) -> None:
        del event
        # Widget.size is the drawable content box.  Resize.size includes the
        # border for custom-rendered widgets and made shells two cells too big.
        rows = max(self.size.height, 1)
        cols = max(self.size.width, 1)
        if (self._screen.lines, self._screen.columns) != (rows, cols):
            self._screen.resize(lines=rows, columns=cols)
            if self._pty is not None and not self._dead:
                with suppress(OSError):
                    self._pty.setwinsize(rows, cols)
            self._update_border_subtitle()
            self.refresh()

    # ------------------------------------------------------------- rendering

    def render_line(self, y: int) -> Strip:
        screen = self._screen
        term_fg, term_bg = palette.TERM_FG, palette.TERM_BG
        empty = _empty_style(term_fg, term_bg)
        if y >= screen.lines:
            return Strip.blank(self.size.width, empty)
        if self._dead:
            return self._render_dead_line(y, empty)
        buffer_line = screen.buffer[y]
        cursor = screen.cursor
        show_cursor = (
            self.has_focus and not cursor.hidden and cursor.y == y and cursor.x < screen.columns
        )
        segments: list[Segment] = []
        run: list[str] = []
        run_style: Style | None = None
        for x in range(screen.columns):
            char = buffer_line[x]
            style = _char_style(
                char.fg,
                char.bg,
                char.bold,
                char.italics,
                char.underscore,
                char.strikethrough,
                char.reverse != (show_cursor and x == cursor.x),
                term_fg,
                term_bg,
            )
            if style is not run_style and run:
                segments.append(Segment("".join(run), run_style or empty))
                run = []
            run_style = style
            run.append(char.data)
        if run:
            segments.append(Segment("".join(run), run_style or empty))
        strip = Strip(segments)
        return strip.adjust_cell_length(self.size.width, empty)

    def _render_dead_line(self, y: int, empty: Style) -> Strip:
        mid = self.size.height // 2
        if y == mid:
            text = "◢ SESSION TERMINATED — RESPAWNING ◣"
            pad = max((self.size.width - len(text)) // 2, 0)
            return Strip(
                [
                    Segment(" " * pad, empty),
                    Segment(text, Style(color=palette.HOT, bold=True)),
                ]
            ).adjust_cell_length(self.size.width, empty)
        return Strip.blank(self.size.width, empty)
