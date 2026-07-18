# CONTRIBUTING.md

Working doc for anyone — human or agent — touching this repo. The README is
the front door; this is the bench.

## Current state (2026-07-18)

- v0.1.0, Python 3.12+, uv-managed. 101 tests green, ruff clean.
- Runs on macOS, Linux, and Windows. The platform seam is
  `tachyon/pty_backend.py`: ptyprocess on POSIX, pywinpty/ConPTY on Windows.

## Development

```sh
uv run tachyon               # run from source
uv run pytest -q             # full suite, headless
uv run ruff check .
uv run ruff format --check .
uv build
```

## Working notes

- The pytest suite is headless. Anything visual or interactive — deck chords,
  resize behavior, boot sequence, theme rendering — needs a real terminal run
  (`uv run tachyon`); Windows behavior additionally wants Windows Terminal,
  since legacy conhost mangles Textual's escape sequences.
- The terminal core has a threading invariant: the PTY reader runs outside the
  Textual event loop and only batches bytes; all pyte screen mutation happens
  back on the event loop, and every PTY generation is tagged so a dead shell's
  late output cannot touch its replacement. Keep that shape when touching
  `widgets/term.py` or `pty_backend.py`.
- Themes live in `tachyon/palette.py`; `theme.tcss` derives layout from theme
  variables, so instruments repaint on a live theme switch without their own
  theme code.
- The only network egress in the codebase is UPLINK GRID geolocation
  (ip-api.com, public remote IPs only, `TACHYON_NO_GEO=1` kills it). Keep it
  that way — anything new that touches the wire needs an off switch.
