"""Left-column system monitor panels: system info, CPU, memory, processes."""

from __future__ import annotations

import math
import platform
import subprocess
from collections import deque
from contextlib import suppress

import psutil
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Sparkline, Static

from tachyon import palette
from tachyon.widgets.resize import EdgeResize


def _telemetry_active(widget: Widget) -> bool:
    """Return whether a visible panel should spend work sampling sensors."""

    try:
        return bool(getattr(widget.app, "telemetry_active", True)) and bool(
            widget.region.width and widget.region.height
        )
    except Exception:
        return True


def _load_color(pct: float) -> str:
    if pct >= 80:
        return palette.HOT
    if pct >= 50:
        return palette.ACCENT
    return palette.OK


def _bar(pct: float, width: int) -> Text:
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    bar = Text()
    bar.append("▓" * filled, style=_load_color(pct))
    bar.append("░" * (width - filled), style=palette.DIM)
    return bar


class SystemPanel(EdgeResize, Static):
    """OS / kernel / CPU model / load / process count."""

    _cpu_model: str | None = None

    def on_mount(self) -> None:
        self.border_title = "◢ SYSTEM ◣"
        if SystemPanel._cpu_model is None:
            SystemPanel._cpu_model = self._detect_cpu_model()
        self.set_interval(5.0, self._tick)

    def _tick(self) -> None:
        if _telemetry_active(self):
            self.refresh()

    @staticmethod
    def _detect_cpu_model() -> str:
        try:
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
        return platform.processor() or "unknown"

    def render(self) -> Text:
        if platform.system() == "Darwin":
            os_line = f"macOS {platform.mac_ver()[0]}"
        else:
            os_line = f"{platform.system()} {platform.release()}"
        kernel = f"{platform.system()} {platform.release()} {platform.machine()}"
        try:
            # psutil emulates load averages on Windows, where os.getloadavg
            # does not exist at all.
            load = " ".join(f"{v:.2f}" for v in psutil.getloadavg())
        except (OSError, AttributeError):
            load = "—"
        nproc = len(psutil.pids())
        rows = [
            ("OS", os_line),
            ("KRNL", kernel),
            ("CPU", SystemPanel._cpu_model or "unknown"),
            ("LOAD", load),
            ("PROCS", f"{nproc} TRACKED"),
        ]
        text = Text(no_wrap=True)
        width = max(self.content_size.width, 10)
        for i, (label, value) in enumerate(rows):
            if i:
                text.append("\n")
            text.append(f"{label:<6}", style=palette.ACCENT_DIM)
            text.append(value[: width - 6], style=palette.TEXT)
        return text


class _CoreGrid(Static):
    """Per-core load bars, packed to fit."""

    cores: list[float] = []

    def render(self) -> Text:
        cores = self.cores
        if not cores:
            return Text("...", style=palette.DIM)
        width = max(self.content_size.width, 12)
        height = max(self.size.height, 1)
        per_line = max(math.ceil(len(cores) / height), 1)
        # Each cell: "NN " + bar; cells separated by two spaces.
        bar_w = max((width - 2 * (per_line - 1)) // per_line - 3, 3)
        text = Text(no_wrap=True)
        for i, pct in enumerate(cores):
            if i and i % per_line == 0:
                text.append("\n")
            elif i % per_line:
                text.append("  ")
            text.append(f"{i:02d} ", style=palette.DIM)
            text.append(_bar(pct, bar_w))
        return text


class CpuPanel(EdgeResize, Widget):
    """Overall CPU load sparkline + per-core bars."""

    DEFAULT_CSS = """
    CpuPanel { layout: vertical; }
    CpuPanel > #cpu-headline { height: 1; }
    CpuPanel > Sparkline { height: 2; }
    CpuPanel > Sparkline > .sparkline--min-color { color: $accent-dim; }
    CpuPanel > Sparkline > .sparkline--max-color { color: $hot; }
    CpuPanel > _CoreGrid { height: 1fr; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: deque[float] = deque([0.0] * 60, maxlen=60)

    def compose(self) -> ComposeResult:
        yield Static(id="cpu-headline")
        yield Sparkline(list(self._history), summary_function=max)
        yield _CoreGrid()

    def on_mount(self) -> None:
        self.border_title = "◢ CPU CORES ◣"
        psutil.cpu_percent(percpu=True)  # prime the delta
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        if not _telemetry_active(self):
            return
        try:
            percpu = psutil.cpu_percent(percpu=True)
        except Exception:
            return
        overall = sum(percpu) / max(len(percpu), 1)
        self._history.append(overall)
        headline = Text(no_wrap=True)
        headline.append("LOAD ", style=palette.ACCENT_DIM)
        headline.append(f"{overall:5.1f}%", style=f"bold {_load_color(overall)}")
        freq = None
        with suppress(Exception):
            freq = psutil.cpu_freq()
        if freq and freq.current >= 100:
            headline.append(f"  {freq.current / 1000:.2f} GHz", style=palette.DIM)
        self.query_one("#cpu-headline", Static).update(headline)
        self.query_one(Sparkline).data = list(self._history)
        grid = self.query_one(_CoreGrid)
        grid.cores = percpu
        grid.refresh()


class MemPanel(EdgeResize, Static):
    """RAM and swap gauges."""

    def on_mount(self) -> None:
        self.border_title = "◢ MEMORY ◣"
        self.set_interval(2.0, self._tick)

    def _tick(self) -> None:
        if _telemetry_active(self):
            self.refresh()

    def render(self) -> Text:
        width = max(self.content_size.width, 12)
        text = Text(no_wrap=True)
        try:
            vm = psutil.virtual_memory()
            sw = psutil.swap_memory()
        except Exception:
            return Text("unavailable", style=palette.DIM)
        gib = 1024**3
        used = (vm.total - vm.available) / gib
        text.append("MEM  ", style=palette.ACCENT_DIM)
        text.append(f"{used:5.1f}", style=palette.TEXT)
        text.append(f" / {vm.total / gib:.1f} GB", style=palette.DIM)
        text.append(f"  {vm.percent:.0f}%", style=_load_color(vm.percent))
        text.append("\n")
        text.append(_bar(vm.percent, width))
        text.append("\n")
        text.append("SWAP ", style=palette.ACCENT_DIM)
        text.append(f"{sw.used / gib:5.1f}", style=palette.TEXT)
        text.append(f" / {sw.total / gib:.1f} GB", style=palette.DIM)
        if sw.total:
            text.append(f"  {sw.percent:.0f}%", style=_load_color(sw.percent))
        text.append("\n")
        text.append(_bar(sw.percent if sw.total else 0.0, width))
        return text


class ProcessPanel(EdgeResize, Static):
    """Top processes by CPU."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows: list[tuple[int, float, float, str]] = []

    def on_mount(self) -> None:
        self.border_title = "◢ PROCESSES ◣"
        self.call_after_refresh(self._tick)  # wait for a visible layout region
        self.set_interval(2.0, self._tick)

    def _tick(self) -> None:
        if not _telemetry_active(self):
            return
        # Walking the process table takes ~40ms — keep it off the UI thread.
        self.run_worker(self._collect, thread=True, exclusive=True, group="proc-scan")

    def _collect(self) -> None:
        rows = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                info = proc.info
                rows.append(
                    (
                        info["pid"],
                        info["cpu_percent"] or 0.0,
                        info["memory_percent"] or 0.0,
                        info["name"] or "?",
                    )
                )
        except Exception:
            return
        # CPU is the primary signal; memory keeps an idle machine informative
        # instead of filling the table with arbitrary zero-CPU kernel tasks.
        rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
        self.app.call_from_thread(self._apply, rows)

    def _apply(self, rows: list[tuple[int, float, float, str]]) -> None:
        self._rows = rows
        self.border_subtitle = f"{len(rows)} TASKS"
        self.refresh()

    def render(self) -> Text:
        width = max(self.content_size.width, 20)
        height = max(self.size.height, 2)
        name_w = max(width - 17, 4)
        text = Text(no_wrap=True)
        heading = f"{'PID':>5} {'CPU%':>5} {'MEM%':>4} {'NAME':<{name_w}}"
        text.append(heading[:width], style=palette.ACCENT_DIM)
        for pid, cpu, mem, name in self._rows[: height - 1]:
            text.append("\n")
            text.append(f"{pid:>5} ", style=palette.DIM)
            text.append(f"{min(cpu, 999.9):>5.1f} ", style=_load_color(cpu))
            text.append(f"{mem:>4.1f} ", style=palette.TEXT)
            text.append(name[:name_w], style=palette.ACCENT)
        return text
