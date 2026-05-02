#!/usr/bin/env python3
"""Small CLI-only helpers shared by top-level command wrappers."""

import sys

sys.dont_write_bytecode = True

try:
    from .process import die, run_interactive
except ImportError:
    from process import die, run_interactive  # type: ignore


def clear_screen(enabled: bool) -> None:
    if enabled:
        run_interactive(["clear"])


def command_from_argv(argv: list[str]) -> str:
    command = " ".join(argv).strip()
    if not command:
        die("empty command")
    return command


def parse_csv_names(values: list[str], *, allow_all: bool = True) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for value in values:
        for part in value.split(","):
            name = part.strip()

            if not name:
                die("empty name in list")

            key = name.lower()
            if key in seen:
                die(f"duplicate name: {name}")

            seen.add(key)
            names.append(name)

    if allow_all:
        if len(names) == 1 and names[0].lower() == "all":
            return []
        if any(name.lower() == "all" for name in names):
            die("'all' cannot be mixed with names")

    return names


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False
        print("please answer yes or no")
