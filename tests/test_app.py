from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tachyon.app import TachyonApp
from tachyon.config import TachyonConfig
from tachyon.widgets.boot import BootScreen
from tachyon.widgets.files import FileBrowser, TachyonDirectoryTree
from tachyon.widgets.help import OperatorIndex
from tachyon.widgets.term import Terminal


def _assert_terminal_dimensions(term: Terminal) -> None:
    assert term.size.width > 0
    assert term.size.height > 0
    assert (term._screen.columns, term._screen.lines) == (term.size.width, term.size.height)


def test_control_surface_layouts_and_monochrome_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    changed_directories: list[Path] = []

    def change_directory(_term: Terminal, path: str | Path) -> bool:
        changed_directories.append(Path(path))
        return True

    monkeypatch.setattr(Terminal, "change_directory", change_directory)

    async def scenario() -> None:
        app = TachyonApp(config=TachyonConfig(boot_enabled=False))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            body = app.query_one("#body")
            term = app.query_one(Terminal)
            browser = app.query_one(FileBrowser)
            tree = app.query_one(TachyonDirectoryTree)

            assert term.has_focus
            assert app.layout_mode == "full"
            assert app.layout_short is False
            assert not body.has_class("rail")
            assert not body.has_class("compact")
            assert not body.has_class("short")
            _assert_terminal_dimensions(term)

            # Reserved bindings must win over Terminal.on_key while its PTY has focus.
            term.focus()
            await pilot.press("f3")
            assert tree.has_focus

            term.focus()
            await pilot.press("f6")
            assert app.telemetry_paused is True
            assert term.has_focus
            app.action_toggle_telemetry()

            term.focus()
            await pilot.press("f8")
            assert app.overview is True
            assert body.has_class("overview")
            app.action_overview()
            await pilot.pause()
            assert term.has_focus

            term.focus()
            await pilot.press("f9")
            assert app.zen is True
            assert body.has_class("zen")
            app.action_zen()
            await pilot.pause()
            assert term.has_focus

            await pilot.resize_terminal(100, 40)
            await pilot.pause()
            assert app.layout_mode == "rail"
            assert app.layout_short is False
            assert body.has_class("rail")
            assert not body.has_class("compact")
            assert not body.has_class("short")
            _assert_terminal_dimensions(term)

            await pilot.resize_terminal(80, 28)
            await pilot.pause()
            assert app.layout_mode == "compact"
            assert app.layout_short is True
            assert not body.has_class("rail")
            assert body.has_class("compact")
            assert body.has_class("short")
            _assert_terminal_dimensions(term)

            term.focus()
            await pilot.press("f3")
            assert app.files_only is True
            assert body.has_class("files-only")
            assert tree.has_focus
            assert term.display is False
            assert browser.display is True

            browser._selected_path = tmp_path
            browser._selected_is_directory = True
            await pilot.press("f4")
            assert changed_directories == [tmp_path]
            assert app.files_only is False
            assert not body.has_class("files-only")
            assert term.has_focus

            await pilot.resize_terminal(140, 40)
            await pilot.pause()
            assert app.layout_mode == "full"
            assert app.layout_short is False
            _assert_terminal_dimensions(term)

            term.focus()
            await pilot.press("f1")
            assert isinstance(app.screen, OperatorIndex)
            await pilot.press("escape")
            assert not isinstance(app.screen, OperatorIndex)
            assert term.has_focus

            screenshot = app.export_screenshot()
            assert screenshot.startswith("<svg")
            assert "TACHYON" in screenshot

    asyncio.run(scenario())


def test_boot_screen_dismisses_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")

    async def scenario() -> None:
        app = TachyonApp(config=TachyonConfig(boot_enabled=True))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, BootScreen)
            await pilot.press("x")
            assert not isinstance(app.screen, BootScreen)

    asyncio.run(scenario())


def test_leader_deck_magnify_and_stand_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")

    async def scenario() -> None:
        from tachyon.widgets.deck import CommandDeck

        app = TachyonApp(config=TachyonConfig(boot_enabled=False))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            body = app.query_one("#body")
            term = app.query_one(Terminal)

            # Panels carry stable deck numbers for the magnify chords.
            assert term.border_title == "◢ 01 · MAIN SHELL ◣"
            assert app.query_one("#panel-cpu").border_title == "◢ 04 · CPU CORES ◣"

            # The leader arms the deck; ESC stands it down without side effects.
            await pilot.press("ctrl+space")
            assert isinstance(app.screen, CommandDeck)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, CommandDeck)
            assert term.has_focus

            # An unknown chord keeps the deck armed and names the miss.
            await pilot.press("ctrl+space")
            await pilot.press("x")
            await pilot.pause()
            assert isinstance(app.screen, CommandDeck)
            assert "no chord bound to X" in app.screen._render_strip().plain
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, CommandDeck)

            # A chord typed with CTRL still held (tmux habit) still resolves.
            await pilot.press("ctrl+space")
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert app.telemetry_paused is True
            app.action_toggle_telemetry()
            await pilot.pause()

            # leader+digit magnifies a telemetry instrument to fill the deck.
            await pilot.press("ctrl+space")
            await pilot.press("4")
            await pilot.pause()
            assert app.magnified == "panel-cpu"
            assert body.has_class("zoomed")
            cpu = app.query_one("#panel-cpu")
            assert cpu.has_class("zoom-target")
            assert app.query_one("#col-left").has_class("zoom-host")
            assert app.telemetry_active is True
            assert cpu.region.width > 100
            assert app.query_one("#panel-proc").region.width == 0
            assert term.region.width == 0

            # The same chord toggles back; focus returns to the shell.
            await pilot.press("ctrl+space")
            await pilot.press("4")
            await pilot.pause()
            assert app.magnified is None
            assert not body.has_class("zoomed")
            assert term.has_focus

            # Chord 0 magnifies panel 10, the uplink grid.
            await pilot.press("ctrl+space")
            await pilot.press("0")
            await pilot.pause()
            assert app.magnified == "panel-globe"
            await pilot.press("escape")
            await pilot.pause()
            assert app.magnified is None

            # ESC restores the deck from a magnified instrument too.
            await pilot.press("ctrl+space")
            await pilot.press("8")
            await pilot.pause()
            assert app.magnified == "panel-conn"
            await pilot.press("escape")
            await pilot.pause()
            assert app.magnified is None
            assert term.has_focus

            # Letter chords drive the existing actions: z toggles zen.
            await pilot.press("ctrl+space")
            await pilot.press("z")
            await pilot.pause()
            assert app.zen is True
            assert app.magnified is None
            await pilot.press("ctrl+space")
            await pilot.press("z")
            await pilot.pause()
            assert app.zen is False

            # leader+1 is the shell deck (zen); entering it clears a magnify.
            app.action_magnify(5)
            await pilot.pause()
            assert app.magnified == "panel-mem"
            app.action_magnify(1)
            await pilot.pause()
            assert app.zen is True and app.magnified is None
            app.action_zen()
            await pilot.pause()

    asyncio.run(scenario())


def test_tree_vim_motions_and_shell_follow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")
    (tmp_path / "alpha" / "beta").mkdir(parents=True)
    (tmp_path / "gamma").mkdir()

    async def scenario() -> None:
        config = TachyonConfig(boot_enabled=False, shell_cwd=tmp_path, filesystem_root=tmp_path)
        app = TachyonApp(config=config)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one(TachyonDirectoryTree)
            browser = app.query_one(FileBrowser)
            term = app.query_one(Terminal)

            # Let the shell's initial cwd poll land so it can't race the
            # explicit follow() calls below.
            for _ in range(30):
                await asyncio.sleep(0.1)
                if browser._shell_linked:
                    break
            assert browser._shell_linked

            tree.focus()
            await pilot.pause()
            top = tree.cursor_line
            await pilot.press("j")
            assert tree.cursor_line == top + 1
            await pilot.press("k")
            assert tree.cursor_line == top
            await pilot.press("G")
            assert tree.cursor_line == tree.last_line
            await pilot.press("g")
            assert tree.cursor_line == 0

            # l expands the highlighted directory, h folds it again.
            await pilot.press("j")  # onto "alpha"
            await pilot.press("l")
            await asyncio.sleep(0.3)
            node = tree.cursor_node
            assert node is not None and node.is_expanded
            await pilot.press("h")
            assert not node.is_expanded

            # follow() declines while the operator is inside the tree...
            target = (tmp_path / "alpha" / "beta").resolve()
            browser.follow(target)
            assert browser.selected_path != target

            # ...and quietly retargets selection + cursor otherwise.
            term.focus()
            await pilot.pause()
            browser.follow(target)
            for _ in range(30):
                await asyncio.sleep(0.1)
                cursor = tree.cursor_node
                if cursor is not None and Path(cursor.data.path).name == "beta":
                    break
            assert browser.selected_path == target
            assert browser.target_directory == target
            # follow() re-roots the tree at the cwd — an interactive `ls`.
            assert Path(tree.path).expanduser() == target
            cursor = tree.cursor_node
            assert cursor is not None and Path(cursor.data.path).name == "beta"

            # End to end: a cd inside the real shell reaches the tree via
            # the cwd poll (compare resolved paths; /tmp is a symlink on mac).
            goal = (tmp_path / "gamma").resolve()
            assert term.execute(f"cd {tmp_path / 'gamma'}")
            for _ in range(60):
                await asyncio.sleep(0.1)
                if browser.selected_path.resolve() == goal:
                    break
            assert browser.selected_path.resolve() == goal

    asyncio.run(scenario())


def _mouse(x: int = 0, y: int = 0, screen_x: int = 0, screen_y: int = 0):
    from types import SimpleNamespace

    return SimpleNamespace(x=x, y=y, screen_x=screen_x, screen_y=screen_y, stop=lambda: None)


def test_edge_resize_and_keys_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")

    async def scenario() -> None:
        from tachyon.widgets.keys import KeysPanel
        from tachyon.widgets.monitors import CpuPanel

        app = TachyonApp(config=TachyonConfig(boot_enabled=False))
        async with app.run_test(size=(160, 44)) as pilot:
            await pilot.pause()
            term = app.query_one(Terminal)
            keys = app.query_one(KeysPanel)

            # The input matrix is opt-in; ^SPC k toggles it.
            assert app.keys_visible is False
            assert keys.region.height == 0
            await pilot.press("ctrl+space")
            await pilot.press("k")
            await pilot.pause()
            assert app.keys_visible is True and keys.region.height == 7
            term.focus()
            await pilot.press("x")
            assert keys._lit
            await pilot.press("ctrl+space")
            await pilot.press("k")
            await pilot.pause()
            assert keys.region.height == 0

            # Any panel border is a drag handle: the terminal's left border
            # resizes the fixed-width left column.
            col_left = app.query_one("#col-left")
            start = col_left.region.width
            term.on_mouse_down(_mouse(x=0, y=5, screen_x=start))
            term.on_mouse_move(_mouse(x=0, y=5, screen_x=start + 12))
            term.on_mouse_up(_mouse())
            await pilot.pause()
            assert col_left.region.width == start + 12

            # A horizontal boundary resizes the fixed-height neighbor above.
            cpu = app.query_one(CpuPanel)
            mem = app.query_one("#panel-mem")
            height = cpu.region.height
            mem.on_mouse_down(_mouse(x=4, y=0, screen_y=20))
            mem.on_mouse_move(_mouse(x=4, y=0, screen_y=17))
            mem.on_mouse_up(_mouse())
            await pilot.pause()
            assert cpu.region.height == height - 3

            # Interior clicks never start a drag.
            term.on_mouse_down(_mouse(x=20, y=5, screen_x=60, screen_y=6))
            assert term._edge_drag is None

    asyncio.run(scenario())


def test_theme_deck_switches_palette_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")

    async def scenario() -> None:
        from tachyon import palette
        from tachyon.widgets.deck import ThemeDeck

        app = TachyonApp(config=TachyonConfig(boot_enabled=False))
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert palette.theme().name == "tron"

                await pilot.press("ctrl+space")
                await pilot.press("y")
                await pilot.pause()
                assert isinstance(app.screen, ThemeDeck)
                await pilot.press("3")
                await pilot.pause()
                await pilot.pause()
                assert palette.theme().name == "catppuccin"
                assert app.get_css_variables()["accent"] == "#cba6f7"
                await asyncio.sleep(2.5)  # ticking panels rebuild cached content
                screenshot = app.export_screenshot().lower()
                assert "cba6f7" in screenshot
                assert "18e0e8" not in screenshot

                # ghost switches the app into the terminal's own colors.
                app.action_set_theme("ghost")
                await pilot.pause()
                assert app.ansi_color is True
        finally:
            palette.set_theme("tron")

    asyncio.run(scenario())


def test_startup_theme_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")

    async def scenario() -> None:
        from tachyon import palette

        app = TachyonApp(config=TachyonConfig(boot_enabled=False, theme="gruvbox"))
        try:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert palette.theme().name == "gruvbox"
                assert "83a598" in app.export_screenshot().lower()
        finally:
            palette.set_theme("tron")

    asyncio.run(scenario())


def test_selection_follows_tree_cursor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("TACHYON_NO_GEO", "1")
    (tmp_path / "aaa").mkdir()
    (tmp_path / "bbb").mkdir()

    async def scenario() -> None:
        config = TachyonConfig(boot_enabled=False, shell_cwd=tmp_path, filesystem_root=tmp_path)
        app = TachyonApp(config=config)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            browser = app.query_one(FileBrowser)
            tree = app.query_one(TachyonDirectoryTree)
            tree.focus()
            await pilot.pause()

            # The cursor IS the selection: CD HERE targets what you look at.
            await pilot.press("g")
            await pilot.press("j")
            assert browser.target_directory == tmp_path / "aaa"
            await pilot.press("j")
            assert browser.target_directory == tmp_path / "bbb"
            await pilot.press("k")
            assert browser.target_directory == tmp_path / "aaa"

    asyncio.run(scenario())
