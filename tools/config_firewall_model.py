#!/usr/bin/env python3
try:
    from .default import FIREWALL_TARGET_ALL, ZONE_MESH
    from .config_model import ConfigData, FirewallAllow
    from .config_schema import FIREWALL_ALLOW_KIND_ROUTER
except ImportError:
    from default import FIREWALL_TARGET_ALL, ZONE_MESH  # type: ignore
    from config_model import ConfigData, FirewallAllow  # type: ignore
    from config_schema import FIREWALL_ALLOW_KIND_ROUTER  # type: ignore


def expand_firewall_targets(cfg: ConfigData, allow: FirewallAllow) -> list[str]:
    if FIREWALL_TARGET_ALL not in allow.targets:
        return allow.targets

    return [name for name in cfg.router_names if name != allow.source_router]


def firewall_allow_rule_name(
    source_name: str,
    target_name: str,
    kind: str,
    src_zone: str = ZONE_MESH,
) -> str:
    suffix = "Router" if kind == FIREWALL_ALLOW_KIND_ROUTER else "Lan"
    return f"Allow-{source_name}-To-{target_name}-{suffix}-Via-{src_zone}"


def legacy_firewall_allow_rule_name(
    source_name: str,
    target_name: str,
    kind: str,
) -> str:
    """Name used before overlay ingress became explicit in allow-rule names."""
    suffix = "Router" if kind == FIREWALL_ALLOW_KIND_ROUTER else "Lan"
    return f"Allow-{source_name}-To-{target_name}-{suffix}"


def mesh_firewall_rule_name(_hub_name: str, target_name: str) -> str:
    return f"Allow-Mesh-{target_name}"
