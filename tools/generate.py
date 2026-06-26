#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

try:
    from .common import *
    from .generate_firewall import update_firewall_part
    from .generate_router_misc import update_bootstrap
    from .generate_access import build_access_state
    from .generate_clients import (
        generate_openvpn_access,
        generate_openvpn_client_files,
        generate_wireguard_client_files,
        update_openvpn_uci,
    )
    from .generate_exit import (
        build_exit_exit_server_conf,
        build_exit_in_network_interface_block,
        build_exit_ipip_interface_block,
        build_exit_out_network_interface_block,
        build_material_for_exit,
        build_material_for_exit_exit,
        build_material_for_exit_reverse,
        build_server_direct_conf,
        build_server_reverse_conf,
    )
    from .generate_mesh import build_mesh_state
    from .generate_network import update_babeld, update_network_part
    from .generate_runtime import write_router_ipsets, write_server_ipsets
    from .generate_server_runtime import (
        build_server_babeld_conf,
        build_server_env,
        ensure_server_layout,
        reconcile_server_dirs,
        remove_stale_server_amneziawg_confs,
    )
    from .tunnel_model import (
        exit_hub_is_public,
        router_is_public_mesh_hub,
    )
except ImportError:
    from common import *
    from generate_firewall import update_firewall_part
    from generate_router_misc import update_bootstrap
    from generate_access import build_access_state
    from generate_clients import (
        generate_openvpn_access,
        generate_openvpn_client_files,
        generate_wireguard_client_files,
        update_openvpn_uci,
    )
    from generate_exit import (
        build_exit_exit_server_conf,
        build_exit_in_network_interface_block,
        build_exit_ipip_interface_block,
        build_exit_out_network_interface_block,
        build_material_for_exit,
        build_material_for_exit_exit,
        build_material_for_exit_reverse,
        build_server_direct_conf,
        build_server_reverse_conf,
    )
    from generate_mesh import build_mesh_state
    from generate_network import update_babeld, update_network_part
    from generate_runtime import write_router_ipsets, write_server_ipsets
    from generate_server_runtime import (
        build_server_babeld_conf,
        build_server_env,
        ensure_server_layout,
        reconcile_server_dirs,
        remove_stale_server_amneziawg_confs,
    )
    from tunnel_model import (
        exit_hub_is_public,
        router_is_public_mesh_hub,
    )


# ============================================================
# ACCESS OPENVPN HELPERS
# ============================================================


# ============================================================
# MAIN
# ============================================================


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Generator: mesh/exit AmneziaWG + access WireGuard/AmneziaWG/OpenVPN + "
            "babeld + firewall + bootstrap updates"
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="regenerate mesh/exit keys; access secrets are preserved",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="print detailed generation information",
    )
    args = ap.parse_args(argv)

    raw_cfg = load_json_config(Path(args.config))
    cfg = build_config_data(raw_cfg)

    need("wg", "openssl")
    existing = load_existing_network_cfgs(cfg)

    secrets_force = args.force
    access_force = False

    access_blocks, access_states, access_names = build_access_state(
        cfg=cfg,
        existing_all=existing,
        access_groups=cfg.access,
        force=access_force,
        verbose=args.verbose,
    )

    generate_openvpn_access(cfg=cfg, force=access_force, verbose=args.verbose)
    generate_openvpn_client_files(cfg=cfg, force=access_force, verbose=args.verbose)
    generate_wireguard_client_files(
        cfg=cfg,
        states_by_router=access_states,
        verbose=args.verbose,
    )

    keep_exit_hubs = {h.name for h in cfg.exit_hubs}
    reconcile_server_dirs(keep_exit_hubs)
    mesh_blocks, mesh_ifaces, _mesh_states = build_mesh_state(
        cfg=cfg,
        existing_all=existing,
        force=secrets_force,
        verbose=args.verbose,
    )

    router_exit_blocks: dict[str, dict[str, str]] = {r: {} for r in cfg.router_names}
    router_exit_ipip_blocks: dict[str, dict[str, str]] = {
        r: {} for r in cfg.router_names
    }
    router_exit_ifaces: dict[str, list[str]] = {r: [] for r in cfg.router_names}
    router_exit_ipip_ifaces: dict[str, list[str]] = {r: [] for r in cfg.router_names}
    hub_states: dict[str, list[RouterExitState]] = {h.name: [] for h in cfg.exit_hubs}
    exit_exit_aliases_by_hub: dict[str, list[str]] = {h.name: [] for h in cfg.exit_hubs}

    for hub in cfg.exit_hubs:
        ensure_server_layout(hub.name)

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        left_alias = build_exit_exit_alias(cfg, left_hub.name, right_hub.name)
        right_alias = build_exit_exit_alias(cfg, right_hub.name, left_hub.name)
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        key = exit_exit_link_key(left_hub.name, right_hub.name)
        awg = awg_for_infra_link(key)
        keys = build_material_for_exit_exit(
            cfg=cfg,
            left_hub=left_hub,
            right_hub=right_hub,
            force=secrets_force,
        )

        write(
            server_client_conf_path(left_hub.name, left_alias),
            build_exit_exit_server_conf(left_hub, right_hub, link, keys, awg),
        )
        write(
            server_client_conf_path(right_hub.name, right_alias),
            build_exit_exit_server_conf(right_hub, left_hub, link, keys, awg),
        )
        exit_exit_aliases_by_hub[left_hub.name].append(left_alias)
        exit_exit_aliases_by_hub[right_hub.name].append(right_alias)

        if args.verbose:
            print(
                f"EXIT-EXIT {left_hub.name:<8} Out -> {right_hub.name:<8} In "
                f"aliases={left_alias}/{right_alias} "
                f"ports={link.left_port}/{link.right_port}"
            )

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
                    force=secrets_force,
                )

                write(
                    server_client_conf_path(hub.name, client_alias),
                    build_server_direct_conf(client_alias, hub, link, keys, awg),
                )
                blocks.append(
                    build_exit_out_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

                hub_states[hub.name].append(
                    RouterExitState(
                        router_name=router_name,
                        client_alias=client_alias,
                        hub=hub,
                        link=link,
                        keys=keys,
                        awg=awg,
                    )
                )

                if args.verbose:
                    print(
                        f"EXIT-OUT {router_name:<10} -> {hub.name:<8} "
                        f"alias={client_alias:<16} port={link.port:<5}"
                    )

            if router_is_public_mesh_hub(cfg, router_name):
                client_alias = build_exit_reverse_client_alias(
                    cfg, hub.name, router_name
                )
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                key = exit_reverse_link_key(hub.name, router_name)
                awg = awg_for_infra_link(key)
                iface_name = exit_in_iface_name(hub.name)

                keys = build_material_for_exit_reverse(
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=secrets_force,
                )

                write(
                    server_client_conf_path(hub.name, client_alias),
                    build_server_reverse_conf(
                        cfg, router_name, client_alias, hub, link, keys, awg
                    ),
                )
                blocks.append(
                    build_exit_in_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

                hub_states[hub.name].append(
                    RouterExitState(
                        router_name=router_name,
                        client_alias=client_alias,
                        hub=hub,
                        link=link,
                        keys=keys,
                        awg=awg,
                    )
                )

                if args.verbose:
                    print(
                        f"EXIT-IN  {hub.name:<8} -> {router_name:<10} "
                        f"alias={client_alias:<16} port={link.port:<5}"
                    )

            if blocks:
                router_exit_blocks[router_name][hub.name] = "\n".join(
                    block.strip() for block in blocks
                )

            router_exit_ipip_blocks[router_name][hub.name] = (
                build_exit_ipip_interface_block(
                    cfg,
                    router_name,
                    hub,
                )
            )
            router_exit_ipip_ifaces[router_name].append(
                router_exit_ipip_iface_name(hub.name)
            )

        keep_server_aliases: set[str] = set(exit_exit_aliases_by_hub[hub.name])
        if exit_hub_is_public(hub):
            keep_server_aliases |= {
                build_exit_client_alias(cfg, hub.name, router_name)
                for router_name in cfg.router_names
            }
        keep_server_aliases |= {
            build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
            for mesh_hub in cfg.mesh_hubs
        }
        remove_stale_server_amneziawg_confs(hub.name, keep_server_aliases)

        write(
            server_babeld_conf_path(hub.name),
            build_server_babeld_conf(
                hub, hub_states[hub.name], exit_exit_aliases_by_hub[hub.name]
            ),
        )
        write(
            server_path(hub.name, "etc", "awg-server.env"),
            build_server_env(
                cfg, hub, hub_states[hub.name], exit_exit_aliases_by_hub[hub.name]
            ),
        )
        write_server_ipsets(cfg, hub.name)

    for router_name in cfg.router_names:
        mesh_text = mesh_blocks[router_name].strip()
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
        access_text = access_blocks.get(router_name, "").strip()

        update_network_part(
            cfg=cfg,
            router_name=router_name,
            mesh_text=mesh_text,
            exit_text=exit_text,
            ipip_text=ipip_text,
            access_text=access_text,
            access_names=access_names,
        )
        update_babeld(
            cfg=cfg,
            router_name=router_name,
            mesh_ifaces=mesh_ifaces[router_name],
            exit_ifaces=sorted(set(router_exit_ifaces[router_name])),
        )
        active_exit_ipip_ifaces = [
            router_exit_ipip_iface_name(hub.name)
            for hub in router_exit_order_hubs(cfg, router_name)
        ]
        update_firewall_part(
            cfg=cfg,
            router_name=router_name,
            mesh_ifaces=mesh_ifaces[router_name],
            exit_ifaces=sorted(set(router_exit_ifaces[router_name])),
            exit_ipip_ifaces=sorted(set(active_exit_ipip_ifaces)),
            access_groups_for_router=cfg.access.get(router_name, []),
        )
        update_bootstrap(cfg=cfg, router_name=router_name)
        update_openvpn_uci(
            cfg=cfg,
            router_name=router_name,
            groups=cfg.access.get(router_name, []),
        )
        write_router_ipsets(cfg, router_name)


if __name__ == "__main__":
    main()
