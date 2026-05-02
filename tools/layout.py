#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .default import (
        REL,
        ROUTERS_ROOT,
        SERVER_BABELD_CONF_PREFIX,
        SERVER_BABELD_CONF_SUFFIX,
        SERVER_ROOT,
        TOPOLOGY_2D_OUT,
        TOPOLOGY_3D_OUT,
    )
except ImportError:
    from default import (  # type: ignore
        REL,
        ROUTERS_ROOT,
        SERVER_BABELD_CONF_PREFIX,
        SERVER_BABELD_CONF_SUFFIX,
        SERVER_ROOT,
        TOPOLOGY_2D_OUT,
        TOPOLOGY_3D_OUT,
    )


def router_dir(cfg: object, name: str) -> Path:
    router = getattr(cfg, "router_by_name")[name]
    return ROUTERS_ROOT / router.slug


def router_path(cfg: object, name: str, kind: str) -> Path:
    return router_dir(cfg, name) / REL[kind]


def router_openvpn_root(cfg: object, router: str) -> Path:
    return router_path(cfg, router, "openvpn")


def router_openvpn_iface_dir(cfg: object, router: str, iface_name: str) -> Path:
    return router_openvpn_root(cfg, router) / iface_name


def router_openvpn_ca_dir(cfg: object, router: str, iface_name: str) -> Path:
    return router_openvpn_iface_dir(cfg, router, iface_name) / "ca"


def router_openvpn_server_conf_path(
    cfg: object,
    router: str,
    iface_name: str,
) -> Path:
    return router_openvpn_iface_dir(cfg, router, iface_name) / "server.ovpn"


def router_openvpn_clients_dir(cfg: object, router: str, iface_name: str) -> Path:
    return router_openvpn_iface_dir(cfg, router, iface_name) / "clients"


def router_wireguard_root(cfg: object, router: str) -> Path:
    return router_path(cfg, router, "wireguard")


def router_wireguard_iface_dir(cfg: object, router: str, iface_name: str) -> Path:
    return router_wireguard_root(cfg, router) / iface_name


def router_wireguard_clients_dir(cfg: object, router: str, iface_name: str) -> Path:
    return router_wireguard_iface_dir(cfg, router, iface_name) / "clients"


def server_dir_name(exit: str) -> str:
    return exit.lower()


def server_exit_dir(exit: str) -> Path:
    return SERVER_ROOT / server_dir_name(exit)


def server_path(exit: str, *parts: str) -> Path:
    return server_exit_dir(exit).joinpath(*parts)


def server_amneziawg_dir(exit: str) -> Path:
    return server_path(exit, "etc", "amnezia", "amneziawg")


def server_client_conf_path(exit: str, client_alias: str) -> Path:
    return server_amneziawg_dir(exit) / f"{client_alias}.conf"


def server_babeld_slug(exit: str) -> str:
    return exit.lower()


def server_babeld_conf_basename(exit: str) -> str:
    return f"babel{server_babeld_slug(exit)}.conf"


def server_babeld_conf_path(exit: str) -> Path:
    return server_path(exit, "etc", server_babeld_conf_basename(exit))


def server_babeld_conf_remote_path(exit: str) -> str:
    return f"{SERVER_BABELD_CONF_PREFIX}{server_babeld_slug(exit)}{SERVER_BABELD_CONF_SUFFIX}"


def topology_2d_path() -> Path:
    return Path(TOPOLOGY_2D_OUT)


def topology_3d_html_path() -> Path:
    return Path(TOPOLOGY_3D_OUT)
