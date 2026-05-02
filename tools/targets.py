#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .process import die
    from .common import build_config_data
except ImportError:
    from process import die
    from common import build_config_data


def config_exit_names(cfg: dict[str, object]) -> list[str]:
    return [hub.name for hub in build_config_data(cfg).exit_hubs]


def select_config_names(
    configured: list[str],
    values: list[str],
    *,
    kind: str,
) -> list[str]:
    by_lc = {name.lower(): name for name in configured}

    if not values:
        return configured

    out: list[str] = []
    seen: set[str] = set()

    for value in values:
        for item in value.replace(",", " ").split():
            if not item:
                continue

            name = by_lc.get(item.lower())
            if name is None:
                die(f"unknown {kind} in selected config: {item}")

            key = name.lower()
            if key in seen:
                continue

            seen.add(key)
            out.append(name)

    return out


def selected_servers(cfg: dict[str, object], values: list[str]) -> list[str]:
    return select_config_names(config_exit_names(cfg), values, kind="server")
