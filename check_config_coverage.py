#!/usr/bin/env python3
"""Ensure the bundled demonstration config covers the current config schema.

No network, firmware builder or external credentials needed; checks declarative
coverage and the in-process schema/model/runtime serialization.
"""

import argparse
from pathlib import Path

from tools import awg_model
from tools import config_schema as schema
from tools.awg_model import AWG_KEYS
from tools.config_builder import build_config_data
from tools.config_io import load_json_config
from tools.default import ROUTING_MODES
from tools.generate_runtime import EXIT_ROUTE_MODES, build_exit_route_config


def check(title, actual, required, problems):
    missing = set(required) - set(actual)
    if missing:
        problems.append(
            f"{title}: missing {', '.join(map(str, sorted(missing, key=str)))}"
        )
    else:
        print(f"OK: {title}: {len(required)}/{len(required)}")


def union_keys(items):
    result = set()
    for item in items:
        result.update(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    cfg_file = Path(args.config)
    raw = load_json_config(cfg_file)
    schema.validate_config_known_keys(raw)
    # Only during this in-memory coverage test, substitute a synthetic HMAC
    # master key. The real loader lazily creates a key file under ~/.ssh;
    # a checker must not mutate the user's private material or home directory.
    awg_model.master_key = lambda *_args, **_kwargs: bytes(32)
    cfg = build_config_data(raw)
    routers = raw["routers"]
    groups = [a for r in routers for a in r.get("access", [])]
    dhcp_hosts = [h for r in routers for h in r.get("dhcp_hosts", [])]
    route_rules = [rule for r in routers for rule in r.get("routing_rules", [])]
    route_policies = [r["exit_route"] for r in routers if "exit_route" in r]

    regions = {
        "top-level keys": (schema.CONFIG_KEYS, [raw]),
        "device profile keys": (
            schema.DEVICE_PROFILE_KEYS,
            list(raw["device_profiles"].values()),
        ),
        "router keys": (schema.ROUTER_KEYS, routers),
        "wifi keys": (
            schema.WIFI_KEYS,
            [r[k] for r in routers for k in schema.WIFI_CONFIG_KEYS if k in r],
        ),
        "pppoe keys": (
            schema.PPPOE_KEYS,
            [r["pppoe"] for r in routers if "pppoe" in r],
        ),
        "DHCP host keys": (schema.DHCP_HOST_KEYS, dhcp_hosts),
        "mesh hub keys": (schema.MESH_HUB_KEYS, raw["mesh_hubs"]),
        "EXIT hub keys": (schema.EXIT_HUB_KEYS, raw["exit_hubs"]),
        "access group keys": (schema.ACCESS_KEYS, groups),
        "AmneziaWG keys": (AWG_KEYS, [g["awg"] for g in groups if "awg" in g]),
        "device routing keys": (schema.ROUTING_RULE_KEYS, route_rules),
        "global EXIT route keys": (schema.EXIT_ROUTE_KEYS, route_policies),
    }
    problems = []
    for title, (required, items) in regions.items():
        check(title, union_keys(items), required, problems)

    check(
        "device routing modes",
        [x["mode"] for x in route_rules],
        ROUTING_MODES,
        problems,
    )
    check(
        "global EXIT route modes",
        [x["mode"] for x in route_policies],
        EXIT_ROUTE_MODES,
        problems,
    )
    check(
        "access protocols",
        [x["protocol"] for x in groups],
        schema.ACCESS_PROTOCOLS,
        problems,
    )
    check(
        "access policies",
        [x["policy"] for x in groups],
        schema.ACCESS_POLICIES,
        problems,
    )
    check(
        "protocol/policy pairs",
        [(x["protocol"], x["policy"]) for x in groups],
        [(p, q) for p in schema.ACCESS_PROTOCOLS for q in schema.ACCESS_POLICIES],
        problems,
    )
    check(
        "Wi-Fi bands",
        [k for r in routers for k in schema.WIFI_CONFIG_KEYS if k in r],
        schema.WIFI_CONFIG_KEYS,
        problems,
    )
    check(
        "hub access_only boolean",
        [h.get("access_only", False) for h in raw["mesh_hubs"]],
        (True, False),
        problems,
    )
    check(
        "EXIT endpoint types",
        [
            (
                "reverse"
                if "listen_ip" not in h
                else "snat" if "exit_ip" in h else "masquerade"
            )
            for h in raw["exit_hubs"]
        ],
        ("reverse", "masquerade", "snat"),
        problems,
    )
    check(
        "WAN types",
        ["pppoe" if "pppoe" in r else "dhcp" for r in routers],
        ("pppoe", "dhcp"),
        problems,
    )
    check(
        "PPPoE MTU variants",
        [
            "explicit" if "mtu" in r["pppoe"] else "default"
            for r in routers
            if "pppoe" in r
        ],
        ("explicit", "default"),
        problems,
    )
    check(
        "DHCP reservation kinds",
        [
            (
                "plain"
                if "dhcp_options" not in h
                else (
                    "dns_only"
                    if all(v.startswith("6,") for v in h["dhcp_options"])
                    else "other_options"
                )
            )
            for h in dhcp_hosts
        ],
        ("plain", "dns_only", "other_options"),
        problems,
    )
    check(
        "per-router package override kinds",
        [p[0] for r in routers for p in r.get("packages", [])],
        ("+", "-"),
        problems,
    )
    check(
        "version variants",
        [
            (
                "snapshot"
                if r.get("openwrt_version", raw["openwrt_version"]).endswith(
                    "-SNAPSHOT"
                )
                else "release"
            )
            for r in routers
        ],
        ("release", "snapshot"),
        problems,
    )
    check(
        "access AWG random_trailers booleans",
        [
            g["awg"].get("random_trailers")
            for g in groups
            if "awg" in g and "random_trailers" in g["awg"]
        ],
        (True, False),
        problems,
    )
    check(
        "access AWG disable_cookies booleans",
        [
            g["awg"].get("disable_cookies")
            for g in groups
            if "awg" in g and "disable_cookies" in g["awg"]
        ],
        (True, False),
        problems,
    )

    # Confirm each global EXIT mode generates its corresponding UCI state.
    for name in cfg.router_names:
        text = build_exit_route_config(cfg, name)
        mode = cfg.exit_routes_by_router[name].mode
        if f"option mode '{mode}'" not in text:
            problems.append(f"{name}: missing generated UCI mode {mode}")
    if "config device" not in build_exit_route_config(cfg, "Spine01"):
        problems.append("Spine01: no serialized per-device route rules")

    if problems:
        raise SystemExit("FAILED:\n- " + "\n- ".join(problems))
    print(
        f"OK: valid config; {len(cfg.routers)} routers, {len(cfg.exit_hubs)} EXITs, "
        f"{len(groups)} access groups, {len(route_rules)} per-device policies"
    )


if __name__ == "__main__":
    main()
