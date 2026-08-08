#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .config_firewall_model import expand_firewall_targets
    from .config_schema import FIREWALL_ALLOW_KIND_ROUTER
    from .common import (
        ConfigData,
        parse_uci_block,
        read,
        render_uci_block,
        rm,
        router_path,
        split_uci_blocks,
        write,
    )
except ImportError:
    from config_firewall_model import expand_firewall_targets  # type: ignore
    from config_schema import FIREWALL_ALLOW_KIND_ROUTER  # type: ignore
    from common import (  # type: ignore
        ConfigData,
        parse_uci_block,
        read,
        render_uci_block,
        rm,
        router_path,
        split_uci_blocks,
        write,
    )


MESH_DNS_SUFFIX = ".mesh"
MESH_DNS_HOST_PREFIX = "router-"


def router_mesh_dns_label(name: str) -> str:
    # Router names are restricted by config validation to ASCII letters,
    # digits and underscores.  DNS labels use '-' instead of '_'.
    return name.lower().replace("_", "-")


def router_mesh_dns_name(name: str) -> str:
    return f"{MESH_DNS_HOST_PREFIX}{router_mesh_dns_label(name)}{MESH_DNS_SUFFIX}"


def router_allow_to_router_targets(cfg: ConfigData, router_name: str) -> list[str]:
    targets: set[str] = set()

    # dhcp_part is shared by the router itself and all of its access groups, so
    # expose the union of router-level and access-group allow_to_router targets.
    # Firewall policy still decides which source subnet can actually reach which
    # target; DNS only makes the allowed router names discoverable on this router.
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


def is_generated_mesh_dns_block(block: str) -> bool:
    parsed = parse_uci_block(block)
    if not parsed:
        return False
    if parsed.get("type") != "hostrecord":
        return False
    hostname = str(parsed.get("options", {}).get("name", ""))
    return hostname.startswith(MESH_DNS_HOST_PREFIX) and hostname.endswith(
        MESH_DNS_SUFFIX
    )


def strip_generated_mesh_dns(text: str) -> str:
    blocks = split_uci_blocks(text)
    had_generated = any(is_generated_mesh_dns_block(block) for block in blocks)

    # If the file contains no OWMB-owned records, leave it byte-for-byte intact.
    # In particular, do not eat the conventional leading blank line in *_part.
    if not had_generated:
        return text

    # Once our generated prefix is removed, discard only the separator newlines
    # that used to sit between that prefix and the user-owned UCI content.
    preserved = "".join(
        block for block in blocks if not is_generated_mesh_dns_block(block)
    )
    return preserved.lstrip("\r\n")


def merge_mesh_dns_prefix(generated: str, preserved: str) -> str:
    generated = generated.rstrip("\r\n")
    preserved = preserved.lstrip("\r\n")

    if generated and preserved:
        return "\n" + generated + "\n\n" + preserved
    if generated:
        return "\n" + generated + "\n"
    return preserved


def update_dhcp_part(cfg: ConfigData, router_name: str) -> None:
    path = router_path(cfg, router_name, "dhcp")
    original = read(path) if path.exists() else ""
    generated = build_mesh_dns_text(cfg, router_name)
    blocks = split_uci_blocks(original) if original else []
    had_generated = any(is_generated_mesh_dns_block(block) for block in blocks)

    # If this router has neither generated DNS to add nor stale generated DNS to
    # remove, leave its user-owned dhcp_part byte-for-byte unchanged.
    if not generated and not had_generated:
        return

    preserved = strip_generated_mesh_dns(original)
    updated = merge_mesh_dns_prefix(generated, preserved)

    if not updated:
        rm(path)
        return

    write(path, updated)
