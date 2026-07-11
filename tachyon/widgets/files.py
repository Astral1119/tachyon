"""Filesystem browser with compact selection metadata."""

from __future__ import annotations

import stat
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DirectoryTree, Static

from tachyon import palette
from tachyon.widgets.resize import EdgeResize


def _display_path(path: Path) -> str:
    """Return a compact, single-line display path."""
    try:
        relative = path.relative_to(Path.home())
    except ValueError:
        shown = str(path)
    else:
        shown = "~" if not relative.parts else f"~/{relative}"
    return "".join(character if character.isprintable() else "�" for character in shown)


def _human_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return f"{value:.0f}{unit}" if unit in ("B", "K") else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


class TachyonDirectoryTree(DirectoryTree):
    """Directory tree using terminal-safe glyphs, vim motions, and optional dotfiles."""

    ICON_NODE = "▸ "
    ICON_NODE_EXPANDED = "▾ "
    ICON_FILE = "◇ "

    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("h", "vim_left", "collapse / parent", show=False),
        Binding("l", "vim_right", "expand / select", show=False),
        Binding("g", "cursor_top", "top", show=False),
        Binding("G", "cursor_bottom", "bottom", show=False),
        Binding("full_stop", "toggle_dotfiles", "dotfiles", show=False),
    ]

    def __init__(self, path: str | Path, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self._hidden_visible = False

    @property
    def hidden_visible(self) -> bool:
        """Whether dotfiles are currently included in the tree."""
        return self._hidden_visible

    def toggle_hidden(self) -> bool:
        """Toggle dotfile visibility, reload the tree, and return the new state."""
        self._hidden_visible = not self._hidden_visible
        self.reload()
        return self._hidden_visible

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        if self._hidden_visible:
            return paths
        return (path for path in paths if not path.name.startswith("."))

    # ------------------------------------------------------------ vim motions

    def action_vim_left(self) -> None:
        """Collapse the current directory, step to its parent, or re-root up."""
        node = self.cursor_node
        if node is None or node is self.root:
            self.root_up()
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.move_cursor(node.parent)

    def root_up(self) -> None:
        """Re-root the tree one directory up (netrw-style free navigation)."""
        here = Path(self.path).expanduser()
        parent = here.parent
        if parent != here:
            self.path = parent

    def action_vim_right(self) -> None:
        """Expand a directory, descend into it, or select a file."""
        node = self.cursor_node
        if node is None:
            return
        if not node.allow_expand:
            self.action_select_cursor()
        elif not node.is_expanded:
            node.expand()
        elif node.children:
            self.move_cursor(node.children[0])

    def action_cursor_top(self) -> None:
        self.move_cursor_to_line(0)

    def action_cursor_bottom(self) -> None:
        self.move_cursor_to_line(self.last_line)

    def action_toggle_dotfiles(self) -> None:
        # Route through the app action when available so the hint bar
        # confirms the new state; the tree alone gives no flash.
        action = getattr(self.app, "action_toggle_hidden", None)
        if action is not None:
            action()
        elif isinstance(self.parent, FileBrowser):
            self.parent.toggle_hidden()
        else:
            self.toggle_hidden()


class FileBrowser(EdgeResize, Vertical):
    """Themed filesystem panel rooted at ``root`` (``$HOME`` by default)."""

    BORDER_TITLE = "◢ FILESYSTEM ◣"

    class PathChanged(Message):
        """Posted when the user selects a file or directory."""

        def __init__(self, path: Path, *, is_directory: bool) -> None:
            self.path = path
            self.is_directory = is_directory
            self.target_directory = path if is_directory else path.parent
            super().__init__()

    DEFAULT_CSS = """
    FileBrowser {
        border-subtitle-color: $accent-dim;
    }
    FileBrowser > #files-status {
        height: 1;
        color: $text;
    }
    FileBrowser > TachyonDirectoryTree {
        height: 1fr;
        background: transparent;
        color: $text;
        scrollbar-size-vertical: 1;
        scrollbar-color: $accent-dim;
        scrollbar-background: $panel-bg;
    }
    FileBrowser TachyonDirectoryTree > .tree--guides { color: $dim; }
    FileBrowser TachyonDirectoryTree > .tree--guides-hover { color: $accent-dim; }
    FileBrowser TachyonDirectoryTree > .tree--guides-selected { color: $accent; }
    FileBrowser TachyonDirectoryTree > .tree--cursor {
        background: $accent-dim 40%;
        color: $accent;
        text-style: bold;
    }
    FileBrowser TachyonDirectoryTree > .directory-tree--folder { color: $accent; }
    FileBrowser TachyonDirectoryTree > .directory-tree--extension { color: $dim; }
    FileBrowser TachyonDirectoryTree > .directory-tree--hidden { color: $dim; }
    """

    def __init__(self, root: str | Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root = Path(root).expanduser() if root is not None else Path.home()
        self._selected_path = self._root
        self._selected_is_directory = True
        self._shell_linked = False
        self._status = Static(id="files-status")
        self._tree = TachyonDirectoryTree(self._root)

    @property
    def selected_path(self) -> Path:
        """The file or directory most recently selected by the user."""
        return self._selected_path

    @property
    def target_directory(self) -> Path:
        """The selected directory, or the parent of the selected file."""
        if self._selected_is_directory:
            return self._selected_path
        return self._selected_path.parent

    @property
    def hidden_visible(self) -> bool:
        """Whether dotfiles are currently included in the tree."""
        return self._tree.hidden_visible

    def compose(self) -> ComposeResult:
        yield self._status
        yield self._tree

    def on_mount(self) -> None:
        self.border_title = self.BORDER_TITLE
        self._update_path_chrome()

    def focus_tree(self) -> None:
        self._tree.focus()

    def toggle_hidden(self) -> bool:
        """Toggle dotfile visibility and return the new state."""
        visible = self._tree.toggle_hidden()
        self._update_status()
        return visible

    def follow(self, path: Path) -> None:
        """Mirror the shell's working directory without fighting the user.

        Re-roots the tree at the shell's cwd — an interactive ``ls`` of
        wherever the shell is — unless the operator is navigating the tree.
        Selection quietly retargets too (no PathChanged chatter).
        """
        if self._tree.has_focus or not path.is_dir():
            return
        path = Path(path)
        self._selected_path = path
        self._selected_is_directory = True
        self._shell_linked = True
        self._update_path_chrome()
        if Path(self._tree.path).expanduser() != path:
            self._tree.path = path

    def _select_path(self, path: Path, *, is_directory: bool) -> None:
        self._selected_path = Path(path)
        self._selected_is_directory = is_directory
        self._shell_linked = False
        self._update_path_chrome()
        self.post_message(self.PathChanged(self._selected_path, is_directory=is_directory))

    def _update_path_chrome(self) -> None:
        shown = _display_path(self._selected_path)
        subtitle = Text(no_wrap=True, overflow="ellipsis")
        subtitle.append("◢ ", style=palette.DIM)
        subtitle.append(shown, style=palette.ACCENT_DIM)
        subtitle.append(" ◣", style=palette.DIM)
        self.border_subtitle = subtitle
        self._update_status()

    def _update_status(self) -> None:
        kind = "⌁SH " if self._shell_linked else ("DIR " if self._selected_is_directory else "FILE")
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append(f"{kind:<4}", style=f"bold {palette.ACCENT}")
        line.append("HIDDEN ", style=palette.DIM)
        line.append(
            "ON" if self.hidden_visible else "OFF",
            style=palette.ACCENT if self.hidden_visible else palette.DIM,
        )

        try:
            info = self._selected_path.stat()
            mode = stat.filemode(info.st_mode)[1:]
            modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            line.append("  ·  metadata unavailable", style=palette.DIM)
        else:
            if not self._selected_is_directory:
                line.append(f"  ·  {_human_bytes(info.st_size)}", style=palette.TEXT)
            line.append(f"  ·  {mode}", style=palette.ACCENT_DIM)
            line.append(f"  ·  {modified}", style=palette.DIM)

        self._status.update(line)

    def on_tree_node_highlighted(self, event) -> None:
        """Selection follows the cursor: 'CD HERE' means what you're looking at.

        Quiet (no PathChanged chatter) so traversing with j/k doesn't spam
        the hint bar; explicit ENTER still announces the target.
        """
        entry = getattr(event.node, "data", None)
        if entry is None:
            return
        path = Path(entry.path)
        if path == self._selected_path:
            return
        self._selected_path = path
        self._selected_is_directory = path.is_dir()
        self._shell_linked = False
        self._update_path_chrome()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        self._select_path(event.path, is_directory=False)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()
        self._select_path(event.path, is_directory=True)
