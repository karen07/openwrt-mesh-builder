#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .process import die
except ImportError:
    from process import die  # type: ignore


def router_public_host_for_access(cfg: object, router_name: str) -> str:
    endpoint = getattr(cfg, "access_endpoints", {}).get(router_name)
    if endpoint:
        return endpoint

    die(
        f"access router {router_name}: cannot determine public host; "
        f"add a mesh_hubs entry with listen_ip, or use access_only=true"
    )
