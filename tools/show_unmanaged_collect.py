#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re

try:
    from .common import *
    from .managed_blocks import (
        collect_unmanaged_uci_blocks,
        strip_exact_text_blocks,
        strip_outer_blank_lines,
        uci_counter_from_text,
    )
    from .generated_files import (
        expected_router_generated_exact_paths,
        expected_server_exact_paths,
        expected_sync_router_paths,
    )
    from .generate_access import build_access_state
    from .generate_exit import (
        build_exit_in_network_interface_block,
        build_exit_ipip_interface_block,
        build_exit_out_network_interface_block,
        build_material_for_exit,
        build_material_for_exit_reverse,
    )
    from .generate_firewall import build_firewall_blocks
    from .generate_mesh import build_mesh_state
    from .generate_router_misc import (
        build_doh_source_addr_block,
        build_openvpn_babeld_hotplug_block,
        build_subnet_hostname_block,
        build_wifi_block,
        router_has_openvpn_access,
    )
    from .tunnel_model import exit_hub_is_public, router_is_public_mesh_hub
    from .default import EXPECTED_MANAGED_ROUTER_DIRS
except ImportError:
    from common import *  # type: ignore
    from managed_blocks import (  # type: ignore
        collect_unmanaged_uci_blocks,
        strip_exact_text_blocks,
        strip_outer_blank_lines,
        uci_counter_from_text,
    )
    from generated_files import (  # type: ignore
        expected_router_generated_exact_paths,
        expected_server_exact_paths,
        expected_sync_router_paths,
    )
    from generate_access import build_access_state  # type: ignore
    from generate_exit import (  # type: ignore
        build_exit_in_network_interface_block,
        build_exit_ipip_interface_block,
        build_exit_out_network_interface_block,
        build_material_for_exit,
        build_material_for_exit_reverse,
    )
    from generate_firewall import build_firewall_blocks  # type: ignore
    from generate_mesh import build_mesh_state  # type: ignore
    from generate_router_misc import (  # type: ignore
        build_doh_source_addr_block,
        build_openvpn_babeld_hotplug_block,
        build_subnet_hostname_block,
        build_wifi_block,
        router_has_openvpn_access,
    )
    from tunnel_model import exit_hub_is_public, router_is_public_mesh_hub  # type: ignore
    from default import EXPECTED_MANAGED_ROUTER_DIRS  # type: ignore

EXPECTED_UNMANAGED_ROUTER_EXACT = {}
EXPECTED_GENERATION_STATE_CACHE: dict[int, dict[str, dict[str, object]]] = {}


# ============================================================
# STRICT GENERATED BLOCK LOGIC
# ============================================================


def expected_router_generation_state(
    cfg: ConfigData,
) -> dict[str, dict[str, object]]:
    cached = EXPECTED_GENERATION_STATE_CACHE.get(id(cfg))
    if cached is not None:
        return cached

    existing = load_existing_network_cfgs(cfg)

    access_blocks, _access_states, access_names = build_access_state(
        cfg=cfg,
        existing_all=existing,
        access_groups=cfg.access,
        force=False,
        verbose=False,
    )

    mesh_blocks, mesh_ifaces, _mesh_states = build_mesh_state(
        cfg=cfg,
        existing_all=existing,
        force=False,
        verbose=False,
    )

    router_exit_blocks: dict[str, dict[str, str]] = {r: {} for r in cfg.router_names}
    router_exit_ipip_blocks: dict[str, dict[str, str]] = {
        r: {} for r in cfg.router_names
    }
    router_exit_ifaces: dict[str, list[str]] = {r: [] for r in cfg.router_names}

    for hub in cfg.exit_hubs:
        for router_name in cfg.router_names:
            router_cfg = existing[router_name]
            blocks: list[str] = []

            if exit_hub_is_public(hub):
                client_alias = build_exit_client_alias(cfg, hub.name, router_name)
                link = compute_exit_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_link_key(hub.name, router_name))
                iface_name = exit_out_iface_name(hub.name)
                keys = build_material_for_exit(
                    router_name=router_name,
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=False,
                )
                blocks.append(
                    build_exit_out_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

            if router_is_public_mesh_hub(cfg, router_name):
                client_alias = build_exit_reverse_client_alias(
                    cfg, hub.name, router_name
                )
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_reverse_link_key(hub.name, router_name))
                iface_name = exit_in_iface_name(hub.name)
                keys = build_material_for_exit_reverse(
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=False,
                )
                blocks.append(
                    build_exit_in_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

            if blocks:
                router_exit_blocks[router_name][hub.name] = "\n".join(
                    block.strip() for block in blocks
                )

            router_exit_ipip_blocks[router_name][hub.name] = (
                build_exit_ipip_interface_block(cfg, router_name, hub)
            )

    state: dict[str, dict[str, object]] = {}

    for router_name in cfg.router_names:
        exit_text = "\n".join(
            router_exit_blocks[router_name][hub.name].strip()
            for hub in cfg.exit_hubs
            if hub.name in router_exit_blocks[router_name]
        ).strip()
        ipip_text = "\n".join(
            router_exit_ipip_blocks[router_name][hub.name].strip()
            for hub in router_exit_order_hubs(cfg, router_name)
            if hub.name in router_exit_ipip_blocks[router_name]
        ).strip()

        network_text = "\n\n".join(
            part
            for part in (
                access_blocks.get(router_name, "").strip(),
                mesh_blocks[router_name].strip(),
                exit_text,
                ipip_text,
            )
            if part
        )

        exit_ifaces = sorted(set(router_exit_ifaces[router_name]))
        active_exit_ipip_ifaces = sorted(
            {
                router_exit_ipip_iface_name(hub.name)
                for hub in router_exit_order_hubs(cfg, router_name)
            }
        )
        firewall_text = "\n\n".join(
            build_firewall_blocks(
                cfg=cfg,
                router_name=router_name,
                mesh_ifaces=mesh_ifaces[router_name],
                exit_ifaces=exit_ifaces,
                exit_ipip_ifaces=active_exit_ipip_ifaces,
                access_groups_for_router=cfg.access.get(router_name, []),
            )
        ).strip()

        state[router_name] = {
            "network": uci_counter_from_text(network_text, where="show_unmanaged"),
            "firewall": uci_counter_from_text(firewall_text, where="show_unmanaged"),
        }

    EXPECTED_GENERATION_STATE_CACHE[id(cfg)] = state
    return state


def exact_bootstrap_blocks(cfg: ConfigData, router_name: str) -> list[str]:
    router = router_or_die(cfg, router_name)
    blocks = [
        build_subnet_hostname_block(router),
        build_wifi_block(cfg, router_name),
        build_doh_source_addr_block(router),
    ]
    if router_has_openvpn_access(cfg, router_name):
        blocks.append(build_openvpn_babeld_hotplug_block())
    return blocks


def strip_managed_bootstrap(
    text_before_marker: str,
    cfg: ConfigData,
    router_name: str,
) -> str:
    text = text_before_marker.strip()

    if not text:
        return ""

    lines = strip_outer_blank_lines(text_before_marker.splitlines())

    # Drop only the standard shell/function wrapper.  Everything inside
    # customization() is checked against exact generated snippets below.
    if lines and lines[0].strip() == "#!/bin/sh":
        lines = strip_outer_blank_lines(lines[1:])

    if lines and re.match(r"^\s*customization\s*\(\)\s*\{\s*$", lines[0]):
        lines = strip_outer_blank_lines(lines[1:])
        if lines and lines[-1].strip() == "}":
            lines = strip_outer_blank_lines(lines[:-1])

    lines = strip_exact_text_blocks(
        lines,
        exact_bootstrap_blocks(cfg, router_name),
        where="show_unmanaged",
    )

    return "\n".join(lines).strip("\n")


# ============================================================
# COLLECTORS
# ============================================================


def collect_unmanaged_network_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    path = router_path(cfg, router_name, "network")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)

    expected = expected_router_generation_state(cfg)[router_name]["network"].copy()
    return collect_unmanaged_uci_blocks(before_marker, expected, where="show_unmanaged")


def collect_unmanaged_firewall_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    path = router_path(cfg, router_name, "firewall")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)

    expected = expected_router_generation_state(cfg)[router_name]["firewall"].copy()
    return collect_unmanaged_uci_blocks(before_marker, expected, where="show_unmanaged")


def collect_unmanaged_bootstrap_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> str:
    path = router_path(cfg, router_name, "bootstrap")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)
    return strip_managed_bootstrap(
        before_marker,
        cfg=cfg,
        router_name=router_name,
    )


def collect_unmanaged_router_files(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    root = router_dir(cfg, router_name)
    if not root.exists():
        die(f"router dir does not exist: {root}")

    expected_exact = expected_router_generated_exact_paths(cfg, router_name)
    sync_exact, sync_dirs = expected_sync_router_paths()

    unmanaged: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(root)

        if rel in EXPECTED_UNMANAGED_ROUTER_EXACT:
            continue
        if any(is_under(rel, d) for d in EXPECTED_MANAGED_ROUTER_DIRS):
            continue
        if rel in expected_exact:
            continue
        if rel in sync_exact:
            continue
        if any(is_under(rel, d) for d in sync_dirs):
            continue

        unmanaged.append(str(rel))

    return unmanaged


def collect_unmanaged_server_files(cfg: ConfigData) -> list[str]:
    root = SERVER_ROOT
    if not root.exists():
        return []

    expected_exact = expected_server_exact_paths(cfg)

    unmanaged: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        if path not in expected_exact:
            unmanaged.append(str(path))

    return unmanaged
