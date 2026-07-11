from __future__ import annotations

from pathlib import Path

import pytest

from tachyon.config import MAX_HISTORY_LINES, MIN_HISTORY_LINES, parse_config

TACHYON_ENVIRONMENT = (
    "TACHYON_CWD",
    "TACHYON_FILE_ROOT",
    "TACHYON_HISTORY",
    "TACHYON_NO_BOOT",
)


@pytest.fixture(autouse=True)
def clear_tachyon_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in TACHYON_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_defaults_use_home() -> None:
    config = parse_config([])
    home = Path.home().resolve()

    assert config.shell_cwd == home
    assert config.filesystem_root == home
    assert config.history_lines == 2_000
    assert config.boot_enabled is True


def test_environment_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    shell_cwd = tmp_path / "shell"
    files_root = tmp_path / "files"
    shell_cwd.mkdir()
    files_root.mkdir()
    monkeypatch.setenv("TACHYON_CWD", str(shell_cwd))
    monkeypatch.setenv("TACHYON_FILE_ROOT", str(files_root))
    monkeypatch.setenv("TACHYON_HISTORY", "1500")
    monkeypatch.setenv("TACHYON_NO_BOOT", "1")

    config = parse_config([])

    assert config.shell_cwd == shell_cwd.resolve()
    assert config.filesystem_root == files_root.resolve()
    assert config.history_lines == 1_500
    assert config.boot_enabled is False


def test_cli_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shell_cwd = tmp_path / "shell"
    files_root = tmp_path / "files"
    shell_cwd.mkdir()
    files_root.mkdir()
    monkeypatch.setenv("TACHYON_CWD", str(tmp_path / "missing-env-cwd"))
    monkeypatch.setenv("TACHYON_FILE_ROOT", str(tmp_path / "missing-env-root"))
    monkeypatch.setenv("TACHYON_HISTORY", "not-an-integer")

    config = parse_config(
        [
            "--cwd",
            str(shell_cwd),
            "--files-root",
            str(files_root),
            "--history",
            str(MAX_HISTORY_LINES),
            "--no-boot",
        ]
    )

    assert config.shell_cwd == shell_cwd.resolve()
    assert config.filesystem_root == files_root.resolve()
    assert config.history_lines == MAX_HISTORY_LINES
    assert config.boot_enabled is False


@pytest.mark.parametrize("history", [str(MIN_HISTORY_LINES - 1), str(MAX_HISTORY_LINES + 1)])
def test_cli_rejects_history_outside_bounds(
    history: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        parse_config(["--history", history])

    assert raised.value.code == 2
    assert "500 to 50000" in capsys.readouterr().err


def test_environment_rejects_invalid_history(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TACHYON_HISTORY", "many")

    with pytest.raises(SystemExit) as raised:
        parse_config([])

    error = capsys.readouterr().err
    assert raised.value.code == 2
    assert "TACHYON_HISTORY" in error
    assert "history must be an integer" in error


def test_cli_rejects_file_as_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file_path = tmp_path / "plain-file"
    file_path.write_text("not a directory")

    with pytest.raises(SystemExit) as raised:
        parse_config(["--cwd", str(file_path)])

    assert raised.value.code == 2
    assert "not a directory" in capsys.readouterr().err


def test_environment_rejects_missing_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TACHYON_FILE_ROOT", str(tmp_path / "missing"))

    with pytest.raises(SystemExit) as raised:
        parse_config([])

    error = capsys.readouterr().err
    assert raised.value.code == 2
    assert "TACHYON_FILE_ROOT" in error
    assert "directory does not exist" in error
