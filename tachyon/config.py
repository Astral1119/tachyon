"""Command-line and environment configuration for Tachyon."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

DEFAULT_HISTORY_LINES = 2_000
MIN_HISTORY_LINES = 500
MAX_HISTORY_LINES = 50_000


@dataclass(frozen=True, slots=True)
class TachyonConfig:
    """Validated startup settings for a Tachyon session."""

    shell_cwd: Path = field(default_factory=Path.home)
    filesystem_root: Path = field(default_factory=Path.home)
    history_lines: int = DEFAULT_HISTORY_LINES
    boot_enabled: bool = True
    theme: str = "tron"


def _resolve_directory(value: str | Path) -> Path:
    raw = os.fspath(value)
    if not raw:
        raise ValueError("directory path must not be empty")
    try:
        path = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"cannot resolve directory {raw!r}: {error}") from error
    try:
        exists = path.exists()
        is_directory = path.is_dir()
    except OSError as error:
        raise ValueError(f"cannot inspect directory {path}: {error}") from error
    if not exists:
        raise ValueError(f"directory does not exist: {path}")
    if not is_directory:
        raise ValueError(f"not a directory: {path}")
    return path


def _directory_argument(value: str) -> Path:
    try:
        return _resolve_directory(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _history_value(value: str) -> int:
    try:
        history = int(value, 10)
    except ValueError as error:
        raise ValueError(
            f"history must be an integer from {MIN_HISTORY_LINES} to {MAX_HISTORY_LINES}"
        ) from error
    if not MIN_HISTORY_LINES <= history <= MAX_HISTORY_LINES:
        raise ValueError(
            f"history must be from {MIN_HISTORY_LINES} to {MAX_HISTORY_LINES}, got {history}"
        )
    return history


def _history_argument(value: str) -> int:
    try:
        return _history_value(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _parser_error(parser: argparse.ArgumentParser, source: str, error: ValueError) -> NoReturn:
    parser.error(f"{source}: {error}")


def _environment_directory(parser: argparse.ArgumentParser, name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return _resolve_directory(value)
    except ValueError as error:
        _parser_error(parser, name, error)


def _environment_history(parser: argparse.ArgumentParser) -> int:
    value = os.environ.get("TACHYON_HISTORY")
    if value is None:
        return DEFAULT_HISTORY_LINES
    try:
        return _history_value(value)
    except ValueError as error:
        _parser_error(parser, "TACHYON_HISTORY", error)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tachyon",
        description="A lightweight sci-fi terminal environment.",
    )
    parser.add_argument(
        "--cwd",
        dest="shell_cwd",
        metavar="DIR",
        type=_directory_argument,
        default=argparse.SUPPRESS,
        help="initial directory for the embedded shell",
    )
    parser.add_argument(
        "--files-root",
        dest="filesystem_root",
        metavar="DIR",
        type=_directory_argument,
        default=argparse.SUPPRESS,
        help="root directory shown in the filesystem panel",
    )
    parser.add_argument(
        "--history",
        dest="history_lines",
        metavar="LINES",
        type=_history_argument,
        default=argparse.SUPPRESS,
        help=f"terminal scrollback lines ({MIN_HISTORY_LINES}..{MAX_HISTORY_LINES})",
    )
    parser.add_argument(
        "--no-boot",
        action="store_true",
        default=False,
        help="skip the startup sequence",
    )
    from tachyon.palette import THEMES

    parser.add_argument(
        "--theme",
        dest="theme",
        choices=sorted(THEMES),
        default=argparse.SUPPRESS,
        help="color theme (also switchable in-app via ^SPC y)",
    )
    return parser


def parse_config(argv: Sequence[str] | None = None) -> TachyonConfig:
    """Parse CLI arguments over environment variables and validated defaults."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    try:
        home = _resolve_directory(Path.home())
    except ValueError as error:
        _parser_error(parser, "home directory", error)

    shell_cwd = (
        arguments.shell_cwd
        if hasattr(arguments, "shell_cwd")
        else _environment_directory(parser, "TACHYON_CWD", home)
    )
    filesystem_root = (
        arguments.filesystem_root
        if hasattr(arguments, "filesystem_root")
        else _environment_directory(parser, "TACHYON_FILE_ROOT", home)
    )
    history_lines = (
        arguments.history_lines
        if hasattr(arguments, "history_lines")
        else _environment_history(parser)
    )
    no_boot_from_environment = bool(os.environ.get("TACHYON_NO_BOOT"))

    from tachyon.palette import THEMES

    if hasattr(arguments, "theme"):
        theme = arguments.theme
    else:
        theme = os.environ.get("TACHYON_THEME", "tron")
        if theme not in THEMES:
            _parser_error(
                parser,
                "TACHYON_THEME",
                ValueError(f"unknown theme {theme!r} (have {sorted(THEMES)})"),
            )

    return TachyonConfig(
        shell_cwd=shell_cwd,
        filesystem_root=filesystem_root,
        history_lines=history_lines,
        boot_enabled=not (arguments.no_boot or no_boot_from_environment),
        theme=theme,
    )
