# ⬢ TACHYON

> [!WARNING]
> Disclosure: this project was developed with minimal human input by Fable 5.

Tachyon is an eDEX-inspired command center that runs entirely inside a terminal.
A real shell on a real PTY occupies the center; live CPU, memory, process,
network, connection, disk, and filesystem instruments surround it in a restrained
cyan-on-void interface.

It is deliberately lighter than the original eDEX-UI: there is no browser engine,
canvas renderer, map feed, or background service. The runtime is Python,
[Textual](https://textual.textualize.io/),
[pyte](https://github.com/selectel/pyte),
[psutil](https://github.com/giampaolo/psutil), and ptyprocess.

## Run

```sh
uv run tachyon

# Useful startup controls
uv run tachyon --no-boot
uv run tachyon --cwd ~/work --files-root ~/work --history 5000
```

The equivalent environment variables are `TACHYON_NO_BOOT`, `TACHYON_CWD`,
`TACHYON_FILE_ROOT`, and `TACHYON_HISTORY`. Scrollback accepts 500–50,000 lines
and defaults to 2,000.

The embedded shell gets a scrubbed environment: the virtualenv Tachyon itself
runs in (e.g. under `uv run`) is stripped from `PATH` and `VIRTUAL_ENV`, so
working on Python projects inside Tachyon behaves like a fresh terminal.

Tachyon runs on macOS, Linux, and Windows. On POSIX systems the embedded shell
is `$SHELL` on a ptyprocess PTY; on Windows it is PowerShell (`pwsh`, then
`powershell`, then `cmd.exe`) on a ConPTY session via
[pywinpty](https://github.com/andfoy/pywinpty). Use Windows Terminal for best
results — legacy conhost struggles with Textual's escape sequences.

Tachyon adapts to the viewport instead of requiring a fixed terminal size:

- **122 columns and wider:** full three-column command center.
- **88–121 columns:** one telemetry rail plus the shell.
- **Below 88 columns or 34 rows:** shell-first compact deck; hidden sensors stop polling.
- **Below 29 rows:** the filesystem collapses, but `F3` opens it as a dedicated deck.

## Controls

Tachyon reserves one chord: `ctrl+space` arms the **command deck**, and the next
key is a control chord (a which-key strip shows every option). Everything else is
sent to the embedded shell. Function keys remain as aliases for the same actions,
but terminal emulators and macOS media keys make them unreliable — the leader
always works.

| Chord | Action |
| --- | --- |
| `^SPC s` (`F2`) | Focus the shell |
| `^SPC f` (`F3`) | Focus the filesystem |
| `^SPC c` (`F4`) | Change the shell to the selected directory or file's parent |
| `^SPC r` (`F5`) | Replace the shell session |
| `^SPC t` (`F6`) | Hold / resume peripheral telemetry |
| `^SPC .` (`F7`) | Show / filter filesystem dotfiles |
| `^SPC o` (`F8`) | Expand / close the two-column sensor deck |
| `^SPC z` (`F9`) | Toggle shell-only focus mode |
| `^SPC 1`–`9`, `0` | Magnify a numbered panel to fill the deck (tmux zoom; `0` = panel 10) |
| `^SPC ?` (`F1`, `cmd+/`) | Open the operator index |
| `^SPC q` (`F10`, `ctrl+q`) | Exit Tachyon |
| `ESC` | Stand down: restore the deck, then return focus to the shell |
| `ctrl+c` | Send `SIGINT` to the shell |
| `cmd+k` / `ctrl+shift+k` | Clear the shell: wipe scrollback and repaint the prompt |
| `shift+pageup`, `shift+pagedown` | Move through terminal history |
| `ctrl+shift+home`, `ctrl+shift+end` | Jump to oldest retained history / live tail |

Chords typed with CTRL still held (the tmux habit) resolve normally, and an
unknown chord keeps the deck armed and names the miss. Every panel border carries
its deck number (`◢ 04 · CPU CORES ◣`), so the magnify chords are always visible.
`^SPC 1` is shell focus mode and `^SPC 2` the dedicated file deck; `3`–`9` and `0`
fill the body with a single magnified instrument, which keeps sampling while
magnified.

The filesystem speaks vim when focused: `j`/`k` traverse, `h` folds a directory or
steps to its parent (at the root it re-roots one level up), `l` unfolds or selects,
`g`/`G` warp to the ends of the tree, and `.` toggles dotfiles. The cursor *is*
the selection — `CD HERE` targets whatever the cursor rests on. Selecting a path
updates its metadata rail. `^SPC c` uses a shell-quoted absolute path and returns
focus to the terminal. Dotfiles are filtered by default so the compact tree
remains legible.

The filesystem follows the shell: a 1 Hz poll of the PTY process tracks its
working directory, and a `cd` re-roots the tree there — an interactive `ls` of
wherever the shell is (marked `⌁SH` in the files status line) — unless you are
actively navigating the tree.

The bottom rail is a quiet status line — each mode names its own exit chord
there — and the header carries the shell's working directory in the middle.
The full keymap lives in the operator index, not on screen.

Every panel border is a drag handle: grab any edge with the mouse and drag to
resize the grid, tmux-style. Of the two panels meeting at a boundary, the
fixed-size one resizes and its flexible sibling absorbs the change.

## Instruments

Beyond the original telemetry, three theatrical instruments ship as prototypes:

- **UPLINK GRID** (`^SPC 0` to magnify, `^SPC g` to switch modes) — a braille
  Earth rasterized from Natural Earth coastlines, plotting live TCP endpoints
  as blinking blips with your own uplink marked `◎`. The default **ORBIT**
  mode renders a rotating orthographic globe (~7 fps, precomputed sphere
  geometry so rotation is just a longitude shift); **CHART** is the flat
  equirectangular map. Geolocation uses ip-api.com over plain HTTP with an
  in-memory cache; only public remote IPs are ever sent. Set `TACHYON_NO_GEO=1`
  to keep every lookup off the wire (the map still renders, the header reports
  `GEO OFF`).
- **INPUT MATRIX** (`^SPC k`, off by default) — an eDEX-style keyboard under
  the shell that lights keys as you type and tracks keystrokes per minute.
- **REPO TELEMETRY** — a git instrument beside the filesystem that wakes when the
  shell's working directory enters a repository: branch, ahead/behind, staged /
  dirty / untracked counts, and the last three commits. Outside a repo it idles
  at `NO REPO SIGNAL`.

## Themes

`^SPC y` opens the theme deck; a digit applies a palette live — layout CSS
re-derives from theme variables and every instrument repaints. Startup theme
via `--theme NAME` or `TACHYON_THEME`:

| Theme | Character |
| --- | --- |
| `tron` | cyan signal on near-black void (default) |
| `ghost` | transparent, [moonfly](https://github.com/bluz71/vim-moonfly-colors) foregrounds — backgrounds drop away and your terminal's own background (including blur/transparency) shows through |
| `catppuccin` | catppuccin mocha, mauve accent |
| `tokyo-night` | calm blue over deep indigo |
| `gruvbox` | gruvbox dark — warm grays, restrained color |

The boot sequence is a two-act homage to eDEX-UI: a kernel-log burst mixing
real facts about your machine with campy subsystem lines, then a block-letter
title card. Any key skips it; `--no-boot` disables it.

Note on `cmd+k`: whether the ⌘ key reaches Tachyon depends on your emulator.
Terminals speaking the kitty keyboard protocol (Ghostty, kitty, iTerm2 with
CSI u) deliver it as `super+k` — though most bind ⌘K themselves by default,
so you may need to unbind their own "clear" shortcut. `ctrl+shift+k` works
everywhere.

## What is live

- Per-core CPU load, aggregate history, and frequency when the OS reports it.
- RAM and swap gauges.
- Top processes by CPU, with memory as the idle-system tie-breaker.
- Interface identity, correctly time-normalized RX/TX rates, histories, and totals.
- Aggregated TCP connection state with IPv4/IPv6-safe endpoints.
- Portable mounted-volume capacity plus aggregate disk read/write throughput.
- A bounded terminal scrollback buffer and isolated xterm alternate-screen buffer.
- Automatic shell respawn with generation-safe PTY output and exit handling.

Expensive process and connection scans run in workers. PTY reads are coalesced and
bounded before they reach the UI, histories and style caches are bounded, and
telemetry panels stop sampling while hidden, held, or in shell focus mode.

## Architecture

```text
tachyon/
├── app.py            responsive decks, status rails, and global actions
├── config.py         validated CLI and environment configuration
├── palette.py        shared color vocabulary and themes
├── pty_backend.py    cross-platform PTY seam (ptyprocess POSIX / pywinpty ConPTY)
├── theme.tcss        layout, panel chrome, and responsive states
└── widgets/
    ├── term.py       PTY ↔ pyte ↔ Textual terminal core
    ├── deck.py       leader-key command deck (which-key chord strip)
    ├── globe.py      braille world map with geolocated uplink blips
    ├── worldmap.py   baked Natural Earth landmass bitmap
    ├── keys.py       input matrix keyboard telemetry (opt-in)
    ├── repo.py       contextual git instrument
    ├── resize.py     drag-any-border grid resizing foundation
    ├── monitors.py   system, CPU, memory, and process instruments
    ├── network.py    throughput, TCP connections, disks, and I/O
    ├── files.py      filtered filesystem navigator and shell target
    ├── help.py       operator index overlay
    └── boot.py       dismissible cold-boot sequence
```

The terminal reader runs outside the Textual event loop and batches bytes into a
bounded buffer. All pyte screen mutation occurs back on the event loop. Each PTY
generation is tagged, so late output or exit events from an old shell cannot affect
its replacement.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and working notes.

## Limits

- pyte covers the terminal behavior needed by common shells and full-screen apps,
  but it is not a byte-for-byte replacement for every xterm extension.
- Terminal mouse-reporting protocols are not forwarded; native terminal text
  selection remains available.
- System-wide TCP visibility depends on OS permissions. Tachyon falls back to the
  current user's processes when needed.
- Sensor availability varies by platform; missing counters degrade to a stable
  empty or sampling state rather than taking down the interface.
