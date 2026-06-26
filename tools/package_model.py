#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .default import (
        CONFIG_KEY_NAME,
        CONFIG_KEY_PACKAGES,
        CONFIG_KEY_ROUTERS,
        ROUTER_REQUIRED_ACCESS_PACKAGES,
        ROUTER_REQUIRED_PACKAGES,
    )
    from .identifiers import require_package_identifier
    from .process import die
except ImportError:
    from default import (  # type: ignore
        CONFIG_KEY_NAME,
        CONFIG_KEY_PACKAGES,
        CONFIG_KEY_ROUTERS,
        ROUTER_REQUIRED_ACCESS_PACKAGES,
        ROUTER_REQUIRED_PACKAGES,
    )
    from identifiers import require_package_identifier  # type: ignore
    from process import die  # type: ignore


def dedupe_package_names(packages: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for package in packages:
        if package in seen:
            continue
        result.append(package)
        seen.add(package)

    return result


def normalize_config_package_list(
    value: object,
    where: str,
    *,
    allow_empty: bool,
    router_override: bool,
) -> list[str]:
    if not isinstance(value, list):
        die(f"{where} must be a list of strings")
    if not value and not allow_empty:
        die(f"{where} must be a non-empty list of strings")

    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item:
            die(f"{where} must be a list of non-empty strings")
        if item in seen:
            die(f"{where}: duplicate package entry: {item}")
        seen.add(item)

        if router_override:
            if len(item) < 2 or item[0] not in "+-":
                die(f"{where} entry must start with + or -: {item}")
            package = item[1:]
            if not package:
                die(f"{where} has empty package entry: {item}")
            require_package_identifier(package, f"{where} package entry {item!r}")
        else:
            if item[0] in "+-":
                die(f"{where} entries must not start with + or -: {item}")
            require_package_identifier(item, f"{where} package entry {item!r}")

        result.append(item)

    return result


def validate_config_package_list(
    value: object,
    where: str,
    *,
    allow_empty: bool,
    router_override: bool,
) -> None:
    normalize_config_package_list(
        value,
        where,
        allow_empty=allow_empty,
        router_override=router_override,
    )


def normalize_optional_config_package_list(
    value: object,
    where: str,
    *,
    router_override: bool,
) -> list[str]:
    if value is None:
        return []
    return normalize_config_package_list(
        value,
        where,
        allow_empty=True,
        router_override=router_override,
    )


def required_managed_router_packages(access_groups: list[object]) -> list[str]:
    packages = list(ROUTER_REQUIRED_PACKAGES)

    for group in access_groups:
        packages.extend(ROUTER_REQUIRED_ACCESS_PACKAGES[group.protocol])

    return dedupe_package_names(packages)


def apply_router_package_overrides(
    base_packages: list[str],
    required_packages: list[str],
    package_overrides: list[str],
    *,
    where: str,
) -> list[str]:
    required_set = set(required_packages)
    result = dedupe_package_names(base_packages)
    present = set(result)

    for entry in package_overrides:
        op = entry[0]
        package = entry[1:]

        if op == "+":
            if package not in present:
                result.append(package)
                present.add(package)
            continue

        if package in required_set:
            die(f"{where} tries to remove required managed package: {package}")

        if package not in present:
            die(
                f"{where} tries to remove package that is not currently "
                f"installed: {package}"
            )

        result = [item for item in result if item != package]
        present.remove(package)

    return result


def validate_router_package_policy(
    routers: list[object],
    global_packages: list[str],
    access: dict[str, list[object]],
) -> None:
    for router in routers:
        required = required_managed_router_packages(access.get(router.name, []))
        result = apply_router_package_overrides(
            required + global_packages,
            required,
            router.package_overrides,
            where=f"routers[{router.name}].packages",
        )
        present = set(result)
        missing = sorted(set(required) - present)
        if missing:
            die(
                f"router {router.name}: missing required managed package(s): "
                + ", ".join(missing)
            )


def validate_raw_router_package_policy(
    raw_cfg: dict[str, object],
    cfg: object,
) -> None:
    global_packages = normalize_optional_config_package_list(
        raw_cfg.get(CONFIG_KEY_PACKAGES),
        "config.packages",
        router_override=False,
    )

    raw_routers = raw_cfg.get(CONFIG_KEY_ROUTERS, [])
    if not isinstance(raw_routers, list):
        die("config key 'routers' must be a list")

    for raw_router in raw_routers:
        if not isinstance(raw_router, dict):
            die("each router entry must be an object")
        router_name = raw_router.get(CONFIG_KEY_NAME)
        if not isinstance(router_name, str) or not router_name:
            die("router name must be a non-empty string")

        required = required_managed_router_packages(cfg.access.get(router_name, []))
        overrides = normalize_optional_config_package_list(
            raw_router.get(CONFIG_KEY_PACKAGES),
            f"routers[{router_name}].packages",
            router_override=True,
        )
        result = apply_router_package_overrides(
            required + global_packages,
            required,
            overrides,
            where=f"routers[{router_name}].packages",
        )
        missing = sorted(set(required) - set(result))
        if missing:
            die(
                f"router {router_name}: missing required managed package(s): "
                + ", ".join(missing)
            )


def managed_router_packages(cfg: object, router: object) -> list[str]:
    required = required_managed_router_packages(cfg.access.get(router.name, []))
    return apply_router_package_overrides(
        required + cfg.packages,
        required,
        router.package_overrides,
        where=f"router {router.name}.packages",
    )
