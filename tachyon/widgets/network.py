"""Right-column panels: network throughput, live connections, disk array."""

from __future__ import annotations

import getpass
import os
import socket
import sys
from collections import Counter, deque
from collections.abc import Iterable
from contextlib import suppress
from time import monotonic
from typing import Any

import psutil
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Sparkline, Static

from tachyon import palette
from tachyon.widgets.resize import EdgeResize

_PSEUDO_FILESYSTEMS = {
    "autofs",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devfs",
    "devpts",
    "devtmpfs",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "nsfs",
    "overlay",
    "proc",
    "pstore",
    "ramfs",
    "securityfs",
    "squashfs",
    "sysfs",
    "tmpfs",
    "tracefs",
}


def _telemetry_enabled(widget: Widget) -> bool:
    """Return whether a mounted, visible panel should sample its sensors."""
    try:
        active = getattr(widget.app, "telemetry_active", True)
    except Exception:
        return False
    region = widget.region
    return bool(active and region.width > 0 and region.height > 0)


def _fit(text: Text, width: int, *, overflow: str = "ellipsis") -> Text:
    """Crop one display row to its content width and prohibit wrapping."""
    text.no_wrap = True
    text.overflow = overflow
    text.truncate(max(width, 0), overflow=overflow)
    return text


def _human_rate(bps: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024 or unit == "GB/s":
            return f"{bps:.1f} {unit}" if unit != "B/s" else f"{bps:.0f} {unit}"
        bps /= 1024
    return f"{bps:.1f} GB/s"


def _human_bytes(n: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 53))  # no packets sent; resolves routing only
            return sock.getsockname()[0]
    except OSError:
        return "0.0.0.0"


class NetPanel(EdgeResize, Vertical):
    """Interface identity plus live RX/TX rate sparklines."""

    DEFAULT_CSS = """
    NetPanel Static { height: 1; }
    NetPanel Sparkline { height: 2; }
    NetPanel #net-rx-spark > .sparkline--max-color { color: $accent; }
    NetPanel #net-rx-spark > .sparkline--min-color { color: $accent-dim; }
    NetPanel #net-tx-spark > .sparkline--max-color { color: $hot; }
    NetPanel #net-tx-spark > .sparkline--min-color { color: $accent-dim; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rx_hist: deque[float] = deque([0.0] * 28, maxlen=28)
        self._tx_hist: deque[float] = deque([0.0] * 28, maxlen=28)
        self._last: tuple[int, int] | None = None
        self._last_at: float | None = None
        self._last_source: str | None = None
        self._iface = "?"
        self._ip = "0.0.0.0"
        self._iface_age = 999

    def compose(self) -> ComposeResult:
        yield Static(id="net-info")
        yield Static(id="net-rx-label")
        yield Sparkline(list(self._rx_hist), summary_function=max, id="net-rx-spark")
        yield Static(id="net-tx-label")
        yield Sparkline(list(self._tx_hist), summary_function=max, id="net-tx-spark")
        yield Static(id="net-totals")

    def on_mount(self) -> None:
        self.border_title = "◢ NETWORK ◣"
        self.call_after_refresh(self._tick)
        self.set_interval(1.0, self._tick)

    def _refresh_iface(self) -> None:
        ip = _local_ip()
        iface = "?"
        try:
            for name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address == ip:
                        iface = name
                        break
                if iface != "?":
                    break
        except OSError:
            pass

        if (iface, ip) != (self._iface, self._ip):
            self._last = None
            self._last_at = None
            self._last_source = None
        self._iface = iface
        self._ip = ip

    def _tick(self) -> None:
        if not _telemetry_enabled(self):
            # Never average a hidden/paused interval into the next visible rate.
            self._last = None
            self._last_at = None
            self._last_source = None
            return
        try:
            self._iface_age += 1
            if self._iface_age >= 5:
                self._iface_age = 0
                self._refresh_iface()
            per_nic = psutil.net_io_counters(pernic=True)
            now = per_nic.get(self._iface)
            source = self._iface
            if now is None:
                now = psutil.net_io_counters()
                source = "*"
            if now is None:
                return

            sampled_at = monotonic()
            counters = (now.bytes_recv, now.bytes_sent)
            if source != self._last_source:
                self._last = None
                self._last_at = None
                self._rx_hist.append(0.0)
                self._tx_hist.append(0.0)
            if self._last is not None and self._last_at is not None:
                elapsed = sampled_at - self._last_at
                if elapsed > 0:
                    self._rx_hist.append(max(counters[0] - self._last[0], 0) / elapsed)
                    self._tx_hist.append(max(counters[1] - self._last[1], 0) / elapsed)
            self._last = counters
            self._last_at = sampled_at
            self._last_source = source

            info = Text()
            info.append("IFACE ", style=palette.DIM)
            info.append(self._iface, style=f"bold {palette.ACCENT}")
            info.append("  ", style=palette.DIM)
            info.append(self._ip, style=palette.TEXT)

            rx_label = Text()
            rx_label.append("▼ RX ", style=palette.ACCENT)
            rx_label.append(_human_rate(self._rx_hist[-1]), style=f"bold {palette.TEXT}")

            tx_label = Text()
            tx_label.append("▲ TX ", style=palette.HOT)
            tx_label.append(_human_rate(self._tx_hist[-1]), style=f"bold {palette.TEXT}")

            totals = Text()
            totals.append("Σ ", style=palette.DIM)
            totals.append(f"▼{_human_bytes(now.bytes_recv)} ", style=palette.ACCENT_DIM)
            totals.append(f"▲{_human_bytes(now.bytes_sent)}", style=palette.ACCENT_DIM)

            width = self.content_size.width
            with self.app.batch_update():
                self.query_one("#net-info", Static).update(_fit(info, width))
                self.query_one("#net-rx-label", Static).update(_fit(rx_label, width))
                self.query_one("#net-rx-spark", Sparkline).data = list(self._rx_hist)
                self.query_one("#net-tx-label", Static).update(_fit(tx_label, width))
                self.query_one("#net-tx-spark", Sparkline).data = list(self._tx_hist)
                self.query_one("#net-totals", Static).update(_fit(totals, width))
        except Exception:  # a sensor tick must never take the UI down
            pass


_STATUS_ABBR = {
    "ESTABLISHED": ("ESTAB", palette.OK),
    "LISTEN": ("LSTN", palette.ACCENT_DIM),
    "TIME_WAIT": ("TW", palette.DIM),
    "CLOSE_WAIT": ("CW", palette.WARN),
    "SYN_SENT": ("SYN", palette.WARN),
    "FIN_WAIT1": ("FIN1", palette.DIM),
    "FIN_WAIT2": ("FIN2", palette.DIM),
    "LAST_ACK": ("LACK", palette.DIM),
    "CLOSING": ("CLSG", palette.DIM),
    "NONE": ("-", palette.DIM),
}

_STATUS_ORDER = {"ESTABLISHED": 0, "SYN_SENT": 1, "CLOSE_WAIT": 2, "TIME_WAIT": 3, "LISTEN": 4}


def _format_endpoint(address: Any, *, empty: str) -> str:
    """Render psutil's IPv4/IPv6 address tuple unambiguously."""
    if not address:
        return empty
    try:
        host, port = address.ip, address.port
    except AttributeError:
        host, port = address[0], address[1]
    host = str(host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


class ConnectionsPanel(EdgeResize, Static):
    """Live TCP connection table, degraded gracefully when unprivileged."""

    class RemotesSampled(Message):
        """The set of remote endpoint IPs seen in the latest scan."""

        def __init__(self, ips: frozenset[str]) -> None:
            self.ips = ips
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows: list[tuple[str, str, str, int]] = []
        self._established = 0
        self._use_fallback = False
        self._scanned = False

    def on_mount(self) -> None:
        self.border_title = "◢ CONNTRACK ◣"
        self.call_after_refresh(self._poll)
        self.set_interval(3.0, self._poll)

    def _poll(self) -> None:
        if not _telemetry_enabled(self):
            return
        self.run_worker(
            self._collect,
            thread=True,
            exclusive=True,
            group="conntrack",
            exit_on_error=False,
        )

    def _collect(self) -> None:
        conns = []
        if not self._use_fallback:
            try:
                conns = psutil.net_connections(kind="tcp")
            except (psutil.AccessDenied, PermissionError, OSError):
                self._use_fallback = True
        if self._use_fallback:
            me = getpass.getuser()
            for proc in psutil.process_iter(["username"]):
                try:
                    if proc.info["username"] != me:
                        continue
                    getter = getattr(proc, "net_connections", None) or proc.connections
                    conns.extend(getter(kind="tcp"))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except OSError:
                    continue
        counts: Counter[tuple[str, str, str]] = Counter()
        remotes: set[str] = set()
        for c in conns:
            try:
                laddr = _format_endpoint(c.laddr, empty="-")
                raddr = _format_endpoint(c.raddr, empty="*")
                status = str(c.status or "NONE").upper()
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
            remote_ip = getattr(c.raddr, "ip", None) if c.raddr else None
            if remote_ip:
                remotes.add(str(remote_ip))
            # The table renders remote endpoints for connected sockets and
            # local endpoints for listeners. Aggregate by that visible target
            # so parallel browser/service sockets read as one useful signal.
            visible_key = ("", raddr, status) if raddr != "*" else (laddr, "*", status)
            counts[visible_key] += 1

        established = sum(
            count for (_, _, status), count in counts.items() if status == "ESTABLISHED"
        )
        payload = [(*row, count) for row, count in counts.items()]
        payload.sort(
            key=lambda row: (
                _STATUS_ORDER.get(row[2], 9),
                -row[3],
                row[1] if row[1] != "*" else row[0],
            )
        )
        with suppress(RuntimeError):
            self.app.call_from_thread(self._apply, payload, established, frozenset(remotes))

    def _apply(
        self,
        rows: list[tuple[str, str, str, int]],
        established: int,
        remotes: frozenset[str] = frozenset(),
    ) -> None:
        self._rows = rows
        self._established = established
        self._scanned = True
        # The border title is deck chrome owned by the app; live counts
        # belong in the subtitle so numbered titles stay stable.
        self.border_subtitle = f"{established} LIVE"
        self.post_message(self.RemotesSampled(remotes))
        self.refresh()

    def render(self) -> Text:
        width = self.content_size.width
        height = self.content_size.height
        out = Text(no_wrap=True, overflow="crop")
        if width <= 0 or height <= 0:
            return out
        if not self._rows:
            out.append("no tcp sockets" if self._scanned else "scanning…", style=palette.DIM)
            return out
        for i, (laddr, raddr, status, count) in enumerate(self._rows[:height]):
            abbr, color = _STATUS_ABBR.get(status, (status[:5], palette.DIM))
            target = raddr if raddr != "*" else laddr
            count_text = f"×{count}" if count > 1 else ""
            show_count = bool(count_text and width >= len(abbr) + len(count_text) + 3)
            tail = f"{count_text} {abbr}" if show_count else abbr
            room = max(width - len(tail) - 1, 1)
            if len(target) > room:
                target = "…" if room == 1 else "…" + target[-(room - 1) :]
            line = Text()
            target_style = palette.TEXT if status == "ESTABLISHED" else palette.DIM
            line.append(target.ljust(room), style=target_style)
            line.append(" ")
            if show_count:
                line.append(count_text, style=palette.ACCENT_DIM)
                line.append(" ")
            line.append(abbr, style=color)
            _fit(line, width, overflow="crop")
            if i:
                out.append("\n")
            out.append(line)
        return out


def _is_under(path: str, parent: str) -> bool:
    path = os.path.normpath(path)
    parent = os.path.normpath(parent)
    return path == parent or path.startswith(parent + os.sep)


def _visible_partitions(partitions: Iterable[Any], *, platform: str = sys.platform) -> list[Any]:
    """Filter pseudo/system mounts and collapse duplicate devices or paths."""
    visible: list[Any] = []
    seen_devices: set[str] = set()
    seen_mounts: set[str] = set()

    for part in partitions:
        mountpoint = os.path.normpath(str(part.mountpoint))
        fstype = str(getattr(part, "fstype", "")).lower()
        if not mountpoint.startswith(os.sep) or fstype in _PSEUDO_FILESYSTEMS:
            continue
        if any(_is_under(mountpoint, root) for root in ("/dev", "/proc", "/run", "/sys")):
            continue
        if platform == "darwin" and not (mountpoint == "/" or _is_under(mountpoint, "/Volumes")):
            continue

        mount_key = os.path.normcase(os.path.abspath(mountpoint))
        device = str(getattr(part, "device", ""))
        if device.casefold() in {"", "-", "none", "rootfs"}:
            device_key = ""
        elif device.startswith(os.sep):
            device_key = os.path.normcase(os.path.realpath(device))
        else:
            device_key = device.casefold()
        if mount_key in seen_mounts or (device_key and device_key in seen_devices):
            continue

        seen_mounts.add(mount_key)
        if device_key:
            seen_devices.add(device_key)
        visible.append(part)

    visible.sort(
        key=lambda part: (
            os.path.normpath(str(part.mountpoint)) != "/",
            str(part.mountpoint),
        )
    )
    return visible


def _disk_label(mountpoint: str, device: str) -> str:
    if os.path.normpath(mountpoint) == "/":
        return "ROOT"
    label = os.path.basename(os.path.normpath(mountpoint))
    if not label:
        label = os.path.basename(device)
    return (label or "VOLUME").upper()


def _disk_row(label: str, pct: float, free: int, width: int) -> Text:
    """Build one exact-width volume row which will never wrap."""
    row = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return row

    pct = max(0.0, min(100.0, pct))
    pct_text = f"{pct:3.0f}%"
    free_text = _human_bytes(free)
    label_width = min(7, max(2, width // 4))
    show_free = width >= 18
    fixed_width = label_width + 6 + (1 + len(free_text) if show_free else 0)
    bar_width = max(width - fixed_width, 1)
    filled = round(bar_width * pct / 100)
    color = palette.OK if pct < 70 else palette.WARN if pct < 90 else palette.HOT

    row.append(f"{label:<{label_width}.{label_width}}", style=palette.TEXT)
    row.append(" ")
    row.append("▰" * filled, style=color)
    row.append("▱" * (bar_width - filled), style=palette.DIM)
    row.append(" ")
    row.append(pct_text, style=color)
    if show_free:
        row.append(" ")
        row.append(free_text, style=palette.ACCENT_DIM)
    return _fit(row, width, overflow="crop")


class DiskPanel(EdgeResize, Static):
    """Mounted volumes with usage bars."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._disks: list[tuple[str, float, int]] = []  # label, pct, free
        self._last_io: tuple[int, int] | None = None
        self._last_io_at: float | None = None
        self._read_rate = 0.0
        self._write_rate = 0.0
        self._io_ready = False

    def on_mount(self) -> None:
        self.border_title = "◢ DISK ARRAY ◣"
        self.call_after_refresh(self._tick)
        self.set_interval(5.0, self._tick)

    def _tick(self) -> None:
        if not _telemetry_enabled(self):
            self._last_io = None
            self._last_io_at = None
            self._io_ready = False
            return

        disks: list[tuple[str, float, int]] = []
        try:
            for part in _visible_partitions(psutil.disk_partitions(all=False)):
                mp = part.mountpoint
                try:
                    usage = psutil.disk_usage(mp)
                except (OSError, psutil.Error):
                    continue
                label = _disk_label(mp, part.device)
                disks.append((label, usage.percent, usage.free))
        except (OSError, psutil.Error):
            pass

        sampled_at = monotonic()
        try:
            io = psutil.disk_io_counters()
        except (OSError, psutil.Error):
            io = None
        if io is not None:
            counters = (io.read_bytes, io.write_bytes)
            if self._last_io is not None and self._last_io_at is not None:
                elapsed = sampled_at - self._last_io_at
                if elapsed > 0:
                    self._read_rate = max(counters[0] - self._last_io[0], 0) / elapsed
                    self._write_rate = max(counters[1] - self._last_io[1], 0) / elapsed
                    self._io_ready = True
            self._last_io = counters
            self._last_io_at = sampled_at
        else:
            self._last_io = None
            self._last_io_at = None
            self._io_ready = False
        self._disks = disks
        self.refresh()

    def render(self) -> Text:
        width = self.content_size.width
        height = self.content_size.height
        out = Text(no_wrap=True, overflow="crop")
        if width <= 0 or height <= 0:
            return out

        io_line = Text()
        io_line.append("I/O ", style=palette.DIM)
        if self._io_ready:
            io_line.append("▼", style=palette.ACCENT)
            io_line.append(_human_rate(self._read_rate), style=palette.TEXT)
            io_line.append(" ")
            io_line.append("▲", style=palette.HOT)
            io_line.append(_human_rate(self._write_rate), style=palette.TEXT)
        else:
            io_line.append("sampling…", style=palette.ACCENT_DIM)
        out.append(_fit(io_line, width))

        rows_left = height - 1
        if rows_left <= 0:
            return out
        if not self._disks:
            out.append("\n")
            out.append("no volumes", style=palette.DIM)
            return out

        for label, pct, free in self._disks[:rows_left]:
            if len(out):
                out.append("\n")
            out.append(_disk_row(label, pct, free, width))
        return out
