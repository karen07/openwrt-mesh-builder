#!/usr/bin/env python3
"""Small process helpers for the Unix-tool boundary.

All host-side external command calls should go through this module or through a
higher-level wrapper that uses this module.  This keeps the project logic in
Python while keeping domain work in the matching Unix tools.
"""

import sys

sys.dont_write_bytecode = True
import shutil
import subprocess
from pathlib import Path


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def format_command(args: list[str]) -> str:
    return " ".join(str(arg) for arg in args)


def need(*names: str) -> None:
    for name in names:
        if shutil.which(name) is None:
            die(f"command not found: {name}")


def run_command(argv: list[str], timeout: int | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def run_captured(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def run_checked(
    args: list[str],
    cwd: Path | None = None,
    quiet: bool = False,
    input_text: str | None = None,
) -> str:
    result = run_captured(args, cwd=cwd, input_text=input_text)
    if result.returncode != 0:
        if result.stdout and not quiet:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        die(f"command failed: {format_command(args)}")
    return result.stdout


def run_no_capture(args: list[str], cwd: Path | None = None) -> None:
    rc = subprocess.run(args, cwd=cwd, check=False).returncode
    if rc != 0:
        die(f"command failed: {format_command(args)}")


def run_interactive(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_data: bytes | None = None,
) -> int:
    return subprocess.run(args, cwd=cwd, input=input_data, check=False).returncode


def output_or_none(args: list[str], cwd: Path | None = None) -> str | None:
    result = run_captured(args, cwd=cwd)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None
