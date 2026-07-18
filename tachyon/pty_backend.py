"""Cross-platform pseudoterminal sessions.

POSIX sessions ride on ptyprocess; Windows sessions ride on pywinpty's ConPTY
bridge.  Both are normalized to a bytes-in/bytes-out interface with a shared
exception tuple so the terminal widget never branches on the host platform.
"""

from __future__ import annotations

import os
import shutil
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import winpty

    PTY_ERRORS: tuple[type[BaseException], ...] = (OSError, EOFError, winpty.WinptyError)
else:
    import ptyprocess

    PTY_ERRORS = (OSError, ptyprocess.PtyProcessError)


def default_shell(
    *, windows: bool = IS_WINDOWS, environ: dict[str, str] | None = None
) -> list[str]:
    """The command a fresh Tachyon session should spawn on this host."""
    env = os.environ if environ is None else environ
    if windows:
        shell = (
            shutil.which("pwsh") or shutil.which("powershell") or env.get("COMSPEC") or "cmd.exe"
        )
        return [shell]
    return [env.get("SHELL") or shutil.which("zsh") or "/bin/sh"]


class PtySession:
    """A live PTY-backed child process with byte-oriented I/O.

    ``read`` blocks until output arrives and returns ``b""`` once the session
    reaches EOF; it never raises.  ``write`` returns the number of bytes
    accepted.  Lifecycle methods mirror ptyprocess semantics.
    """

    pid: int

    @property
    def closed(self) -> bool:
        raise NotImplementedError

    def read(self, size: int) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes) -> int:
        raise NotImplementedError

    def setwinsize(self, rows: int, cols: int) -> None:
        raise NotImplementedError

    def getwinsize(self) -> tuple[int, int]:
        raise NotImplementedError

    def isalive(self) -> bool:
        raise NotImplementedError

    def terminate(self, force: bool = False) -> bool:
        raise NotImplementedError

    def close(self, force: bool = True) -> None:
        raise NotImplementedError


class _PosixSession(PtySession):
    def __init__(self, proc: ptyprocess.PtyProcess) -> None:
        self._proc = proc
        self.pid = proc.pid

    @property
    def closed(self) -> bool:
        return self._proc.closed

    def read(self, size: int) -> bytes:
        # Linux raises EIO at PTY EOF where macOS returns b""; both mean done.
        try:
            return os.read(self._proc.fd, size)
        except OSError:
            return b""

    def write(self, data: bytes) -> int:
        return self._proc.write(data)

    def setwinsize(self, rows: int, cols: int) -> None:
        self._proc.setwinsize(rows, cols)

    def getwinsize(self) -> tuple[int, int]:
        return self._proc.getwinsize()

    def isalive(self) -> bool:
        return self._proc.isalive()

    def terminate(self, force: bool = False) -> bool:
        return self._proc.terminate(force=force)

    def close(self, force: bool = True) -> None:
        self._proc.close(force=force)


class _WindowsSession(PtySession):
    """ConPTY session; pywinpty deals in decoded text, so bytes bridge UTF-8."""

    def __init__(self, proc: winpty.PtyProcess, dimensions: tuple[int, int]) -> None:
        self._proc = proc
        self._dimensions = dimensions
        self.pid = proc.pid

    @property
    def closed(self) -> bool:
        return bool(self._proc.closed)

    def read(self, size: int) -> bytes:
        try:
            return self._proc.read(size).encode("utf-8")
        except PTY_ERRORS:
            return b""

    def write(self, data: bytes) -> int:
        self._proc.write(data.decode("utf-8", "replace"))
        return len(data)

    def setwinsize(self, rows: int, cols: int) -> None:
        self._proc.setwinsize(rows, cols)
        self._dimensions = (rows, cols)

    def getwinsize(self) -> tuple[int, int]:
        return self._dimensions

    def isalive(self) -> bool:
        return self._proc.isalive()

    def terminate(self, force: bool = False) -> bool:
        return bool(self._proc.terminate(force=force))

    def close(self, force: bool = True) -> None:
        self._proc.close()


def spawn(
    argv: list[str],
    *,
    dimensions: tuple[int, int],
    env: dict[str, str],
    cwd: str,
) -> PtySession:
    """Spawn ``argv`` on a PTY sized ``(rows, cols)`` and return the session."""
    if IS_WINDOWS:
        proc = winpty.PtyProcess.spawn(argv, dimensions=dimensions, env=env, cwd=cwd)
        return _WindowsSession(proc, dimensions)
    proc = ptyprocess.PtyProcess.spawn(argv, dimensions=dimensions, env=env, cwd=cwd)
    return _PosixSession(proc)
