#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import contextlib
import hashlib
from collections import Counter
import io
import os
import re
from pathlib import Path

try:
    from .common import *
    from .sync_rules import SYNC_COPY_DIRS, SYNC_COPY_FILES, SYNC_MERGE_FILES
except ImportError:
    from common import *
    from sync_rules import SYNC_COPY_DIRS, SYNC_COPY_FILES, SYNC_MERGE_FILES

try:
    import generate as gen
except ImportError:
    from . import generate as gen

try:
    from .default import (
        EXPECTED_MANAGED_ROUTER_DIRS,
        UNMANAGED_REPORT_HASH_LEN,
    )
except ImportError:
    from default import (
        EXPECTED_MANAGED_ROUTER_DIRS,
        UNMANAGED_REPORT_HASH_LEN,
    )

EXPECTED_UNMANAGED_ROUTER_EXACT = {}
EXPECTED_GENERATION_STATE_CACHE: dict[int, dict[str, dict[str, object]]] = {}


def exit_reverse_firewall_rule_name(hub_name: str) -> str:
    return f"Allow-Exit-Reverse-{hub_name}"


# ============================================================
# EXPECTED FILE SETS
# ============================================================


def expected_sync_router_paths() -> tuple[set[Path], set[Path]]:
    exact = set(SYNC_COPY_FILES) | set(SYNC_MERGE_FILES)
    dirs = set(SYNC_COPY_DIRS)
    return exact, dirs


def expected_router_generated_exact_paths(
    cfg: ConfigData,
    router_name: str,
) -> set[Path]:
    root = router_dir(cfg, router_name)
    expected: set[Path] = {
        router_path(cfg, router_name, "network").relative_to(root),
        router_path(cfg, router_name, "firewall").relative_to(root),
        router_path(cfg, router_name, "bootstrap").relative_to(root),
        router_path(cfg, router_name, "babeld").relative_to(root),
        REL_DROPBEAR_AUTHORIZED_KEYS,
        REL_DIRECT_STATIC_IPSET,
        REL_RUNTIME_ENV,
        REL_DIRECT_IPSET,
    }

    if any(g.protocol == PROTOCOL_OPENVPN for g in cfg.access.get(router_name, [])):
        expected.add(router_path(cfg, router_name, "openvpn_uci").relative_to(root))

    for group in cfg.access.get(router_name, []):
        if group.protocol == PROTOCOL_OPENVPN:
            ca_dir = router_openvpn_ca_dir(cfg, router_name, group.name).relative_to(
                root
            )
            clients_dir = router_openvpn_clients_dir(
                cfg, router_name, group.name
            ).relative_to(root)

            expected.add(
                router_openvpn_server_conf_path(
                    cfg, router_name, group.name
                ).relative_to(root)
            )
            expected |= {
                ca_dir / "ca.key",
                ca_dir / "ca.pem",
            }

            for user in group.users:
                expected.add(clients_dir / f"{user}.ovpn")

        elif group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
            clients_dir = router_wireguard_clients_dir(
                cfg, router_name, group.name
            ).relative_to(root)

            for user in group.users:
                expected.add(clients_dir / f"{user}.conf")

    return expected


def expected_exit_server_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    aliases: set[str] = set()

    if hub.listen_ip:
        aliases |= {
            build_exit_client_alias(cfg, hub.name, router_name)
            for router_name in cfg.router_names
        }

    aliases |= {
        build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
        for mesh_hub in cfg.mesh_hubs
    }

    aliases |= {
        build_exit_exit_alias(cfg, hub.name, peer_name)
        for peer_name in exit_exit_peer_names_for_hub(cfg, hub)
    }

    return sorted(aliases)


def expected_server_exact_paths(cfg: ConfigData) -> set[Path]:
    expected: set[Path] = set()

    example_root = SERVER_TEMPLATE_DIR
    template_rel_files: set[Path] = set()
    if example_root.exists():
        for p in example_root.rglob("*"):
            if p.is_file():
                expected.add(p)
                template_rel_files.add(p.relative_to(example_root))

    for hub in cfg.exit_hubs:
        exit_root = server_exit_dir(hub.name)

        for rel in template_rel_files:
            expected.add(exit_root / rel)

        expected |= {
            server_babeld_conf_path(hub.name),
            exit_root / "etc/awg-server.env",
            exit_root / "etc/ipsets/direct-static.txt",
            exit_root / "etc/ipsets/direct.txt",
            exit_root / "root/.ssh/authorized_keys",
        }

        expected |= {
            server_client_conf_path(hub.name, alias)
            for alias in expected_exit_server_aliases_for_hub(cfg, hub)
        }

    return expected


# ============================================================
# STRICT GENERATED BLOCK LOGIC
# ============================================================


def uci_block_key(block: str) -> str:
    # Ignore only inter-block separator newlines.  The bytes inside the UCI
    # block itself, including indentation, option order and values, must match.
    return block.strip("\n")


def counter_from_uci_text(text: str) -> Counter[str]:
    out: Counter[str] = Counter()
    normalized = normalize_uci(text)

    for block in split_uci_blocks(normalized):
        if parse_uci_block(block):
            out[uci_block_key(block)] += 1

    return out


def consume_expected_uci_block(expected: Counter[str], block: str) -> bool:
    key = uci_block_key(block)
    if expected.get(key, 0) <= 0:
        return False
    expected[key] -= 1
    return True


def expected_router_generation_state(
    cfg: ConfigData,
) -> dict[str, dict[str, object]]:
    cached = EXPECTED_GENERATION_STATE_CACHE.get(id(cfg))
    if cached is not None:
        return cached

    existing = load_existing_network_cfgs(cfg)

    access_blocks, _access_states, access_names = gen.build_access_state(
        cfg=cfg,
        existing_all=existing,
        access_groups=cfg.access,
        force=False,
        verbose=False,
    )

    mesh_blocks, mesh_ifaces, _mesh_states = gen.build_mesh_state(
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

            if gen.exit_hub_is_public(hub):
                client_alias = build_exit_client_alias(cfg, hub.name, router_name)
                link = compute_exit_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_link_key(hub.name, router_name))
                iface_name = exit_out_iface_name(hub.name)
                keys = gen.build_material_for_exit(
                    router_name=router_name,
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=False,
                )
                blocks.append(
                    gen.build_exit_out_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

            if gen.router_is_public_mesh_hub(cfg, router_name):
                client_alias = build_exit_reverse_client_alias(
                    cfg, hub.name, router_name
                )
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_reverse_link_key(hub.name, router_name))
                iface_name = exit_in_iface_name(hub.name)
                keys = gen.build_material_for_exit_reverse(
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=False,
                )
                blocks.append(
                    gen.build_exit_in_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

            if blocks:
                router_exit_blocks[router_name][hub.name] = "\n".join(
                    block.strip() for block in blocks
                )

            router_exit_ipip_blocks[router_name][hub.name] = (
                gen.build_exit_ipip_interface_block(cfg, router_name, hub)
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
            for hub in gen.router_exit_order_hubs(cfg, router_name)
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
                for hub in gen.router_exit_order_hubs(cfg, router_name)
            }
        )
        firewall_text = build_expected_firewall_text(
            cfg=cfg,
            router_name=router_name,
            mesh_ifaces=mesh_ifaces[router_name],
            exit_ifaces=exit_ifaces,
            exit_ipip_ifaces=active_exit_ipip_ifaces,
            access_groups_for_router=cfg.access.get(router_name, []),
        )

        state[router_name] = {
            "network": counter_from_uci_text(network_text),
            "firewall": counter_from_uci_text(firewall_text),
        }

    EXPECTED_GENERATION_STATE_CACHE[id(cfg)] = state
    return state


def build_expected_firewall_text(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
    exit_ipip_ifaces: list[str],
    access_groups_for_router: list[AccessGroup],
) -> str:
    blocks: list[str] = []

    if mesh_ifaces:
        blocks.append(
            gen.build_zone(
                ZONE_MESH,
                mesh_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ifaces:
        blocks.append(
            gen.build_zone(
                ZONE_EXIT,
                exit_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ipip_ifaces:
        blocks.append(
            gen.build_zone(
                ZONE_EXIT_IPIP,
                exit_ipip_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ifaces and not config_has_allow_to_router_all(cfg):
        blocks.append(gen.build_rule_allow_ssh_from_exit_to_router().strip())

    trusted_access_ifaces = sorted(
        {g.name for g in access_groups_for_router if g.policy == ACCESS_POLICY_TRUSTED}
    )
    transit_access_ifaces = sorted(
        {g.name for g in access_groups_for_router if g.policy == ACCESS_POLICY_TRANSIT}
    )

    if trusted_access_ifaces:
        blocks.append(
            gen.build_zone(
                ZONE_TRUSTED_ACCESS,
                trusted_access_ifaces,
                input_policy=FIREWALL_TARGET_ACCEPT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if transit_access_ifaces:
        blocks.append(
            gen.build_zone(
                ZONE_TRANSIT_ACCESS,
                transit_access_ifaces,
                input_policy=FIREWALL_TARGET_REJECT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )
        blocks.append(gen.build_rule_allow_dns_transit_access().strip())

    if router_name in cfg.mesh_hubs_by_name:
        hub = cfg.mesh_hubs_by_name[router_name]

        for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
            link = compute_mesh_link_params(cfg, hub, target_name)
            blocks.append(
                gen.build_rule_allow_port_wan(
                    mesh_firewall_rule_name(hub.name, target_name),
                    link.port,
                    TRANSPORT_UDP,
                ).strip()
            )

        for exit_hub in cfg.exit_hubs:
            blocks.append(
                gen.build_rule_allow_port_wan(
                    exit_reverse_firewall_rule_name(exit_hub.name),
                    gen.router_exit_listen_port(cfg, exit_hub, router_name),
                    TRANSPORT_UDP,
                ).strip()
            )

    for group in access_groups_for_router:
        blocks.append(
            gen.build_rule_allow_port_wan(
                f"Allow-{group.name}",
                group.port,
                TRANSPORT_TCP if group.protocol == PROTOCOL_OPENVPN else TRANSPORT_UDP,
            ).strip()
        )

    for allow in cfg.firewall_allows:
        targets = expand_firewall_targets(cfg, allow)
        if router_name not in targets:
            continue

        blocks.append(
            gen.build_rule_allow_mesh_src_ip(
                firewall_allow_rule_name(allow.source_name, router_name, allow.kind),
                allow.source_subnet,
                FIREWALL_ZONE_LAN if allow.kind == FIREWALL_ALLOW_KIND_LAN else None,
            ).strip()
        )

    return "\n\n".join(blocks).strip()


def exact_bootstrap_blocks(cfg: ConfigData, router_name: str) -> list[str]:
    router = router_or_die(cfg, router_name)
    blocks = [
        gen.build_subnet_hostname_block(router),
        gen.build_wifi_block(cfg, router_name),
        gen.build_doh_source_addr_block(router),
    ]
    if gen.router_has_openvpn_access(cfg, router_name):
        blocks.append(gen.build_openvpn_babeld_hotplug_block())
    return blocks


def strip_outer_blank_lines(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def strip_exact_bootstrap_block_once(
    lines: list[str],
    block: str,
) -> tuple[list[str], bool]:
    block_lines = block.rstrip("\n").splitlines()
    if not block_lines:
        return lines, False

    out: list[str] = []
    i = 0
    removed = False

    while i < len(lines):
        if not removed and lines[i : i + len(block_lines)] == block_lines:
            i += len(block_lines)
            removed = True
            continue
        out.append(lines[i])
        i += 1

    return out, removed


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

    for block in exact_bootstrap_blocks(cfg, router_name):
        lines, _removed = strip_exact_bootstrap_block_once(lines, block)
        lines = strip_outer_blank_lines(lines)

    lines = strip_outer_blank_lines(lines)

    return "\n".join(lines).strip("\n")


def collect_unmanaged_uci_blocks_exact(
    text_before_marker: str,
    expected: Counter[str],
) -> list[str]:
    out: list[str] = []

    for block in split_uci_blocks(text_before_marker):
        key = uci_block_key(block)
        if not key.strip():
            continue

        if consume_expected_uci_block(expected, block):
            continue

        out.append(key.rstrip())

    return out


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
    return collect_unmanaged_uci_blocks_exact(before_marker, expected)


def collect_unmanaged_firewall_above_marker(
    cfg: ConfigData,
    router_name: str,
) -> list[str]:
    path = router_path(cfg, router_name, "firewall")
    text = read(path)
    before_marker, _ = split_text_by_marker(text, path)

    expected = expected_router_generation_state(cfg)[router_name]["firewall"].copy()
    return collect_unmanaged_uci_blocks_exact(before_marker, expected)


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
