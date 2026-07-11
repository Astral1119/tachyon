from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from tachyon.widgets.files import (
    FileBrowser,
    TachyonDirectoryTree,
    _display_path,
    _human_bytes,
)


def test_display_path_compacts_home_and_sanitizes_controls() -> None:
    home = Path.home()

    assert _display_path(home) == "~"
    assert _display_path(home / "projects" / "tachyon") == "~/projects/tachyon"
    assert _display_path(home / "line\nbreak") == "~/line�break"


@pytest.mark.parametrize(
    ("size", "display"),
    [
        (-1, "0B"),
        (0, "0B"),
        (1_023, "1023B"),
        (1_024, "1K"),
        (1_024**2, "1.0M"),
        (1_024**3, "1.0G"),
    ],
)
def test_human_bytes(size: int, display: str) -> None:
    assert _human_bytes(size) == display


def test_directory_tree_filters_and_toggles_dotfiles(monkeypatch: pytest.MonkeyPatch) -> None:
    tree = object.__new__(TachyonDirectoryTree)
    tree._hidden_visible = False
    reload_tree = Mock()
    monkeypatch.setattr(TachyonDirectoryTree, "reload", reload_tree)
    paths = [Path("visible"), Path(".hidden"), Path("directory/.nested")]

    assert tree.hidden_visible is False
    assert list(tree.filter_paths(paths)) == [Path("visible")]

    assert tree.toggle_hidden() is True
    assert tree.hidden_visible is True
    assert list(tree.filter_paths(paths)) == paths

    assert tree.toggle_hidden() is False
    assert list(tree.filter_paths(paths)) == [Path("visible")]
    assert reload_tree.call_count == 2


def test_file_browser_target_directory_semantics(tmp_path: Path) -> None:
    browser = object.__new__(FileBrowser)
    selected_directory = tmp_path / "directory"
    selected_file = selected_directory / "file.txt"

    browser._selected_path = selected_directory
    browser._selected_is_directory = True
    assert browser.selected_path == selected_directory
    assert browser.target_directory == selected_directory

    browser._selected_path = selected_file
    browser._selected_is_directory = False
    assert browser.selected_path == selected_file
    assert browser.target_directory == selected_directory


def test_path_changed_exposes_target_directory(tmp_path: Path) -> None:
    selected_directory = tmp_path / "directory"
    selected_file = selected_directory / "file.txt"

    directory_change = FileBrowser.PathChanged(selected_directory, is_directory=True)
    file_change = FileBrowser.PathChanged(selected_file, is_directory=False)

    assert directory_change.path == selected_directory
    assert directory_change.target_directory == selected_directory
    assert directory_change.is_directory is True
    assert file_change.path == selected_file
    assert file_change.target_directory == selected_directory
    assert file_change.is_directory is False
