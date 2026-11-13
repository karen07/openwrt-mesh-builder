#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import ipaddress
import tempfile
from pathlib import Path

from .config_exit_model import (
    router_exit_ipip_iface_name,
    router_exit_order_hubs,
    router_required_exit_hubs,
    routing_exit_policy_ids,
)
from .config_model import ConfigData
from .default import (
    DIRECT_CIDR_OVER_COVERAGE,
    DNS_FAILOVER_DOMAIN,
    DNS_FAILOVER_INTERVAL,
    DNS_FAILOVER_PROVIDER_DOMAINS,
    DNS_FAILOVER_RESOLV,
    DNS_FAILOVER_RESOLV_WAIT_MAX,
    EXIT_POLICY_BASE,
    EXIT_ROUTE_INTERVAL,
    LOCAL_DIRECT_IPSETS,
    PING_REBOOT_ARM_SUCCESSES,
    PING_REBOOT_HOSTS,
    PING_REBOOT_INTERVAL,
    PING_REBOOT_MAX_FAILURES,
    PING_REBOOT_TIMEOUT,
    PING_REBOOT_UNARMED_REBOOT,
    REL_DIRECT_IPSET,
    REL_DIRECT_STATIC_IPSET,
    ROUTER_EXAMPLE_DIR,
    RUNTIME_DIRECT_OUT_NAME,
    RUNTIME_DIRECT_STATIC_NAME,
    RUNTIME_IPSETS_DIR,
    UPDATE_IPSETS_CURL_CONNECT_TIMEOUT,
    UPDATE_IPSETS_CURL_MAX_TIME,
    UPDATE_IPSETS_CURL_RETRY,
    URL_IPINFO_LITE_CSV_GZ,
    URL_IPVERSE_ASN,
)
from .file_ops import write
from .generate_server_runtime import shell_quote
from .layout import router_dir, server_exit_dir
from .net_model import exit_announce_network
from .process import die, need, run_checked


def normalize_ipset_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for line in lines:
        item = line.strip()

        if not item or item.startswith("#"):
            continue

        if item in seen:
            continue

        seen.add(item)
        out.append(item)

    return out


def direct_static_lines(cfg: ConfigData) -> list[str]:
    lines: list[str] = []

    lines.extend(LOCAL_DIRECT_IPSETS)
    lines.extend(cfg.exit_direct.subnets)

    for hub in cfg.mesh_hubs:
        lines.append(hub.listen_ip)

    for hub in cfg.exit_hubs:
        if hub.listen_ip:
            lines.append(hub.listen_ip)
        if hub.exit_ip:
            lines.append(hub.exit_ip)

    return normalize_ipset_lines(lines)


def _read_generated_ipset(path: Path, label: str) -> list[str]:
    if not path.is_file():
        die(f"update-ipsets.sh did not create {label}: {path}")

    lines = normalize_ipset_lines(path.read_text(encoding="utf-8").splitlines())
    if not lines:
        die(f"update-ipsets.sh created empty {label}: {path}")
    return lines


def _run_update_ipsets(cfg: ConfigData, ipsets_dir: Path) -> None:
    script = ROUTER_EXAMPLE_DIR / "files/etc/scripts/update-ipsets.sh"
    if not script.is_file():
        die(f"missing update-ipsets.sh: {script}")

    need(
        "env",
        "sh",
        "curl",
        "gzip",
        "grep",
        "cut",
        "sed",
        "cmp",
        "tr",
        "wc",
        "cidr-squash",
    )

    env_args = [
        "ENV_FILE=/dev/null",
        f"IPSETS_DIR={ipsets_dir}",
        "RELOAD_FIREWALL=0",
        f"COUNTRIES={' '.join(cfg.exit_direct.countries)}",
        f"ASNS={' '.join(cfg.exit_direct.asns)}",
        f"DIR={RUNTIME_IPSETS_DIR}",
        f"STATIC_NAME={RUNTIME_DIRECT_STATIC_NAME}",
        f"OUT_NAME={RUNTIME_DIRECT_OUT_NAME}",
        f"IPINFO_URL={URL_IPINFO_LITE_CSV_GZ}",
        f"IPVERSE_ASN_URL={URL_IPVERSE_ASN}",
        f"CIDR_OVER_COVERAGE={DIRECT_CIDR_OVER_COVERAGE}",
        f"CONNECT_TIMEOUT={UPDATE_IPSETS_CURL_CONNECT_TIMEOUT}",
        f"MAX_TIME={UPDATE_IPSETS_CURL_MAX_TIME}",
        f"RETRY={UPDATE_IPSETS_CURL_RETRY}",
    ]

    run_checked(["env", *env_args, "sh", str(script)])


def build_direct_ipset_lines(
    cfg: ConfigData,
    *,
    skip_dynamic_downloads: bool = False,
) -> tuple[list[str], list[str]]:
    static_lines = direct_static_lines(cfg)
    if skip_dynamic_downloads:
        return static_lines, []

    with tempfile.TemporaryDirectory(prefix="owmb-ipsets-") as tmp_dir:
        ipsets_dir = Path(tmp_dir)
        static_path = ipsets_dir / RUNTIME_DIRECT_STATIC_NAME
        direct_path = ipsets_dir / RUNTIME_DIRECT_OUT_NAME
        static_path.write_text("\n".join(static_lines) + "\n", encoding="utf-8")

        _run_update_ipsets(cfg, ipsets_dir)

        generated_static = _read_generated_ipset(
            static_path, RUNTIME_DIRECT_STATIC_NAME
        )
        direct_lines = _read_generated_ipset(direct_path, RUNTIME_DIRECT_OUT_NAME)

    if generated_static != static_lines:
        die(f"update-ipsets.sh unexpectedly changed {RUNTIME_DIRECT_STATIC_NAME}")

    print(
        "OK: update-ipsets.sh generated "
        f"{len(static_lines)} main and {len(direct_lines)} dynamic direct entries"
    )
    return static_lines, direct_lines


def _uci_option(key: str, value: object) -> str:
    return f"    option {key} {shell_quote(str(value))}"


def _uci_list(key: str, values) -> list[str]:
    return [f"    list {key} {shell_quote(str(value))}" for value in values]


EXIT_ROUTE_MODES = frozenset(
    {
        "DIRECT",
        "AUTO",
        "SPLIT_FAIL_OPEN",
        "SPLIT_FAIL_CLOSED",
        "EXIT_FAIL_OPEN",
        "EXIT_FAIL_CLOSED",
    }
)
FIXED_EXIT_MODES = frozenset(
    {"SPLIT_FAIL_OPEN", "SPLIT_FAIL_CLOSED", "EXIT_FAIL_OPEN", "EXIT_FAIL_CLOSED"}
)


def build_exit_route_config(cfg: ConfigData, router_name: str) -> str:
    hubs = router_exit_order_hubs(cfg, router_name)
    all_hubs = router_required_exit_hubs(cfg, router_name)
    policy_ids = routing_exit_policy_ids(cfg)
    global_policy = cfg.exit_routes_by_router[router_name]

    lines = [
        "",
        "config state 'main'",
        _uci_option("table", EXIT_POLICY_BASE),
        _uci_option("interval", EXIT_ROUTE_INTERVAL),
        _uci_option("mode", global_policy.mode),
    ]
    if global_policy.exit_name is not None:
        lines.append(_uci_option("exit", global_policy.exit_name))
    lines.extend(_uci_list("base_auto_exit", (hub.name for hub in hubs)))
    lines.extend(_uci_list("auto_exit", global_policy.auto_exit))

    for hub in all_hubs:
        lines.extend(
            [
                "",
                f"config exit {shell_quote(hub.name)}",
                _uci_option("prefix", exit_announce_network(hub)),
                _uci_option("policy", policy_ids[hub.name]),
                _uci_option("interface", router_exit_ipip_iface_name(hub.name)),
            ]
        )

    # Device policies are generated only from config.json routing_rules.
    devices = {
        rule.src_ip.split("/", 1)[0]: rule
        for rule in cfg.routing_rules_by_router.get(router_name, [])
    }
    for ip in sorted(devices, key=ipaddress.IPv4Address):
        rule = devices[ip]
        lines.extend(
            [
                "",
                "config device",
                _uci_option("ip", ip),
                _uci_option("mode", rule.mode.upper()),
            ]
        )
        if rule.exit_name is not None:
            lines.append(_uci_option("exit", rule.exit_name))
    return "\n".join(lines) + "\n"


def build_router_runtime_configs(cfg: ConfigData, router_name: str) -> dict[str, str]:
    hubs = router_exit_order_hubs(cfg, router_name)
    all_hubs = router_required_exit_hubs(cfg, router_name)
    policy_ids = routing_exit_policy_ids(cfg)
    ipsets = [
        "config settings 'main'",
        *_uci_list("country", cfg.exit_direct.countries),
        *_uci_list("asn", cfg.exit_direct.asns),
        _uci_option("dir", RUNTIME_IPSETS_DIR),
        _uci_option("static_name", RUNTIME_DIRECT_STATIC_NAME),
        _uci_option("out_name", RUNTIME_DIRECT_OUT_NAME),
        _uci_option("ipinfo_url", URL_IPINFO_LITE_CSV_GZ),
        _uci_option("ipverse_asn_url", URL_IPVERSE_ASN),
        _uci_option("cidr_over_coverage", DIRECT_CIDR_OVER_COVERAGE),
        _uci_option("connect_timeout", UPDATE_IPSETS_CURL_CONNECT_TIMEOUT),
        _uci_option("max_time", UPDATE_IPSETS_CURL_MAX_TIME),
        _uci_option("retry", UPDATE_IPSETS_CURL_RETRY),
    ]
    dns = [
        "config settings 'main'",
        _uci_option("domain", DNS_FAILOVER_DOMAIN),
        _uci_option("interval", DNS_FAILOVER_INTERVAL),
        _uci_option("resolv", DNS_FAILOVER_RESOLV),
        _uci_option("resolv_wait_max", DNS_FAILOVER_RESOLV_WAIT_MAX),
        *_uci_list("provider_domain", DNS_FAILOVER_PROVIDER_DOMAINS),
    ]
    ping = [
        "config settings 'main'",
        *_uci_list("host", PING_REBOOT_HOSTS),
        _uci_option("arm_successes", PING_REBOOT_ARM_SUCCESSES),
        _uci_option("unarmed_reboot", PING_REBOOT_UNARMED_REBOOT),
        _uci_option("interval", PING_REBOOT_INTERVAL),
        _uci_option("max_failures", PING_REBOOT_MAX_FAILURES),
        _uci_option("timeout", PING_REBOOT_TIMEOUT),
    ]
    return {
        name: "\n" + "\n".join(lines) + "\n"
        for name, lines in (
            ("update_ipsets", ipsets),
            ("dns_failover", dns),
            ("ping_reboot", ping),
        )
    }


def write_ipsets_at(
    root: Path,
    cfg: ConfigData,
    router_name: str | None = None,
    *,
    static_lines: list[str] | None = None,
    direct_lines: list[str] | None = None,
) -> None:
    if static_lines is None or direct_lines is None:
        static_lines, direct_lines = build_direct_ipset_lines(cfg)

    write(root / REL_DIRECT_STATIC_IPSET, "\n".join(static_lines) + "\n")
    if router_name is not None:
        for name, content in build_router_runtime_configs(cfg, router_name).items():
            write(root / "files/etc/config" / name, content)
        path = root / "files/etc/config/exit_route"
        write(path, build_exit_route_config(cfg, router_name))
    write(root / REL_DIRECT_IPSET, "\n".join(direct_lines) + "\n")


def write_router_ipsets(
    cfg: ConfigData,
    router_name: str,
    *,
    static_lines: list[str] | None = None,
    direct_lines: list[str] | None = None,
) -> None:
    write_ipsets_at(
        router_dir(cfg, router_name),
        cfg,
        router_name,
        static_lines=static_lines,
        direct_lines=direct_lines,
    )


def write_server_ipsets(
    cfg: ConfigData,
    exit_name: str,
    *,
    static_lines: list[str] | None = None,
    direct_lines: list[str] | None = None,
) -> None:
    if static_lines is None or direct_lines is None:
        static_lines, direct_lines = build_direct_ipset_lines(cfg)

    server_ipsets = server_exit_dir(exit_name) / RUNTIME_IPSETS_DIR.lstrip("/")
    write(
        server_ipsets / RUNTIME_DIRECT_STATIC_NAME,
        "\n".join(static_lines) + "\n",
    )
    write(
        server_ipsets / RUNTIME_DIRECT_OUT_NAME,
        "\n".join(direct_lines) + "\n",
    )
