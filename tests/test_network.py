from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from types import SimpleNamespace
from typing import NamedTuple

import pytest

from tachyon.widgets import network as network_module
from tachyon.widgets.network import (
    DiskPanel,
    NetPanel,
    _disk_row,
    _format_endpoint,
    _human_bytes,
    _human_rate,
    _visible_partitions,
)


class Partition(NamedTuple):
    device: str
    mountpoint: str
    fstype: str
    opts: str = "rw"


class _UpdatedWidget:
    def __init__(self) -> None:
        self.value: object | None = None
        self.data: list[float] = []

    def update(self, value: object) -> None:
        self.value = value


class _PanelApp:
    telemetry_active = True

    @staticmethod
    def batch_update():
        return nullcontext()


@pytest.mark.parametrize(
    ("size", "display"),
    [
        (0, "0 B/s"),
        (1_023, "1023 B/s"),
        (1_024, "1.0 KB/s"),
        (1_536, "1.5 KB/s"),
        (1_024**2, "1.0 MB/s"),
        (1_024**3, "1.0 GB/s"),
    ],
)
def test_human_rate(size: int, display: str) -> None:
    assert _human_rate(size) == display


@pytest.mark.parametrize(
    ("size", "display"),
    [
        (0, "0B"),
        (1_023, "1023B"),
        (1_024, "1K"),
        (1_024**2, "1.0M"),
        (1_024**3, "1.0G"),
        (1_024**4, "1.0T"),
    ],
)
def test_human_bytes(size: int, display: str) -> None:
    assert _human_bytes(size) == display


def test_visible_partitions_on_linux_filters_and_deduplicates() -> None:
    partitions = [
        Partition("/dev/root", "/", "ext4"),
        Partition("/dev/home", "/home", "ext4"),
        Partition("/dev/root", "/mnt/root-alias", "ext4"),
        Partition("/dev/usb", "/media/USB", "exfat"),
        Partition("/dev/usb-copy", "/media/USB", "exfat"),
        Partition("tmpfs", "/run", "tmpfs"),
        Partition("proc", "/proc", "proc"),
        Partition("/dev/loop0", "/snap/tool", "squashfs"),
        Partition("/dev/relative", "relative/path", "ext4"),
    ]

    visible = _visible_partitions(partitions, platform="linux")

    assert [partition.mountpoint for partition in visible] == [
        "/",
        "/home",
        "/media/USB",
    ]


def test_visible_partitions_on_macos_keeps_root_and_external_volumes() -> None:
    partitions = [
        Partition("/dev/disk3s1s1", "/", "apfs"),
        Partition("/dev/disk3s5", "/System/Volumes/Data", "apfs"),
        Partition("/dev/disk4s1", "/Volumes/WORK", "apfs"),
        Partition("/dev/disk4s1", "/Volumes/WORK-ALIAS", "apfs"),
        Partition("/dev/disk5s1", "/mnt/archive", "apfs"),
        Partition("map auto_home", "/System/Volumes/Data/home", "autofs"),
    ]

    visible = _visible_partitions(partitions, platform="darwin")

    assert [partition.mountpoint for partition in visible] == ["/", "/Volumes/WORK"]


def test_visible_partitions_on_windows_keeps_drives_and_skips_empty_media() -> None:
    partitions = [
        Partition("C:\\", "C:\\", "NTFS", "rw,fixed"),
        Partition("D:\\", "D:\\", "ntfs", "rw,fixed"),
        Partition("D:\\", "D:\\", "ntfs", "rw,fixed"),
        Partition("E:\\", "E:\\", "", "cdrom"),
        Partition("F:\\", "F:\\", "cdfs", "ro,cdrom"),
        Partition("\\\\nas\\share", "\\\\nas\\share", "smb", "rw"),
        Partition("relative", "relative", "ntfs", "rw"),
    ]

    visible = _visible_partitions(partitions, platform="win32")

    assert [partition.mountpoint for partition in visible] == [
        "C:\\",
        "D:\\",
        "\\\\nas\\share",
    ]


@pytest.mark.parametrize("width", [1, 2, 4, 8, 10, 17, 18, 26, 32, 50, 80])
def test_disk_row_has_exact_width_and_never_wraps(width: int) -> None:
    row = _disk_row("EXTRA-LONG-ARCHIVE", 73.0, 10**12, width)

    assert row.cell_len == width
    assert "\n" not in row.plain
    assert row.no_wrap is True


@pytest.mark.parametrize(
    ("endpoint", "empty", "display"),
    [
        ((), "*", "*"),
        (("127.0.0.1", 8080), "-", "127.0.0.1:8080"),
        (("::1", 443), "-", "[::1]:443"),
        (("fe80::1", 22, 0, 4), "-", "[fe80::1]:22"),
    ],
)
def test_format_endpoint(endpoint: tuple[object, ...], empty: str, display: str) -> None:
    assert _format_endpoint(endpoint, empty=empty) == display


def test_network_rate_uses_actual_elapsed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    counters = SimpleNamespace(bytes_recv=3_000, bytes_sent=6_000)
    monkeypatch.setattr(
        network_module.psutil,
        "net_io_counters",
        lambda *, pernic: {"en0": counters} if pernic else counters,
    )
    monkeypatch.setattr(network_module, "monotonic", lambda: 12.0)

    children = {
        "#net-info": _UpdatedWidget(),
        "#net-rx-label": _UpdatedWidget(),
        "#net-rx-spark": _UpdatedWidget(),
        "#net-tx-label": _UpdatedWidget(),
        "#net-tx-spark": _UpdatedWidget(),
        "#net-totals": _UpdatedWidget(),
    }

    def query_one(selector: str, _widget_type: object) -> _UpdatedWidget:
        return children[selector]

    panel = SimpleNamespace(
        app=_PanelApp(),
        region=SimpleNamespace(width=30, height=14),
        content_size=SimpleNamespace(width=30),
        _iface_age=0,
        _iface="en0",
        _ip="192.0.2.1",
        _last=(1_000, 2_000),
        _last_at=10.0,
        _last_source="en0",
        _rx_hist=deque([0.0], maxlen=28),
        _tx_hist=deque([0.0], maxlen=28),
        query_one=query_one,
    )

    NetPanel._tick(panel)

    assert panel._rx_hist[-1] == pytest.approx(1_000.0)
    assert panel._tx_hist[-1] == pytest.approx(2_000.0)
    assert children["#net-rx-spark"].data[-1] == pytest.approx(1_000.0)
    assert children["#net-tx-spark"].data[-1] == pytest.approx(2_000.0)


def test_disk_rate_uses_actual_elapsed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    counters = SimpleNamespace(read_bytes=12_048, write_bytes=24_096)
    monkeypatch.setattr(network_module.psutil, "disk_partitions", lambda *, all: [])
    monkeypatch.setattr(network_module.psutil, "disk_io_counters", lambda: counters)
    monkeypatch.setattr(network_module, "monotonic", lambda: 22.0)
    refreshed: list[bool] = []
    panel = SimpleNamespace(
        app=_PanelApp(),
        region=SimpleNamespace(width=30, height=9),
        _disks=[],
        _last_io=(10_000, 20_000),
        _last_io_at=20.0,
        _read_rate=0.0,
        _write_rate=0.0,
        _io_ready=False,
        refresh=lambda: refreshed.append(True),
    )

    DiskPanel._tick(panel)

    assert panel._read_rate == pytest.approx(1_024.0)
    assert panel._write_rate == pytest.approx(2_048.0)
    assert panel._io_ready is True
    assert refreshed == [True]
