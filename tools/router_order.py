#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import RouterDef, build_config_data
except ImportError:
    from common import RouterDef, build_config_data


def router_slug(name: str) -> str:
    return name.lower()


def load_routers(cfg: dict[str, object]) -> list[RouterDef]:
    return build_config_data(cfg).routers


def build_router_order(cfg: dict[str, object]) -> list[RouterDef]:
    cfg_data = build_config_data(cfg)
    routers = cfg_data.routers
    mesh_hub_names = set(cfg_data.mesh_hubs_by_name)
    main_router_name = cfg_data.main_router
    routers_by_name = cfg_data.router_by_name

    leafs = [
        r
        for r in routers
        if r.name not in mesh_hub_names and r.name != main_router_name
    ]
    mesh_non_main = [
        r for r in routers if r.name in mesh_hub_names and r.name != main_router_name
    ]

    return leafs + mesh_non_main + [routers_by_name[main_router_name]]
