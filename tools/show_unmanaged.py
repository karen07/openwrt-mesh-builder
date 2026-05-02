#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import contextlib
import hashlib
import io
import os
from pathlib import Path

try:
    from .common import (
        CONFIG_PATH,
        ConfigData,
        SERVER_ROOT,
        build_config_data,
        load_json_config,
    )
    from .default import UNMANAGED_REPORT_HASH_LEN
    from .show_unmanaged_collect import (
        collect_unmanaged_bootstrap_above_marker,
        collect_unmanaged_firewall_above_marker,
        collect_unmanaged_network_above_marker,
        collect_unmanaged_router_files,
        collect_unmanaged_server_files,
    )
except ImportError:
    from common import (  # type: ignore
        CONFIG_PATH,
        ConfigData,
        SERVER_ROOT,
        build_config_data,
        load_json_config,
    )
    from default import UNMANAGED_REPORT_HASH_LEN  # type: ignore
    from show_unmanaged_collect import (  # type: ignore
        collect_unmanaged_bootstrap_above_marker,
        collect_unmanaged_firewall_above_marker,
        collect_unmanaged_network_above_marker,
        collect_unmanaged_router_files,
        collect_unmanaged_server_files,
    )

# ============================================================
# PRINT
# ============================================================

ANSI_RESET = "\033[0m"
ANSI_ROUTER = "\033[1;34m"  # blue
ANSI_SECTION = "\033[1;38;5;208m"  # orange
ANSI_EXTRA_FILE = "\033[0;36m"  # cyan


def use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def color(text: str, ansi: str) -> str:
    if not use_color():
        return text
    return f"{ansi}{text}{ANSI_RESET}"


def print_router_header(name: str, first: bool) -> None:
    if not first:
        print()
    print(color(f"{name}:", ANSI_ROUTER))


def print_section_header(title: str) -> None:
    print(f"  {color(f'{title}:', ANSI_SECTION)}")


def print_uci_section(title: str, blocks: list[str]) -> None:
    if not blocks:
        return

    print_section_header(title)
    for block in blocks:
        for line in block.splitlines():
            print(f"    {line}")
        print()


def print_text_section(title: str, text: str) -> None:
    if not text.strip():
        return

    print_section_header(title)
    for line in text.splitlines():
        print(f"    {line}")
    print()


def print_file_list_section(title: str, items: list[str]) -> None:
    if not items:
        return

    print_section_header(title)
    for item in items:
        print(f"    {color(item, ANSI_EXTRA_FILE)}")
    print()


# ============================================================
# RENDER / MAIN
# ============================================================


def print_unmanaged_report(cfg: ConfigData) -> None:
    printed_any = False

    for router_name in cfg.router_names:
        unmanaged_network = collect_unmanaged_network_above_marker(cfg, router_name)
        unmanaged_firewall = collect_unmanaged_firewall_above_marker(cfg, router_name)
        unmanaged_bootstrap = collect_unmanaged_bootstrap_above_marker(cfg, router_name)
        unmanaged_files = collect_unmanaged_router_files(cfg, router_name)

        if (
            not unmanaged_network
            and not unmanaged_firewall
            and not unmanaged_bootstrap.strip()
            and not unmanaged_files
        ):
            continue

        print_router_header(router_name, first=not printed_any)
        printed_any = True

        print_uci_section("network_part", unmanaged_network)
        print_uci_section("firewall_part", unmanaged_firewall)
        print_text_section("bootstrap.sh", unmanaged_bootstrap)
        print_file_list_section("extra files", unmanaged_files)

    unmanaged_server_files = collect_unmanaged_server_files(cfg)
    if unmanaged_server_files:
        print_router_header(str(SERVER_ROOT), first=not printed_any)
        printed_any = True
        print_file_list_section("extra files", unmanaged_server_files)

    if not printed_any:
        print("No unmanaged content found.")


def render_unmanaged_report(cfg: ConfigData) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_unmanaged_report(cfg)
    return buf.getvalue()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Show unmanaged parts above marker in router managed files. "
            "Generated UCI/bootstrap blocks are hidden only on byte-exact "
            "match against blocks derived from config.json and existing secrets; "
            "extra files are compared against the expected file set."
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    ap.add_argument(
        "--details",
        action="store_true",
        help="print full unmanaged report after its sha256 hash when unmanaged content exists",
    )
    args = ap.parse_args(argv)

    raw_cfg = load_json_config(Path(args.config))
    cfg = build_config_data(raw_cfg)

    report = render_unmanaged_report(cfg)

    if report.strip() == "No unmanaged content found.":
        print(report, end="")
        return

    digest = sha256_text(report)[:UNMANAGED_REPORT_HASH_LEN]
    print(f"unmanaged-sha256: {digest}")

    if args.details:
        print()
        # Print directly instead of reusing the captured plain-text report, so
        # terminal-only color can be applied without affecting the hash.
        print_unmanaged_report(cfg)


if __name__ == "__main__":
    main()
