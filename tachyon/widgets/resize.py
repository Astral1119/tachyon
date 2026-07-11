"""Foundation-level grid resizing: drag any panel border, tmux-style.

``EdgeResize`` is a mixin for bordered widgets.  A mouse-down on the
widget's border cell starts a drag that resizes the appropriate fixed
dimension of the layout: vertical borders resolve to a column width in
the nearest ``Horizontal`` ancestor, horizontal borders to a panel height
in the nearest ``Vertical``.  Of the two children meeting at the dragged
boundary, the one with a fixed (cells) dimension is resized — the ``fr``
sibling absorbs the change, exactly like tmux pane splits.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import events
from textual.containers import Horizontal, Vertical
from textual.css.scalar import Unit
from textual.widget import Widget

_MIN_WIDTH = 16
_MAX_WIDTH = 100
_MIN_HEIGHT = 3
_MAX_HEIGHT = 50


@dataclass
class _Drag:
    target: Widget
    horizontal: bool
    sign: int
    start_size: int
    origin: int


def _has_fixed(widget: Widget, horizontal: bool) -> bool:
    scalar = widget.styles.width if horizontal else widget.styles.height
    return scalar is not None and scalar.unit == Unit.CELLS


class EdgeResize:
    """Mixin: border cells of this widget become drag handles for the grid."""

    _edge_drag: _Drag | None = None

    def _edge_at(self, x: int, y: int) -> str | None:
        width, height = self.region.width, self.region.height
        if width <= 2 or height <= 2:
            return None
        if x <= 0:
            return "left"
        if x >= width - 1:
            return "right"
        if y <= 0:
            return "top"
        if y >= height - 1:
            return "bottom"
        return None

    def _resolve_drag(self, edge: str, origin: int) -> _Drag | None:
        horizontal = edge in ("left", "right")
        container_type = Horizontal if horizontal else Vertical
        node: Widget = self
        while node.parent is not None and not isinstance(node.parent, container_type):
            if not isinstance(node.parent, Widget):
                return None
            node = node.parent
        parent = node.parent
        if parent is None:
            return None

        siblings = [child for child in parent.children if child.display]
        try:
            index = siblings.index(node)
        except ValueError:
            return None
        neighbor_index = index - 1 if edge in ("left", "top") else index + 1
        if not 0 <= neighbor_index < len(siblings):
            return None

        first, second = sorted((index, neighbor_index))
        before, after = siblings[first], siblings[second]
        if _has_fixed(before, horizontal):
            target, sign = before, 1
        elif _has_fixed(after, horizontal):
            target, sign = after, -1
        else:
            return None

        size = target.region.width if horizontal else target.region.height
        return _Drag(target, horizontal, sign, size, origin)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        edge = self._edge_at(event.x, event.y)
        if edge is None:
            return
        origin = event.screen_x if edge in ("left", "right") else event.screen_y
        drag = self._resolve_drag(edge, origin)
        if drag is None:
            return
        event.stop()
        self._edge_drag = drag
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        drag = self._edge_drag
        if drag is None:
            return
        event.stop()
        position = event.screen_x if drag.horizontal else event.screen_y
        size = drag.start_size + drag.sign * (position - drag.origin)
        if drag.horizontal:
            drag.target.styles.width = max(_MIN_WIDTH, min(_MAX_WIDTH, size))
        else:
            drag.target.styles.height = max(_MIN_HEIGHT, min(_MAX_HEIGHT, size))

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._edge_drag is None:
            return
        event.stop()
        self._edge_drag = None
        self.release_mouse()
