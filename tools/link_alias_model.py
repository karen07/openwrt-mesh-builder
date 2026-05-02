#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import hashlib

try:
    from .config_model import ConfigData
    from .default import ANON_LINK_ALIAS_HEX_LEN
    from .link_model import exit_exit_link_pair_for_hubs, exit_exit_pair_names
    from .process import die
except ImportError:
    from config_model import ConfigData  # type: ignore
    from default import ANON_LINK_ALIAS_HEX_LEN  # type: ignore
    from link_model import exit_exit_link_pair_for_hubs, exit_exit_pair_names  # type: ignore
    from process import die  # type: ignore


def _router_or_die(cfg: ConfigData, name: str) -> None:
    if name not in cfg.router_by_name:
        die(f"unknown router: {name}")


def anonymized_link_alias(kind: str, hub_name: str, router_name: str) -> str:
    # Keep server-side AWG interface/config names anonymous and stable.
    # Format: 8 hex chars, for example 3f8a91c2.
    payload = f"{kind}\0{hub_name}\0{router_name}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:ANON_LINK_ALIAS_HEX_LEN]


def build_exit_base_alias(cfg: ConfigData, hub_name: str, router_name: str) -> str:
    _router_or_die(cfg, router_name)
    return anonymized_link_alias("exit", hub_name, router_name)


def build_exit_client_alias(cfg: ConfigData, hub_name: str, router_name: str) -> str:
    # Router/leaf/spine dials public exit (ExitOut on the router side), so the
    # exit-server-side AWG config is the listener/inbound side of that session.
    return f"{build_exit_base_alias(cfg, hub_name, router_name)}In"


def build_exit_reverse_base_alias(
    cfg: ConfigData, hub_name: str, router_name: str
) -> str:
    if router_name not in cfg.mesh_hubs_by_name:
        die(f"router {router_name} is not a public mesh hub")
    return anonymized_link_alias("exit-in", hub_name, router_name)


def build_exit_reverse_client_alias(
    cfg: ConfigData, hub_name: str, router_name: str
) -> str:
    # Exit dials public spine (ExitIn on the router side), so the exit-server
    # AWG config is the client/outbound side of that reverse session.
    return f"{build_exit_reverse_base_alias(cfg, hub_name, router_name)}Out"


def build_exit_exit_base_alias(
    cfg: ConfigData, client_name: str, server_name: str
) -> str:
    client, server = exit_exit_pair_names(client_name, server_name)
    if client not in cfg.exit_hubs_by_name or server not in cfg.exit_hubs_by_name:
        die(f"unknown exit-exit pair: {client_name}<->{server_name}")
    return anonymized_link_alias("exit-exit", client, server)


def build_exit_exit_alias(cfg: ConfigData, local_name: str, peer_name: str) -> str:
    client_name, server_name = exit_exit_link_pair_for_hubs(cfg, local_name, peer_name)
    base = build_exit_exit_base_alias(cfg, client_name, server_name)
    if local_name == client_name:
        return f"{base}Out"
    if local_name == server_name:
        return f"{base}In"
    die(f"bad exit-exit alias mapping: {local_name}<->{peer_name}")


def build_mesh_client_alias(cfg: ConfigData, hub_name: str, router_name: str) -> str:
    _router_or_die(cfg, router_name)
    return anonymized_link_alias("mesh", hub_name, router_name)
