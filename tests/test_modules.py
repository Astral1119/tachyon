from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tachyon.widgets.globe import GlobePanel, _project, render_map
from tachyon.widgets.keys import tokens_for
from tachyon.widgets.repo import sample_repo


@pytest.mark.parametrize(
    ("key", "character", "expected"),
    [
        ("a", "a", ("a",)),
        ("A", "A", ("sft", "a")),
        ("question_mark", "?", ("sft", "/")),
        ("ctrl+c", None, ("ctl", "c")),
        ("enter", None, ("ret",)),
        ("space", " ", ("space",)),
        ("shift+tab", None, ("sft", "tab")),
        ("f5", None, ()),
    ],
)
def test_tokens_for(key: str, character: str | None, expected: tuple[str, ...]) -> None:
    assert tokens_for(key, character) == expected


def test_render_map_has_land_and_open_ocean() -> None:
    grid = render_map(60, 18)
    land = sum(1 for row in grid for cell in row if cell)
    assert land > 100
    # The south-central Pacific stays empty.
    assert grid[10][8] == 0


def test_project_bounds() -> None:
    assert _project(0.0, 0.0, 120, 72) is not None
    x_west, _ = _project(0.0, -179.9, 120, 72)
    x_east, _ = _project(0.0, 179.9, 120, 72)
    assert x_west < x_east
    assert _project(89.0, 0.0, 120, 72) is None  # above the crop
    assert _project(0.0, 181.0, 120, 72) is None


def test_globe_public_ip_filter() -> None:
    assert GlobePanel._is_public("8.8.8.8") is True
    assert GlobePanel._is_public("192.168.1.10") is False
    assert GlobePanel._is_public("127.0.0.1") is False
    assert GlobePanel._is_public("not-an-ip") is False


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_sample_repo(tmp_path: Path) -> None:
    assert sample_repo(tmp_path).in_repo is False

    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "op@tachyon.local")
    _git(tmp_path, "config", "user.name", "Operator")
    (tmp_path / "core.txt").write_text("online\n")
    _git(tmp_path, "add", "core.txt")
    _git(tmp_path, "commit", "-m", "ignite core")

    state = sample_repo(tmp_path)
    assert state.in_repo is True
    assert state.branch == "main"
    assert state.ahead is None  # no upstream
    assert state.staged == 0 and state.dirty == 0 and state.untracked == 0
    assert len(state.commits) == 1
    assert state.commits[0][1] == "ignite core"

    (tmp_path / "core.txt").write_text("meltdown\n")
    (tmp_path / "new.txt").write_text("fresh\n")
    state = sample_repo(tmp_path)
    assert state.dirty == 1
    assert state.untracked == 1


def test_render_globe_is_a_disc_that_rotates() -> None:
    from tachyon.widgets.globe import render_globe

    width, height = 40, 18
    grid = render_globe(width, height, 0.0)
    # Corners are space, the disc has content.
    assert grid[0][0] == 0 and grid[0][width - 1] == 0
    assert grid[height - 1][0] == 0 and grid[height - 1][width - 1] == 0
    lit = sum(1 for row in grid for cell in row if cell)
    assert lit > 50
    # A quarter turn shows different land.
    assert render_globe(width, height, 90.0) != grid
    # Antarctica (below the bitmap crop) renders as a solid southern cap.
    assert any(cell for cell in grid[height - 3])


def test_sphere_project_visibility() -> None:
    from tachyon.widgets.globe import _sphere_project

    width, height = 40, 18
    # Facing longitude 0: (0, 0) lands near the disc center...
    front = _sphere_project(0.0, 0.0, 0.0, width, height)
    assert front is not None
    x, y = front
    assert abs(x - width // 2) <= 2 and abs(y - height // 2) <= 2
    # ...and the antipode is hidden.
    assert _sphere_project(0.0, 180.0, 0.0, width, height) is None
    # Rotating the globe 180° swaps them.
    assert _sphere_project(0.0, 180.0, 180.0, width, height) is not None


def test_boot_banner_rows_align() -> None:
    from tachyon.widgets.boot import banner

    rows = banner().split("\n")
    assert len(rows) == 5
    assert len({len(row) for row in rows}) == 1  # rectangular art


def test_theme_registry_and_css_variables() -> None:
    from tachyon import palette

    assert palette.theme().name == "tron"
    for name, entry in palette.THEMES.items():
        assert entry.name == name
    try:
        applied = palette.set_theme("ghost")
        assert applied.ansi is True
        css = palette.css_variables()
        assert css["bg"] == "transparent"
        assert css["term-bg"] == "transparent"  # Rich "default" mapped for CSS
        assert "name" not in css and "description" not in css
    finally:
        palette.set_theme("tron")
