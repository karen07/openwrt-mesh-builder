#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

from .config_firewall_model import expand_firewall_targets
from .config_model import ConfigData
from .config_schema import FIREWALL_ALLOW_KIND_ROUTER
from .file_ops import rm, write
from .layout import router_path
from .uci import render_uci_block

MESH_DNS_SUFFIX = ".mesh"
MESH_DNS_HOST_PREFIX = "router-"


def router_mesh_dns_label(name: str) -> str:
    return name.lower().replace("_", "-")


def router_mesh_dns_name(name: str) -> str:
    return f"{MESH_DNS_HOST_PREFIX}{router_mesh_dns_label(name)}{MESH_DNS_SUFFIX}"


def router_allow_to_router_targets(cfg: ConfigData, router_name: str) -> list[str]:
    targets: set[str] = set()
    for allow in cfg.firewall_allows:
        if allow.kind != FIREWALL_ALLOW_KIND_ROUTER:
            continue
        if allow.source_router != router_name:
            continue
        targets.update(expand_firewall_targets(cfg, allow))
    return sorted(targets, key=str.lower)


def build_mesh_dns_text(cfg: ConfigData, router_name: str) -> str:
    blocks: list[str] = []
    for target_name in router_allow_to_router_targets(cfg, router_name):
        target = cfg.router_by_name[target_name]
        blocks.append(
            render_uci_block(
                "hostrecord",
                options={
                    "name": router_mesh_dns_name(target.name),
                    "ip": target.lan_ipaddr.split("/", 1)[0],
                },
            )
        )
    return "\n\n".join(blocks).rstrip() + "\n" if blocks else ""


def build_dhcp_text(cfg: ConfigData, router_name: str) -> str:
    blocks: list[str] = []
    mesh_dns = build_mesh_dns_text(cfg, router_name).strip()
    if mesh_dns:
        blocks.append(mesh_dns)

    dhcp = cfg.dhcp[router_name]
    for host in dhcp.hosts:
        options = {"name": host.name, "ip": host.ip, "mac": host.mac}
        lists: dict[str, list[str]] = {}
        if host.tags:
            lists["tag"] = list(host.tags)
        blocks.append(render_uci_block("host", options=options, lists=lists))

    for tag in dhcp.tags:
        blocks.append(
            render_uci_block(
                "tag",
                name=tag.name,
                lists={"dhcp_option": list(tag.dhcp_options)},
            )
        )

    return "\n" + "\n\n".join(blocks) + "\n" if blocks else ""


def update_dhcp_part(cfg: ConfigData, router_name: str) -> None:
    path = router_path(cfg, router_name, "dhcp")
    generated = build_dhcp_text(cfg, router_name)
    if generated:
        write(path, generated)
    else:
        rm(path)
