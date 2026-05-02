#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re

try:
    from .common import ConfigData, ExitHub, exit_reverse_listen_port
    from .default import IPIP_DEFAULT_MTU, TUNNEL_MTU
except ImportError:
    from common import ConfigData, ExitHub, exit_reverse_listen_port
    from default import IPIP_DEFAULT_MTU, TUNNEL_MTU


def mtu_uci_options() -> dict[str, str]:
    return {"mtu": str(TUNNEL_MTU)} if TUNNEL_MTU is not None else {}


def maybe_mtu_conf_line() -> list[str]:
    return [f"MTU = {TUNNEL_MTU}"] if TUNNEL_MTU is not None else []


def ipip_mtu_value() -> int | None:
    if IPIP_DEFAULT_MTU is not None:
        return IPIP_DEFAULT_MTU
    if TUNNEL_MTU is not None:
        return TUNNEL_MTU - 20
    return None


def ipip_mtu_uci_options() -> dict[str, str]:
    value = ipip_mtu_value()
    return {"mtu": str(value)} if value is not None else {}


def exit_hub_is_public(hub: ExitHub) -> bool:
    return bool(hub.listen_ip)


def router_is_public_mesh_hub(cfg: ConfigData, router_name: str) -> bool:
    return router_name in cfg.mesh_hubs_by_name


def router_exit_listen_port(
    cfg: ConfigData,
    hub: ExitHub,
    router_name: str,
) -> int:
    return exit_reverse_listen_port(cfg, hub, router_name)


def exit_reverse_firewall_rule_name(hub_name: str) -> str:
    return f"Allow-Exit-Reverse-{hub_name}"


def exit_route_env_key(name: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_]", "_", name).upper()
    if not key or key[0].isdigit():
        key = f"_{key}"
    return key
