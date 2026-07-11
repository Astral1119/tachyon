"""Repo telemetry: a git instrument that wakes up when the shell enters a repo."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from tachyon import palette
from tachyon.widgets.resize import EdgeResize


@dataclass(frozen=True)
class RepoState:
    """One sampled snapshot of the repository at a target directory."""

    in_repo: bool = False
    branch: str = ""
    ahead: int | None = None
    behind: int | None = None
    staged: int = 0
    dirty: int = 0
    untracked: int = 0
    commits: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _git(target: Path, *args: str) -> str | None:
    """Run a git plumbing command; returns raw stdout (columns matter for
    ``status --porcelain``, so callers strip when safe)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(target), *args],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def sample_repo(target: Path) -> RepoState:
    """Collect repo telemetry with plain git plumbing; safe off the UI thread."""
    in_tree = _git(target, "rev-parse", "--is-inside-work-tree")
    if in_tree is None or in_tree.strip() != "true":
        return RepoState()

    # symbolic-ref resolves an unborn branch (no commits yet); rev-parse can't.
    branch = (
        (_git(target, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
        or (_git(target, "symbolic-ref", "--short", "HEAD") or "").strip()
        or "?"
    )
    if branch == "HEAD":
        detached = (_git(target, "rev-parse", "--short", "HEAD") or "?").strip()
        branch = f"DETACHED @ {detached}"

    ahead: int | None = None
    behind: int | None = None
    counts = _git(target, "rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if counts is not None:
        with_parts = counts.strip().split()
        if len(with_parts) == 2:
            behind, ahead = int(with_parts[0]), int(with_parts[1])

    staged = dirty = untracked = 0
    status = _git(target, "status", "--porcelain")
    for line in (status or "").splitlines():
        if line.startswith("??"):
            untracked += 1
            continue
        if line[:1].strip():
            staged += 1
        if line[1:2].strip():
            dirty += 1

    commits: list[tuple[str, str]] = []
    log = _git(target, "log", "-3", "--format=%h\x1f%s")
    for line in (log or "").splitlines():
        digest, _, subject = line.partition("\x1f")
        commits.append((digest, subject))

    return RepoState(
        in_repo=True,
        branch=branch,
        ahead=ahead,
        behind=behind,
        staged=staged,
        dirty=dirty,
        untracked=untracked,
        commits=tuple(commits),
    )


class RepoPanel(EdgeResize, Static):
    """Contextual git instrument fed by the shell's working directory."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._target: Path | None = None
        self._state = RepoState()

    def on_mount(self) -> None:
        self.border_title = "◢ REPO TELEMETRY ◣"
        self.set_interval(5.0, self._tick)

    def set_target(self, path: Path) -> None:
        """Point the instrument at a directory (called on shell cwd changes)."""
        self._target = Path(path)
        self._tick()

    def _tick(self) -> None:
        target = self._target
        if target is None or not (self.region.width and self.region.height):
            return
        self.run_worker(
            lambda: self._collect(target),
            thread=True,
            exclusive=True,
            group="repo-scan",
            exit_on_error=False,
        )

    def _collect(self, target: Path) -> None:
        state = sample_repo(target)
        self.app.call_from_thread(self._apply, state)

    def _apply(self, state: RepoState) -> None:
        self._state = state
        self.border_subtitle = state.branch if state.in_repo else ""
        self.refresh()

    def render(self) -> Text:
        state = self._state
        width = max(self.content_size.width, 16)
        if not state.in_repo:
            height = max(self.content_size.height, 1)
            out = Text(no_wrap=True, overflow="crop")
            out.append("\n" * (height // 2))
            line = "◢ NO REPO SIGNAL ◣"
            out.append(" " * max((width - len(line)) // 2, 0))
            out.append(line, style=palette.DIM)
            return out

        out = Text(no_wrap=True, overflow="ellipsis")
        out.append("BRANCH ", style=palette.ACCENT_DIM)
        out.append(state.branch[: max(width - 7, 4)], style=f"bold {palette.ACCENT}")
        out.append("\n")

        if state.ahead is None:
            out.append("TRACK  ", style=palette.ACCENT_DIM)
            out.append("NO UPSTREAM", style=palette.DIM)
        else:
            out.append("TRACK  ", style=palette.ACCENT_DIM)
            out.append(f"↑{state.ahead} ", style=palette.OK if state.ahead else palette.DIM)
            out.append(f"↓{state.behind}", style=palette.HOT if state.behind else palette.DIM)
        out.append("\n")

        out.append("STAGE ", style=palette.ACCENT_DIM)
        out.append(f"{state.staged:<3}", style=palette.OK if state.staged else palette.DIM)
        out.append("DIRTY ", style=palette.ACCENT_DIM)
        out.append(f"{state.dirty:<3}", style=palette.WARN if state.dirty else palette.DIM)
        out.append("NEW ", style=palette.ACCENT_DIM)
        out.append(f"{state.untracked:<3}", style=palette.HOT if state.untracked else palette.DIM)

        for digest, subject in state.commits:
            out.append("\n")
            out.append(f"{digest} ", style=palette.DIM)
            out.append(subject[: max(width - len(digest) - 1, 4)], style=palette.TEXT)
        return out
