from __future__ import annotations

import pytest

from tachyon import pty_backend


def test_default_shell_posix_prefers_shell_variable() -> None:
    assert pty_backend.default_shell(windows=False, environ={"SHELL": "/bin/dash"}) == ["/bin/dash"]


def test_default_shell_posix_falls_back_to_sh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pty_backend.shutil, "which", lambda name: None)

    assert pty_backend.default_shell(windows=False, environ={}) == ["/bin/sh"]


def test_default_shell_windows_prefers_pwsh(monkeypatch: pytest.MonkeyPatch) -> None:
    found = {"pwsh": r"C:\Program Files\PowerShell\7\pwsh.exe"}
    monkeypatch.setattr(pty_backend.shutil, "which", found.get)

    assert pty_backend.default_shell(windows=True, environ={}) == [found["pwsh"]]


def test_default_shell_windows_falls_back_to_comspec_then_cmd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pty_backend.shutil, "which", lambda name: None)
    comspec = {"COMSPEC": r"C:\Windows\system32\cmd.exe"}

    assert pty_backend.default_shell(windows=True, environ=comspec) == [comspec["COMSPEC"]]
    assert pty_backend.default_shell(windows=True, environ={}) == ["cmd.exe"]
