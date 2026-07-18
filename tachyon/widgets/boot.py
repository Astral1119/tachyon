"""Boot sequence — kernel-log theater with an eDEX-style title card.

Two phases: a fake kernel log that mixes real facts about this machine with
campy subsystem lines, paced in bursts with dramatic pauses; then a big
block-letter TACHYON title card that flashes before handing over the deck.
Any key skips everything.
"""

from __future__ import annotations

import getpass
import os
import platform
import socket
from contextlib import suppress

import psutil
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from tachyon import palette, pty_backend

# 5-row block font for the title card, letters used by "TACHYON".
_FONT = {
    "T": ("██████", "  ██  ", "  ██  ", "  ██  ", "  ██  "),
    "A": (" ████ ", "██  ██", "██████", "██  ██", "██  ██"),
    "C": (" █████", "██    ", "██    ", "██    ", " █████"),
    "H": ("██  ██", "██  ██", "██████", "██  ██", "██  ██"),
    "Y": ("██  ██", "██  ██", " ████ ", "  ██  ", "  ██  "),
    "O": (" ████ ", "██  ██", "██  ██", "██  ██", " ████ "),
    "N": ("██  ██", "███ ██", "██▙ ██", "██ ███", "██  ██"),
}


def banner(word: str = "TACHYON") -> str:
    rows = []
    for row in range(5):
        rows.append(" ".join(_FONT[letter][row] for letter in word))
    return "\n".join(rows)


def _real_facts() -> dict[str, str]:
    """Grounded lines make the fake ones land harder."""
    facts = {
        "host": socket.gethostname().removesuffix(".local"),
        "user": getpass.getuser(),
        "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        "shell": os.path.basename(pty_backend.default_shell()[0]),
        "pty_dev": "conpty channel" if pty_backend.IS_WINDOWS else "/dev/ptmx",
        "cores": str(psutil.cpu_count() or "?"),
    }
    with suppress(Exception):
        facts["mem"] = f"{psutil.virtual_memory().total / 1024**3:.1f} GB"
    return facts


def _boot_script() -> list[tuple[str, float]]:
    """(line, delay-after-seconds) pairs — bursts with dramatic pauses."""
    f = _real_facts()
    fast = 0.018
    lines: list[tuple[str, float]] = [
        ("Welcome to TACHYON", 0.35),
        (f"tachyon kernel 0.1.0 cold boot on {f['host']}; root:pty-bridge/RELEASE", 0.4),
        ("vm_page_bootstrap: telemetry pages wired, history pages bounded", fast),
        (f"cpu_topology: {f['cores']} cores enumerated, per-core taps armed", fast),
        (f"mem_map: {f.get('mem', '?')} paged and mirrored", fast),
        (f"kernel text [{f['os']}]", fast),
        ("standard timeslicing quantum is 10000 us", fast),
        ("TSC Deadline Timer supported and enabled", fast),
        ("zone leak detection enabled", fast),
        ("calling mpo_policy_init for SensorMesh", fast),
        ("Security policy loaded: bounded scrollback containment (HistoryBuffer)", fast),
        ("calling mpo_policy_init for AltDisplay", fast),
        ("Security policy loaded: alternate buffer isolation (AltDisplay)", fast),
        ("com.tachyon.PyteVTEngine kmod start", fast),
        ("com.tachyon.PyteVTEngine: xterm-256color translation online", fast),
        ("com.tachyon.TrololoBootScreen kmod start", fast),
        ("mbinit: done [64 MB total pool size, (42/21) split]", 0.3),
        (f"pty_bridge: {f['pty_dev']} acquired for {f['user']}@{f['host']}", fast),
        (f"spawning shell {f['shell']} — environment scrubbed of host venv", fast),
        ("keybind_matrix: leader chord ctrl+space armed, fn aliases standing by", fast),
        ("filesystem_lattice: shell-follow uplink locked at 1 Hz", fast),
        ("repo_telemetry: git plumbing probes calibrated", fast),
        ("conntrack: socket table streaming", fast),
        ("uplink_grid: natural-earth landmass checksum OK (360x160)", fast),
        ("uplink_grid: orthographic rasterizer spun up to 2.2 deg/frame", fast),
        ("input_matrix: 60-key photonic lattice on standby", fast),
        ("sensor_mesh: cpu/mem/disk/net channels up", 0.35),
        ("Waiting for DSMOS...", 0.25),
        ("previous shutdown cause: 5", fast),
        ("en0: 802.11 wireless controller negotiating", fast),
        ("responsive_rails: viewport lock acquired", fast),
        ("drag_grid: every border is a handle; tmux protocols honored", fast),
        ("theme_engine: night-city palette resident", 0.3),
        ("", 0.1),
        ("Boot Complete", 0.5),
    ]
    return lines


class BootScreen(Screen):
    """Kernel-log burst, then a flashing title card, then the deck."""

    DEFAULT_CSS = """
    BootScreen {
        background: $bg;
    }
    BootScreen #boot-log {
        width: 100%;
        height: 100%;
        padding: 1 2;
        color: $text;
    }
    BootScreen.title {
        align: center middle;
    }
    BootScreen.title #boot-log {
        width: auto;
        height: auto;
        padding: 1 4;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._script = _boot_script()
        self._shown = 0
        self._title_frame = 0
        self._done = False

    def compose(self) -> ComposeResult:
        yield Static(id="boot-log")

    def on_mount(self) -> None:
        self._advance()
        self.set_timer(9.0, self._finish)  # hard ceiling, whatever happens

    # ------------------------------------------------------------- log phase

    def _advance(self) -> None:
        if self._done:
            return
        if self._shown >= len(self._script):
            self.set_timer(0.3, self._title_card)
            return
        self._shown += 1
        self._render_log()
        delay = self._script[self._shown - 1][1]
        self.set_timer(delay, self._advance)

    def _render_log(self) -> None:
        height = max(self.size.height - 2, 4)
        visible = self._script[: self._shown][-height:]
        out = Text(no_wrap=True, overflow="crop")
        for index, (raw, _delay) in enumerate(visible):
            if index:
                out.append("\n")
            if raw == "Welcome to TACHYON":
                out.append(raw, style=f"bold {palette.ACCENT}")
            elif raw == "Boot Complete":
                out.append(raw, style=f"bold {palette.OK}")
            elif raw.startswith(("com.tachyon", "Security policy")):
                out.append(raw, style=palette.ACCENT_DIM)
            else:
                out.append(raw, style=palette.TEXT)
        self.query_one("#boot-log", Static).update(out)

    # ----------------------------------------------------------- title phase

    def _title_card(self) -> None:
        if self._done:
            return
        self.add_class("title")
        self._title_frame += 1
        art = banner()
        out = Text(no_wrap=True, overflow="crop", justify="center")
        if self._title_frame == 1:
            out.append(art, style=palette.ACCENT_DIM)
            delay = 0.18
        elif self._title_frame == 2:
            out.append(art, style=f"bold {palette.CHIP} on {palette.ACCENT}")
            delay = 0.22
        elif self._title_frame == 3:
            out.append(art, style=f"bold {palette.HOT}")
            delay = 0.18
        else:
            out.append(art, style=f"bold {palette.ACCENT}")
            out.append("\n\n")
            out.append("S H E L L   C O N T R O L   S U R F A C E", style=palette.DIM)
            self.query_one("#boot-log", Static).update(out)
            self.set_timer(0.8, self._finish)
            return
        self.query_one("#boot-log", Static).update(out)
        self.set_timer(delay, self._title_card)

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        with suppress(Exception):
            self.dismiss()

    def on_key(self, event: events.Key) -> None:
        event.stop()
        self._finish()
