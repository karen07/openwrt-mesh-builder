#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

try:
    from .default import CONFIG_PATH, TOPOLOGY_TITLE
    from .file_ops import write_text_output
except ImportError:
    from default import CONFIG_PATH, TOPOLOGY_TITLE  # type: ignore
    from file_ops import write_text_output  # type: ignore


def add_topology_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--speeds-json",
        default="link-speeds.json",
        help="JSON file produced by collect_link_speeds.py --json-out",
    )
    parser.add_argument(
        "--topology-only",
        action="store_true",
        help="render topology without link speed JSON",
    )
    parser.add_argument(
        "--topology-source",
        choices=("generated", "config"),
        default="generated",
        help="source for --topology-only",
    )
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--title", default=TOPOLOGY_TITLE)


def add_output_arg(parser: argparse.ArgumentParser, *, help_text: str) -> None:
    parser.add_argument("--out", default=None, help=help_text)


def resolved_output_path(out: str | None, default: Path) -> Path:
    if out is not None:
        return Path(out)
    return default


def write_topology_output(path: Path, text: str) -> None:
    write_text_output(path, text)
