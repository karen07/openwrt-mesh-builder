#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from dataclasses import dataclass

try:
    from .common import ConfigData
    from .layout import router_path, server_amneziawg_dir
    from .uci import parse_uci_block, split_uci_blocks
except ImportError:
    from common import ConfigData  # type: ignore
    from layout import router_path, server_amneziawg_dir  # type: ignore
    from uci import parse_uci_block, split_uci_blocks  # type: ignore


@dataclass(frozen=True)
class GeneratedTopologyIndex:
    router_ifaces: dict[str, set[str]]
    exit_aliases: dict[str, set[str]]
    warnings: tuple[str, ...]


def router_generated_awg_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    path = router_path(cfg, router_name, "network")
    if not path.exists():
        return set()

    ifaces: set[str] = set()
    for block in split_uci_blocks(path.read_text(encoding="utf-8")):
        parsed = parse_uci_block(block)
        if not parsed or parsed.get("type") != "interface":
            continue
        opts = parsed.get("options", {})
        if not isinstance(opts, dict):
            continue
        if opts.get("proto") != "amneziawg":
            continue
        name = parsed.get("name")
        if isinstance(name, str) and name:
            ifaces.add(name)
    return ifaces


def generated_exit_aliases(exit_name: str) -> set[str]:
    conf_dir = server_amneziawg_dir(exit_name)
    if not conf_dir.exists():
        return set()
    return {p.stem for p in conf_dir.glob("*.conf") if p.is_file()}


def load_generated_topology_index(cfg: ConfigData) -> GeneratedTopologyIndex:
    router_ifaces = {
        name: router_generated_awg_ifaces(cfg, name) for name in cfg.router_names
    }
    exit_aliases = {hub.name: generated_exit_aliases(hub.name) for hub in cfg.exit_hubs}

    warnings: list[str] = []
    for name in cfg.router_names:
        path = router_path(cfg, name, "network")
        if not path.exists():
            warnings.append(
                f"missing generated router network config for {name}: {path}"
            )
    for hub in cfg.exit_hubs:
        path = server_amneziawg_dir(hub.name)
        if not path.exists():
            warnings.append(f"missing generated exit AWG dir for {hub.name}: {path}")

    return GeneratedTopologyIndex(
        router_ifaces=router_ifaces,
        exit_aliases=exit_aliases,
        warnings=tuple(warnings),
    )
