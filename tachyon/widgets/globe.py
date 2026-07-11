"""Uplink grid: a braille world map plotting live connection endpoints.

The landmass comes from a baked Natural Earth bitmap (see worldmap.py).
Remote endpoints are geolocated through ip-api.com (free, no key) with an
in-memory cache; set ``TACHYON_NO_GEO=1`` to keep every lookup off the
wire, in which case the map still renders and the header reports GEO OFF.
"""

from __future__ import annotations

import ipaddress
import json
import os
import urllib.request
from functools import lru_cache
from math import asin, atan2, cos, degrees, radians, sin, sqrt

from rich.text import Text
from textual.widgets import Static

from tachyon import palette
from tachyon.widgets.monitors import _telemetry_active
from tachyon.widgets.resize import EdgeResize
from tachyon.widgets.worldmap import HEIGHT as _MAP_HEIGHT
from tachyon.widgets.worldmap import LAT_BOTTOM as _LAT_BOTTOM
from tachyon.widgets.worldmap import LAT_TOP as _LAT_TOP
from tachyon.widgets.worldmap import WIDTH as _MAP_WIDTH
from tachyon.widgets.worldmap import bitmap as _world_bitmap
from tachyon.widgets.worldmap import sample as _sample_world

# Braille dot bit for sub-cell (dx, dy) within a 2x4 cell.
_BRAILLE_BITS = {
    (0, 0): 0x01,
    (0, 1): 0x02,
    (0, 2): 0x04,
    (0, 3): 0x40,
    (1, 0): 0x08,
    (1, 1): 0x10,
    (1, 2): 0x20,
    (1, 3): 0x80,
}

_GEO_BATCH_URL = "http://ip-api.com/batch?fields=status,lat,lon,query"
_GEO_SELF_URL = "http://ip-api.com/json/?fields=status,lat,lon"
_GEO_MAX_FAILURES = 3


def _project(lat: float, lon: float, width: int, height: int) -> tuple[int, int] | None:
    """Equirectangular lat/lon to a dot position, or None when off-grid."""
    if not (_LAT_BOTTOM <= lat <= _LAT_TOP) or not (-180.0 <= lon <= 180.0):
        return None
    x = int((lon + 180.0) / 360.0 * (width - 1))
    y = int((_LAT_TOP - lat) / (_LAT_TOP - _LAT_BOTTOM) * (height - 1))
    return x, y


def render_map(width: int, height: int) -> list[list[int]]:
    """Resample the baked landmass into a braille dot grid (width*2 x height*4)."""
    dots = _sample_world(width * 2, height * 4)
    grid = [[0] * width for _ in range(height)]
    for dy, row in enumerate(dots):
        for dx, land in enumerate(row):
            if land:
                grid[dy // 4][dx // 2] |= _BRAILLE_BITS[(dx % 2, dy % 4)]
    return grid


# Sentinels for dots outside the bitmap's latitude coverage.
_POLAR_WATER = -1  # above 84°N: Arctic ocean
_POLAR_LAND = -2  # below 60°S: Antarctica


@lru_cache(maxsize=4)
def _ortho_geometry(dots_w: int, dots_h: int) -> list[list[tuple[int, int] | bool | None]]:
    """Per-dot sphere geometry for an orthographic globe of the given size.

    Braille dots are approximately square (cells are ~1:2, split 2x4), so no
    aspect correction is needed.  Each entry is None (space), True (limb rim),
    or (bitmap_row, base_col) where the actual bitmap column at rotation θ is
    (base_col + θ·WIDTH/360) % WIDTH — rotation is just a column shift.
    """
    radius = min(dots_w, dots_h) / 2 - 0.5
    cx, cy = dots_w / 2, dots_h / 2
    cells: list[list[tuple[int, int] | bool | None]] = []
    for j in range(dots_h):
        row: list[tuple[int, int] | bool | None] = []
        for i in range(dots_w):
            nx = (i + 0.5 - cx) / radius
            ny = (j + 0.5 - cy) / radius
            d2 = nx * nx + ny * ny
            if d2 > 1.0:
                row.append(None)
                continue
            if d2 > 0.93:
                row.append(True)
                continue
            nz = sqrt(1.0 - d2)
            lat = degrees(asin(-ny))
            lon_rel = degrees(atan2(nx, nz))
            if lat > _LAT_TOP:
                row.append((_POLAR_WATER, 0))
            elif lat < _LAT_BOTTOM:
                row.append((_POLAR_LAND, 0))
            else:
                bitmap_row = int((_LAT_TOP - lat) / (_LAT_TOP - _LAT_BOTTOM) * (_MAP_HEIGHT - 1))
                base_col = int((lon_rel + 180.0) / 360.0 * _MAP_WIDTH) % _MAP_WIDTH
                row.append((bitmap_row, base_col))
        cells.append(row)
    return cells


def render_globe(width: int, height: int, rotation: float) -> list[list[int]]:
    """Rasterise the rotating orthographic globe into a braille char grid."""
    dots_w, dots_h = width * 2, height * 4
    geometry = _ortho_geometry(dots_w, dots_h)
    land = _world_bitmap()
    shift = int(rotation / 360.0 * _MAP_WIDTH) % _MAP_WIDTH
    grid = [[0] * width for _ in range(height)]
    for dy in range(dots_h):
        row = geometry[dy]
        for dx in range(dots_w):
            cell = row[dx]
            if cell is None:
                continue
            if cell is True:
                lit = (dx + dy) % 2 == 0  # sparse limb rim
            else:
                bitmap_row, base_col = cell
                if bitmap_row == _POLAR_WATER:
                    lit = False
                elif bitmap_row == _POLAR_LAND:
                    lit = True
                else:
                    lit = land[bitmap_row][(base_col + shift) % _MAP_WIDTH]
            if lit:
                grid[dy // 4][dx // 2] |= _BRAILLE_BITS[(dx % 2, dy % 4)]
    return grid


def _sphere_project(
    lat: float, lon: float, rotation: float, width: int, height: int
) -> tuple[int, int] | None:
    """Project lat/lon onto the front hemisphere; None when hidden or off-globe."""
    dots_w, dots_h = width * 2, height * 4
    radius = min(dots_w, dots_h) / 2 - 0.5
    lon_rel = radians(((lon - rotation + 540.0) % 360.0) - 180.0)
    lat_rad = radians(lat)
    z = cos(lat_rad) * cos(lon_rel)
    if z <= 0.05:
        return None
    x = cos(lat_rad) * sin(lon_rel)
    y = -sin(lat_rad)
    dot_x = int(dots_w / 2 + x * radius)
    dot_y = int(dots_h / 2 + y * radius)
    if not (0 <= dot_x < dots_w and 0 <= dot_y < dots_h):
        return None
    return dot_x // 2, dot_y // 4


def _lookup_batch(ips: list[str]) -> dict[str, tuple[float, float] | None]:
    """Blocking ip-api.com batch lookup; caller handles exceptions."""
    payload = json.dumps(ips[:50]).encode()
    request = urllib.request.Request(
        _GEO_BATCH_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=4.0) as response:
        results = json.load(response)
    located: dict[str, tuple[float, float] | None] = {}
    for entry in results:
        ip = entry.get("query")
        if not ip:
            continue
        if entry.get("status") == "success":
            located[ip] = (float(entry["lat"]), float(entry["lon"]))
        else:
            located[ip] = None
    return located


def _lookup_self() -> tuple[float, float] | None:
    with urllib.request.urlopen(_GEO_SELF_URL, timeout=4.0) as response:
        entry = json.load(response)
    if entry.get("status") == "success":
        return (float(entry["lat"]), float(entry["lon"]))
    return None


class GlobePanel(EdgeResize, Static):
    """World grid with live, geolocated uplink blips."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._targets: frozenset[str] = frozenset()
        self._cache: dict[str, tuple[float, float] | None] = {}
        self._home: tuple[float, float] | None = None
        self._home_resolved = False
        self._geo_enabled = not os.environ.get("TACHYON_NO_GEO")
        self._geo_failures = 0
        self._phase = False
        self._map_cache: tuple[tuple[int, int], list[list[int]]] | None = None
        self._orbit = True
        self._rotation = 210.0  # start facing the Pacific rim, it reads well

    def on_mount(self) -> None:
        self.border_title = "◢ UPLINK GRID ◣"
        self.set_interval(0.6, self._blink)
        self.set_interval(0.15, self._spin)
        self.set_interval(5.0, self._resolve_pending)

    def toggle_mode(self) -> bool:
        """Flip between the rotating globe and the flat chart; returns orbit state."""
        self._orbit = not self._orbit
        self.refresh()
        return self._orbit

    def _spin(self) -> None:
        if self._orbit and _telemetry_active(self):
            self._rotation = (self._rotation + 2.2) % 360.0
            self.refresh()

    @property
    def _geo_live(self) -> bool:
        return self._geo_enabled and self._geo_failures < _GEO_MAX_FAILURES

    def update_targets(self, ips: frozenset[str]) -> None:
        """Feed the current set of remote endpoint IPs (from CONNTRACK)."""
        public = frozenset(ip for ip in ips if self._is_public(ip))
        if public != self._targets:
            self._targets = public
            self.refresh()

    @staticmethod
    def _is_public(ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip).is_global
        except ValueError:
            return False

    def _blink(self) -> None:
        if self._plotted() and _telemetry_active(self):
            self._phase = not self._phase
            self.refresh()

    def _plotted(self) -> list[tuple[float, float]]:
        return [location for ip in self._targets if (location := self._cache.get(ip)) is not None]

    def _resolve_pending(self) -> None:
        if not self._geo_live or not _telemetry_active(self):
            return
        pending = [ip for ip in self._targets if ip not in self._cache]
        if not pending and self._home_resolved:
            return
        self.run_worker(
            lambda: self._resolve(pending),
            thread=True,
            exclusive=True,
            group="geo",
            exit_on_error=False,
        )

    def _resolve(self, pending: list[str]) -> None:
        home = self._home
        home_resolved = self._home_resolved
        try:
            if not home_resolved:
                home = _lookup_self()
                home_resolved = True
            located = _lookup_batch(pending) if pending else {}
        except (OSError, ValueError, json.JSONDecodeError):
            self.app.call_from_thread(self._apply_failure)
            return
        self.app.call_from_thread(self._apply_geo, home, home_resolved, located)

    def _apply_failure(self) -> None:
        self._geo_failures += 1
        self.refresh()

    def _apply_geo(
        self,
        home: tuple[float, float] | None,
        home_resolved: bool,
        located: dict[str, tuple[float, float] | None],
    ) -> None:
        self._geo_failures = 0
        self._home = home
        self._home_resolved = home_resolved
        self._cache.update(located)
        self.refresh()

    def _map(self, width: int, height: int) -> list[list[int]]:
        if self._map_cache is None or self._map_cache[0] != (width, height):
            self._map_cache = ((width, height), render_map(width, height))
        return self._map_cache[1]

    def render(self) -> Text:
        width = max(self.content_size.width, 24)
        height = max(self.content_size.height, 6)
        map_height = height - 1

        plotted = self._plotted()
        header = Text(no_wrap=True, overflow="ellipsis")
        header.append("ORBIT " if self._orbit else "CHART ", style=f"bold {palette.ACCENT}")
        header.append("UPLINKS ", style=palette.ACCENT_DIM)
        header.append(f"{len(self._targets):<4}", style=palette.TEXT)
        header.append("PLOTTED ", style=palette.ACCENT_DIM)
        header.append(f"{len(plotted):<4}", style=palette.ACCENT)
        if not self._geo_enabled:
            header.append("GEO OFF", style=palette.DIM)
        elif not self._geo_live:
            header.append("GEO OFFLINE", style=palette.HOT)

        overlays: dict[tuple[int, int], tuple[str, str]] = {}
        blip = "●" if self._phase else "◌"
        if self._orbit:
            grid = render_globe(width, map_height, self._rotation)
            if self._home is not None:
                spot = _sphere_project(*self._home, self._rotation, width, map_height)
                if spot is not None:
                    overlays[spot] = ("◎", f"bold {palette.ACCENT}")
            for lat, lon in plotted:
                spot = _sphere_project(lat, lon, self._rotation, width, map_height)
                if spot is not None:
                    overlays[spot] = (blip, f"bold {palette.HOT}")
        else:
            grid = self._map(width, map_height)
            if self._home is not None:
                spot = _project(*self._home, width * 2, map_height * 4)
                if spot is not None:
                    overlays[(spot[0] // 2, spot[1] // 4)] = ("◎", f"bold {palette.ACCENT}")
            for lat, lon in plotted:
                spot = _project(lat, lon, width * 2, map_height * 4)
                if spot is not None:
                    overlays[(spot[0] // 2, spot[1] // 4)] = (blip, f"bold {palette.HOT}")

        out = Text(no_wrap=True, overflow="crop")
        out.append(header)
        for row_index, row in enumerate(grid):
            out.append("\n")
            run: list[str] = []
            for col_index, cell in enumerate(row):
                overlay = overlays.get((col_index, row_index))
                if overlay is not None:
                    if run:
                        out.append("".join(run), style=palette.ACCENT_DIM)
                        run = []
                    out.append(overlay[0], style=overlay[1])
                else:
                    run.append(chr(0x2800 + cell) if cell else " ")
            if run:
                out.append("".join(run), style=palette.ACCENT_DIM)
        return out
