from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import pyte
import pytest
from textual.app import App, ComposeResult

from tachyon.widgets.term import Terminal, _rich_color, _TerminalScreen


def _screen_text(terminal: Terminal) -> str:
    return "\n".join(terminal._screen.display)


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition was not met before timeout")
        await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("default", None),
        ("brown", "yellow"),
        ("brightbrown", "bright_yellow"),
        ("cyan", "cyan"),
        ("12aBcF", "#12aBcF"),
        ("12345", None),
        ("gggggg", None),
        ("unknown", None),
    ],
)
def test_rich_color_conversion(source: str, expected: str | None) -> None:
    assert _rich_color(source) == expected


class _RenderOnlyTerminal(Terminal):
    def on_mount(self) -> None:
        """Exercise rendering without starting a process."""


class _RenderApp(App[None]):
    CSS = "Terminal { width: 42; height: 10; border: round cyan; }"

    def compose(self) -> ComposeResult:
        yield _RenderOnlyTerminal(id="term")


def test_no_color_render_uses_concrete_styles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")

    async def probe() -> None:
        app = _RenderApp()
        async with app.run_test(size=(80, 20)):
            terminal = app.query_one("#term", _RenderOnlyTerminal)
            terminal._stream.feed(b"\x1b[31;44;1mstyled\x1b[0m")

            live = terminal.render_line(0)
            assert live.cell_length == terminal.size.width
            assert all(segment.style is not None for segment in live)

            terminal._screen.resize(columns=max(terminal.size.width - 3, 1))
            padded = terminal.render_line(0)
            assert padded.cell_length == terminal.size.width
            assert all(segment.style is not None for segment in padded)

            blank = terminal.render_line(terminal._screen.lines)
            assert all(segment.style is not None for segment in blank)

            terminal._dead = True
            assert all(
                segment.style is not None
                for y in range(terminal.size.height)
                for segment in terminal.render_line(y)
            )

    asyncio.run(asyncio.wait_for(probe(), timeout=2.0))


def test_history_screen_is_bounded_and_pages_back_to_live() -> None:
    screen = _TerminalScreen(12, 3, history=5, ratio=1.0)
    stream = pyte.ByteStream(screen)
    stream.feed(b"".join(f"line-{line:02}\r\n".encode() for line in range(20)))

    live = screen.display.copy()
    assert screen.history.top.maxlen == 5
    assert len(screen.history.top) == 5
    assert screen.history.position == screen.history.size == 5

    screen.prev_page()
    assert screen.history.position < screen.history.size
    assert screen.display != live

    screen.next_page()
    assert screen.history.position == screen.history.size
    assert screen.display == live


def test_1049_alternate_screen_restores_primary_buffer_and_cursor() -> None:
    screen = _TerminalScreen(16, 4, history=20)
    stream = pyte.ByteStream(screen)
    stream.feed(b"PRIMARY")
    primary_display = screen.display.copy()
    primary_cursor = (screen.cursor.x, screen.cursor.y)

    stream.feed(b"\x1b[?1049hALT-SCREEN")
    assert screen.in_alternate_screen is True
    assert "ALT-SCREEN" in "\n".join(screen.display)
    assert screen.display != primary_display

    stream.feed(b"\x1b]2;alternate title\x07\x1b[?1049l")
    assert screen.in_alternate_screen is False
    assert screen.display == primary_display
    assert (screen.cursor.x, screen.cursor.y) == primary_cursor
    assert screen.title == "alternate title"


def test_terminal_constructor_applies_cwd_and_history(tmp_path: Path) -> None:
    terminal = Terminal(command=["/bin/sh"], cwd=tmp_path, history_lines=17)

    assert terminal._cwd == tmp_path
    assert terminal._history_lines == 17
    assert terminal._screen.history.size == 17


def test_change_directory_quotes_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    terminal = Terminal(command=["/bin/sh"])
    target = tmp_path / "space and 'quote'"
    writes: list[str | bytes] = []

    def capture(data: str | bytes) -> bool:
        writes.append(data)
        return True

    monkeypatch.setattr(terminal, "_write", capture)

    assert terminal.change_directory(target) is True
    assert writes == [f"\x15cd {shlex.quote(str(target))}\r"]


def test_output_buffer_rejects_stale_generations() -> None:
    terminal = Terminal(command=["/bin/sh"])
    terminal._active_generation = 2
    terminal._output_generation = 2
    terminal._pending_data_generation = 2

    assert terminal._queue_output(1, b"stale") is False
    assert terminal._output_buffer == b""

    assert terminal._queue_output(2, b"fresh-data") is True
    assert terminal._take_output(1) == (b"", False)
    assert terminal._take_output(2, limit=5) == (b"fresh", True)
    assert terminal._take_output(2) == (b"-data", False)


class _ShellApp(App[None]):
    CSS = "Terminal { width: 42; height: 10; border: round cyan; }"

    def __init__(self, cwd: Path) -> None:
        super().__init__()
        self._cwd = cwd

    def compose(self) -> ComposeResult:
        yield Terminal(
            command=["/bin/sh"],
            cwd=self._cwd,
            history_lines=64,
            id="term",
        )


@pytest.mark.parametrize("no_color", [False, True])
def test_shell_lifecycle_dimensions_output_and_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_color: bool
) -> None:
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)

    async def probe() -> None:
        app = _ShellApp(tmp_path)
        async with app.run_test(size=(80, 20)):
            terminal = app.query_one("#term", Terminal)
            assert terminal._pty is not None
            assert (terminal._screen.columns, terminal._screen.lines) == (
                terminal.size.width,
                terminal.size.height,
            )
            assert terminal._pty.getwinsize() == (
                terminal.size.height,
                terminal.size.width,
            )

            # Octal escapes keep the decoded marker out of the shell's echoed
            # input, so observing it proves child output reached pyte.
            assert terminal.execute(r"printf '\120\124\131\137\122\105\101\104\131\n'")
            await _wait_until(lambda: "PTY_READY" in _screen_text(terminal))

            old_generation = terminal._active_generation
            assert old_generation is not None
            terminal.restart()
            current_generation = terminal._active_generation
            assert current_generation == old_generation + 1

            terminal.post_message(Terminal.Exited(old_generation))
            await asyncio.sleep(0.05)
            assert terminal._active_generation == current_generation
            assert terminal._dead is False
            assert terminal._pty is not None and terminal._pty.isalive()

    asyncio.run(asyncio.wait_for(probe(), timeout=3.0))


def test_sanitized_environment_strips_the_hosting_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from tachyon.widgets.term import _sanitized_environment

    monkeypatch.setattr(sys, "prefix", "/opt/project/.venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr/local/python3.12")
    env = _sanitized_environment(
        {
            "VIRTUAL_ENV": "/opt/project/.venv",
            "VIRTUAL_ENV_PROMPT": "project",
            "PYTHONHOME": "/opt/project/.venv",
            "PATH": "/opt/project/.venv/bin:/usr/bin:/bin",
            "HOME": "/home/operator",
        }
    )

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/operator"
    for poisoned in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME"):
        assert poisoned not in env


def test_sanitized_environment_keeps_foreign_venvs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venv the *user* activated (not the one hosting Tachyon) survives."""
    import sys

    from tachyon.widgets.term import _sanitized_environment

    monkeypatch.setattr(sys, "prefix", "/usr/local/python3.12")
    monkeypatch.setattr(sys, "base_prefix", "/usr/local/python3.12")
    base = {"VIRTUAL_ENV": "/home/operator/work/.venv", "PATH": "/usr/bin:/bin"}

    assert _sanitized_environment(base) == base


def test_clear_buffer_wipes_scrollback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")

    class ClearApp(App):
        def compose(self) -> ComposeResult:
            yield Terminal(id="term")

    async def probe() -> None:
        app = ClearApp()
        async with app.run_test(size=(80, 10)):
            terminal = app.query_one("#term", Terminal)
            # Push enough lines through pyte that scrollback accumulates.
            terminal._stream.feed(b"".join(b"line %d\r\n" % i for i in range(60)))
            assert len(terminal._screen.history.top) > 0

            terminal.clear_buffer()
            assert len(terminal._screen.history.top) == 0
            assert len(terminal._screen.history.bottom) == 0
            assert terminal._history_offset() == 0

    asyncio.run(asyncio.wait_for(probe(), timeout=5.0))
