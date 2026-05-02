#!/usr/bin/env python3
import re

try:
    from .process import die
    from .default import *
    from .identifiers import (
        require_device_profile_arch,
        require_device_profile_board,
        require_file_identifier,
    )
    from .package_model import validate_config_package_list
    from .awg_model import AWG_KEYS
except ImportError:
    from process import die  # type: ignore
    from default import *  # type: ignore
    from identifiers import (  # type: ignore
        require_device_profile_arch,
        require_device_profile_board,
        require_file_identifier,
    )
    from package_model import validate_config_package_list  # type: ignore
    from awg_model import AWG_KEYS  # type: ignore

CONFIG_KEYS = {
    CONFIG_KEY_SSH_KEY_DIR,
    CONFIG_KEY_SECRETS_KEY_PATH,
    CONFIG_KEY_MATERIALS_KEY_PATH,
    CONFIG_KEY_OPENWRT_VERSION,
    CONFIG_KEY_PACKAGES,
    CONFIG_KEY_DEVICE_PROFILES,
    CONFIG_KEY_MAIN_ROUTER,
    CONFIG_KEY_ROUTERS,
    CONFIG_KEY_MESH_HUBS,
    CONFIG_KEY_EXIT_HUBS,
    CONFIG_KEY_EXIT_ORDER,
    CONFIG_KEY_ACCESS,
}

DEVICE_PROFILE_KEYS = {CONFIG_KEY_BOARD, CONFIG_KEY_ARCH}

ROUTER_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_DEVICE_PROFILE,
    CONFIG_KEY_SUBNET,
    CONFIG_KEY_PACKAGES,
    CONFIG_KEY_EXIT_ORDER,
    CONFIG_KEY_ALLOW_TO_LAN,
    CONFIG_KEY_ALLOW_TO_ROUTER,
    CONFIG_KEY_WIFI_2G,
    CONFIG_KEY_WIFI_5G,
}

WIFI_KEYS = {CONFIG_KEY_SSID, CONFIG_KEY_KEY, CONFIG_KEY_BLOCKED_MACS}
WIFI_CONFIG_KEYS = (CONFIG_KEY_WIFI_2G, CONFIG_KEY_WIFI_5G)

MESH_HUB_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_LISTEN_IP,
    CONFIG_KEY_ACCESS_ONLY,
}

EXIT_HUB_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_LISTEN_IP,
    CONFIG_KEY_EXIT_IP,
}

ACCESS_PROTOCOLS = {PROTOCOL_WIREGUARD, PROTOCOL_OPENVPN, PROTOCOL_AMNEZIAWG}
ACCESS_POLICIES = {ACCESS_POLICY_TRUSTED, ACCESS_POLICY_TRANSIT}

FIREWALL_ALLOW_KIND_ROUTER = "router"
FIREWALL_ALLOW_KIND_LAN = "lan"

ACCESS_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_PROTOCOL,
    CONFIG_KEY_POLICY,
    CONFIG_KEY_PORT,
    CONFIG_KEY_SUBNET,
    CONFIG_KEY_USERS,
    CONFIG_KEY_ALLOW_TO_LAN,
    CONFIG_KEY_ALLOW_TO_ROUTER,
    CONFIG_KEY_AWG,
}


def validate_default_exit_direct_config() -> None:
    try:
        from .config_exit_model import load_exit_direct_config
    except ImportError:
        from config_exit_model import load_exit_direct_config  # type: ignore
    load_exit_direct_config()


def require_known_keys(raw: dict[str, object], where: str, allowed: set[str]) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        die(f"{where}: unknown config key(s): {', '.join(unknown)}")


def normalize_openwrt_version(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{where} must be a non-empty string")

    version = value.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        die(f"{where} must be numeric and >= {MIN_OPENWRT_VERSION_TEXT}: " f"{version}")

    parts = version.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    if (major, minor) < MIN_OPENWRT_VERSION:
        die(f"{where} must be >= {MIN_OPENWRT_VERSION_TEXT}")

    return version


def validate_exit_order_shape(value: object, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not value:
        die(f"{where} must be a non-empty list of exit hub names")

    seen: set[str] = set()
    for idx, name in enumerate(value, start=1):
        if isinstance(name, list):
            die(
                f"{where}[{idx}] must be an exit hub name, "
                "not a nested list; same-priority exit groups are not supported"
            )
        if not isinstance(name, str) or not name:
            die(f"{where}[{idx}] must be a non-empty exit hub name")
        if name in seen:
            die(f"{where}: duplicate exit hub name: {name}")
        seen.add(name)


def validate_config_known_keys(raw_cfg: dict[str, object]) -> None:
    require_known_keys(raw_cfg, "config", CONFIG_KEYS)

    validate_exit_order_shape(raw_cfg.get(CONFIG_KEY_EXIT_ORDER), "config.exit_order")

    raw_ssh_key_dir = raw_cfg.get(CONFIG_KEY_SSH_KEY_DIR)
    if raw_ssh_key_dir is None:
        die(
            f"missing required config key {CONFIG_KEY_SSH_KEY_DIR!r}; "
            "set it explicitly, for example: "
            '"ssh_key_dir": "~/.ssh/router-autoinstall-prod"'
        )
    if not isinstance(raw_ssh_key_dir, str) or not raw_ssh_key_dir.strip():
        die(f"config.{CONFIG_KEY_SSH_KEY_DIR} must be a non-empty string")

    if CONFIG_KEY_SECRET_KEY in raw_cfg:
        die(
            f"legacy config.{CONFIG_KEY_SECRET_KEY} is not supported; "
            f"use {CONFIG_KEY_SECRETS_KEY_PATH!r} and {CONFIG_KEY_MATERIALS_KEY_PATH!r}"
        )

    for key_name in (CONFIG_KEY_SECRETS_KEY_PATH, CONFIG_KEY_MATERIALS_KEY_PATH):
        raw_key_path = raw_cfg.get(key_name)
        if raw_key_path is None:
            die(f"missing required config key {key_name!r}")
        if not isinstance(raw_key_path, str) or not raw_key_path.strip():
            die(f"config.{key_name} must be a non-empty string")

    normalize_openwrt_version(
        raw_cfg.get(CONFIG_KEY_OPENWRT_VERSION),
        "config.openwrt_version",
    )

    raw_packages = raw_cfg.get(CONFIG_KEY_PACKAGES)
    if raw_packages is not None:
        validate_config_package_list(
            raw_packages,
            "config.packages",
            allow_empty=True,
            router_override=False,
        )

    raw_profiles = raw_cfg.get(CONFIG_KEY_DEVICE_PROFILES, {})
    if raw_profiles is not None:
        if not isinstance(raw_profiles, dict):
            die("config key 'device_profiles' must be an object")
        for profile_name, profile in raw_profiles.items():
            require_file_identifier(
                profile_name,
                f"device_profiles[{profile_name}] profile name",
            )
            if not isinstance(profile, dict):
                die(f"device_profiles[{profile_name}] must be an object")
            where = f"device_profiles[{profile_name}]"
            require_known_keys(profile, where, DEVICE_PROFILE_KEYS)
            require_device_profile_board(
                profile.get(CONFIG_KEY_BOARD), f"{where}.board"
            )
            require_device_profile_arch(profile.get(CONFIG_KEY_ARCH), f"{where}.arch")

    raw_routers = raw_cfg.get(CONFIG_KEY_ROUTERS, [])
    if raw_routers is not None:
        if not isinstance(raw_routers, list):
            die("config key 'routers' must be a list")
        for idx, raw in enumerate(raw_routers, start=1):
            if not isinstance(raw, dict):
                die(f"routers[{idx}] must be an object")
            name = raw.get(CONFIG_KEY_NAME, idx)
            where = f"routers[{name}]"
            require_known_keys(raw, where, ROUTER_KEYS)

            validate_exit_order_shape(
                raw.get(CONFIG_KEY_EXIT_ORDER),
                f"{where}.exit_order",
            )

            packages = raw.get(CONFIG_KEY_PACKAGES)
            if packages is not None:
                validate_config_package_list(
                    packages,
                    f"{where}.packages",
                    allow_empty=True,
                    router_override=True,
                )

            profile_name = raw.get(CONFIG_KEY_DEVICE_PROFILE)
            if profile_name is None:
                die(f"{where}.device_profile is required")
            if not isinstance(profile_name, str) or not profile_name:
                die(f"{where}.device_profile must be a non-empty string")
            require_file_identifier(profile_name, f"{where}.device_profile")
            raw_profiles_for_check = raw_cfg.get(CONFIG_KEY_DEVICE_PROFILES, {})
            if (
                isinstance(raw_profiles_for_check, dict)
                and profile_name not in raw_profiles_for_check
            ):
                die(
                    f"{where}.device_profile references unknown profile: {profile_name}"
                )

            for wifi_key in WIFI_CONFIG_KEYS:
                wifi = raw.get(wifi_key)
                if wifi is not None:
                    if not isinstance(wifi, dict):
                        die(f"{where}.{wifi_key} must be an object")
                    require_known_keys(wifi, f"{where}.{wifi_key}", WIFI_KEYS)

    raw_mesh_hubs = raw_cfg.get(CONFIG_KEY_MESH_HUBS, [])
    if raw_mesh_hubs is not None:
        if not isinstance(raw_mesh_hubs, list):
            die("config key 'mesh_hubs' must be a list")
        for idx, raw in enumerate(raw_mesh_hubs, start=1):
            if not isinstance(raw, dict):
                die(f"mesh_hubs[{idx}] must be an object")
            name = raw.get(CONFIG_KEY_NAME, idx)
            where = f"mesh_hubs[{name}]"
            require_known_keys(raw, where, MESH_HUB_KEYS)
            access_only = raw.get(CONFIG_KEY_ACCESS_ONLY)
            if access_only is not None and not isinstance(access_only, bool):
                die(f"{where}.access_only must be a boolean")

    raw_exit_hubs = raw_cfg.get(CONFIG_KEY_EXIT_HUBS, [])
    if raw_exit_hubs is not None:
        if not isinstance(raw_exit_hubs, list):
            die("config key 'exit_hubs' must be a list")
        for idx, raw in enumerate(raw_exit_hubs, start=1):
            if not isinstance(raw, dict):
                die(f"exit_hubs[{idx}] must be an object")
            name = raw.get(CONFIG_KEY_NAME, idx)
            where = f"exit_hubs[{name}]"
            require_known_keys(raw, where, EXIT_HUB_KEYS)

    validate_default_exit_direct_config()

    raw_access = raw_cfg.get(CONFIG_KEY_ACCESS, {})
    if raw_access is not None:
        if not isinstance(raw_access, dict):
            die("config key 'access' must be an object")
        for router_name, groups in raw_access.items():
            if not isinstance(groups, list):
                die(f"access[{router_name}] must be a list")
            for idx, raw in enumerate(groups, start=1):
                if not isinstance(raw, dict):
                    die(f"access[{router_name}][{idx}] must be an object")
                iface_name = raw.get(CONFIG_KEY_NAME, idx)
                access_where = f"access[{router_name}][{iface_name}]"
                require_known_keys(
                    raw,
                    access_where,
                    ACCESS_KEYS,
                )
                awg = raw.get(CONFIG_KEY_AWG)
                if awg is not None:
                    if not isinstance(awg, dict):
                        die(f"{access_where}.awg must be an object")
                    require_known_keys(awg, f"{access_where}.awg", AWG_KEYS)
