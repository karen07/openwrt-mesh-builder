#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import shutil

from .change_report import log_change
from .config_exit_model import server_exit_subnets
from .config_model import ConfigData, ExitHub, RouterExitState
from .default import (
    BABELD_TUNNEL_TYPE,
    DIRECT_CIDR_OVER_COVERAGE,
    IPIP_SERVER_IFACE,
    NODE_SERVER_IFACE,
    ROUTER_EXAMPLE_DIR,
    RUNTIME_DIRECT_OUT_NAME,
    RUNTIME_DIRECT_STATIC_NAME,
    RUNTIME_IPSETS_DIR,
    SERVER_ENV_IPSET_NAME,
    SERVER_ROOT,
    SERVER_ROUTE_PROBE_IP,
    SERVER_TEMPLATE_DIR,
    SERVER_TEMPLATE_NAME,
    UPDATE_IPSETS_CURL_CONNECT_TIMEOUT,
    UPDATE_IPSETS_CURL_MAX_TIME,
    UPDATE_IPSETS_CURL_RETRY,
    URL_IPINFO_LITE_CSV_GZ,
    URL_IPVERSE_ASN,
)
from .file_ops import cp_tree, rm
from .layout import (
    server_amneziawg_dir,
    server_babeld_conf_remote_path,
    server_dir_name,
    server_exit_dir,
    server_path,
)
from .net_model import exit_ipip_endpoint_addr4, exit_node_addr4
from .process import die
from .stable_model import stable_babel_intervals
from .tunnel_model import ipip_mtu_value


def build_server_babeld_conf(
    hub: ExitHub,
    states: list[RouterExitState],
    exit_exit_aliases: list[str],
) -> str:
    ifaces = sorted({st.client_alias for st in states} | set(exit_exit_aliases))
    lines = []
    for iface in ifaces:
        hello_interval, update_interval = stable_babel_intervals(hub.name, iface)
        lines.append(
            f"interface {iface} type {BABELD_TUNNEL_TYPE} "
            f"hello-interval {hello_interval} "
            f"update-interval {update_interval}"
        )
    lines += [
        "",
        "install allow",
        "",
        f"redistribute if {NODE_SERVER_IFACE} allow",
        f"redistribute if {IPIP_SERVER_IFACE} allow",
        "redistribute local deny",
        "",
    ]
    return "\n".join(lines).lstrip("\n")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_server_env(
    cfg: ConfigData,
    hub: ExitHub,
    states: list[RouterExitState],
    exit_exit_aliases: list[str],
) -> str:
    service_names = sorted(
        {f"awg-quick@{st.client_alias}.service" for st in states}
        | {f"awg-quick@{alias}.service" for alias in exit_exit_aliases}
    )
    awg_services = " ".join(service_names)

    values = {
        "SERVER_NAME": hub.name,
        "NODE_ADDR4": exit_node_addr4(hub),
        "NODE_IFACE": NODE_SERVER_IFACE,
        "LISTEN_IP": hub.listen_ip,
        "EXIT_IP": hub.exit_ip,
        "IPIP_IFACE": IPIP_SERVER_IFACE,
        "IPIP_ADDR4": exit_ipip_endpoint_addr4(hub),
        **({"IPIP_MTU": str(ipip_mtu_value())} if ipip_mtu_value() is not None else {}),
        "EXIT_SUBNETS": server_exit_subnets(cfg),
        "IPSET_NAME": SERVER_ENV_IPSET_NAME,
        "ROUTE_PROBE_IP": SERVER_ROUTE_PROBE_IP,
        "AWG_SERVICES": awg_services,
        "BABELD_CONF": server_babeld_conf_remote_path(hub.name),
    }

    lines = [
        "",
        "# Runtime settings consumed by awg-server.sh.",
    ]
    for key, value in values.items():
        lines.append(f"{key}={shell_quote(value)}")
    lines.append("")
    return "\n".join(lines)


def reconcile_server_dirs(keep_exit_names: set[str]) -> None:
    SERVER_ROOT.mkdir(parents=True, exist_ok=True)
    protected = {server_dir_name(name) for name in keep_exit_names}
    protected.add(SERVER_TEMPLATE_NAME)

    for child in SERVER_ROOT.iterdir():
        if child.is_dir() and child.name not in protected:
            rm(child)


def ensure_server_layout(exit_name: str) -> None:
    dst = server_exit_dir(exit_name)
    if not dst.exists():
        if not SERVER_TEMPLATE_DIR.is_dir():
            die(f"missing server example directory: {SERVER_TEMPLATE_DIR}")
        log_change(f"Creating {dst} from {SERVER_TEMPLATE_DIR}")
        shutil.copytree(SERVER_TEMPLATE_DIR, dst, copy_function=shutil.copy2)
    else:
        cp_tree(SERVER_TEMPLATE_DIR, dst)

    for p in (
        server_path(exit_name, "etc"),
        server_amneziawg_dir(exit_name),
        server_exit_dir(exit_name) / RUNTIME_IPSETS_DIR.lstrip("/"),
        server_path(exit_name, "etc", "systemd", "system"),
    ):
        p.mkdir(parents=True, exist_ok=True)

    update_src = ROUTER_EXAMPLE_DIR / "files/etc/scripts/update-ipsets.sh"
    update_dst = server_path(exit_name, "etc", "scripts", "update-ipsets.sh")
    if not update_src.is_file():
        die(f"missing shared update-ipsets.sh: {update_src}")
    update_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(update_src, update_dst)


def remove_stale_server_amneziawg_confs(exit_name: str, keep_aliases: set[str]) -> None:
    conf_dir = server_amneziawg_dir(exit_name)
    conf_dir.mkdir(parents=True, exist_ok=True)
    keep_files = {f"{alias}.conf" for alias in keep_aliases}

    for child in conf_dir.iterdir():
        if (
            child.is_file()
            and child.name.endswith(".conf")
            and child.name not in keep_files
        ):
            rm(child)


def build_server_ipsets_env(cfg: ConfigData) -> str:
    values = {
        "COUNTRIES": " ".join(cfg.exit_direct.countries),
        "ASNS": " ".join(cfg.exit_direct.asns),
        "DIR": RUNTIME_IPSETS_DIR,
        "STATIC_NAME": RUNTIME_DIRECT_STATIC_NAME,
        "OUT_NAME": RUNTIME_DIRECT_OUT_NAME,
        "IPINFO_URL": URL_IPINFO_LITE_CSV_GZ,
        "IPVERSE_ASN_URL": URL_IPVERSE_ASN,
        "CIDR_OVER_COVERAGE": DIRECT_CIDR_OVER_COVERAGE,
        "CONNECT_TIMEOUT": str(UPDATE_IPSETS_CURL_CONNECT_TIMEOUT),
        "MAX_TIME": str(UPDATE_IPSETS_CURL_MAX_TIME),
        "RETRY": str(UPDATE_IPSETS_CURL_RETRY),
    }
    return "\n".join(
        [
            "# Runtime settings consumed by update-ipsets.sh and awg-server.sh.",
            *(f"{key}={shell_quote(str(value))}" for key, value in values.items()),
            "",
        ]
    )
