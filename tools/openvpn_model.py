#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re
import tempfile
from pathlib import Path

try:
    from . import openvpn_pki
    from .default import (
        DEFAULT_CA_CN,
        DEFAULT_CERT_DAYS,
        LOCAL_TEMP_ROOT,
        OPENVPN_CLIENT_PROTO,
        OPENVPN_DATA_CIPHERS,
        OPENVPN_DEV_TYPE,
        OPENVPN_GROUP,
        OPENVPN_KEEPALIVE,
        OPENVPN_SERVER_CN,
        OPENVPN_SERVER_PROTO,
        OPENVPN_TOPOLOGY,
        OPENVPN_USER,
        OPENVPN_VERB,
        PROTOCOL_OPENVPN,
    )
    from .file_ops import read, rm, write
    from .layout import (
        router_openvpn_ca_dir,
        router_openvpn_clients_dir,
        router_openvpn_iface_dir,
        router_openvpn_root,
        router_openvpn_server_conf_path,
    )
    from .materials import (
        material_file_for_tool,
        material_plaintext,
        stored_key_material,
    )
    from .materials import write_material_file
    from .process import die
    from .uci import render_uci_block
except ImportError:
    import openvpn_pki  # type: ignore
    from default import (  # type: ignore
        DEFAULT_CA_CN,
        DEFAULT_CERT_DAYS,
        LOCAL_TEMP_ROOT,
        OPENVPN_CLIENT_PROTO,
        OPENVPN_DATA_CIPHERS,
        OPENVPN_DEV_TYPE,
        OPENVPN_GROUP,
        OPENVPN_KEEPALIVE,
        OPENVPN_SERVER_CN,
        OPENVPN_SERVER_PROTO,
        OPENVPN_TOPOLOGY,
        OPENVPN_USER,
        OPENVPN_VERB,
        PROTOCOL_OPENVPN,
    )
    from file_ops import read, rm, write  # type: ignore
    from layout import (  # type: ignore
        router_openvpn_ca_dir,
        router_openvpn_clients_dir,
        router_openvpn_iface_dir,
        router_openvpn_root,
        router_openvpn_server_conf_path,
    )
    from materials import (  # type: ignore
        material_file_for_tool,
        material_plaintext,
        stored_key_material,
    )
    from materials import write_material_file  # type: ignore
    from process import die  # type: ignore
    from uci import render_uci_block  # type: ignore


FORCED_CA_ONCE: set[str] = set()


def openvpn_server_cn(_router_name: str, _iface_name: str) -> str:
    return OPENVPN_SERVER_CN


def openvpn_client_cn(client_index_1based: int) -> str:
    return f"client{client_index_1based}"


def extract_inline_block(text: str, tag: str) -> str | None:
    pattern = re.compile(
        rf"(?ms)^[ \t]*<{re.escape(tag)}>\s*\n(?P<body>.*?)\n[ \t]*</{re.escape(tag)}>\s*$"
    )
    m = pattern.search(text)
    if not m:
        return None
    return m.group("body").strip() + "\n"


def openvpn_inline_material(text: str) -> tuple[str | None, str | None, str | None]:
    return (
        extract_inline_block(text, "ca"),
        extract_inline_block(text, "cert"),
        extract_inline_block(text, "key"),
    )


def local_ca_material(
    ca_dir: Path, days: int = DEFAULT_CERT_DAYS, force: bool = False
) -> tuple[Path, Path]:
    ca_dir.mkdir(parents=True, exist_ok=True)

    ca_key = ca_dir / "ca.key"
    ca_pem = ca_dir / "ca.pem"
    ca_srl = ca_dir / "ca.srl"

    effective_force = force and str(ca_dir) not in FORCED_CA_ONCE
    if effective_force:
        FORCED_CA_ONCE.add(str(ca_dir))
        rm(ca_key)
        rm(ca_pem)
        rm(ca_srl)

    with tempfile.TemporaryDirectory(prefix=".ca-", dir=LOCAL_TEMP_ROOT) as td:
        tmp = Path(td)
        plain_ca_key = tmp / "ca.key"

        if not ca_key.exists():
            print(f"Creating {ca_key}")
            openvpn_pki.generate_ed25519_private_key(plain_ca_key)
            write_material_file(ca_key, read(plain_ca_key))
        else:
            plain_ca_key.write_text(material_plaintext(read(ca_key)), encoding="utf-8")
            plain_ca_key.chmod(0o600)
            if "OWMB_ENC_MATERIAL_V1" not in read(ca_key):
                write_material_file(ca_key, read(plain_ca_key))

        if not ca_pem.exists():
            print(f"Creating {ca_pem}")
            openvpn_pki.self_sign_ca(
                plain_ca_key,
                ca_pem,
                cn=DEFAULT_CA_CN,
                days=days,
            )

    return ca_key, ca_pem


def generate_ed25519_cert_signed_by_ca(
    ca_key: Path,
    ca_pem: Path,
    cn: str,
    days: int = DEFAULT_CERT_DAYS,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix=".ca-sign-", dir=LOCAL_TEMP_ROOT) as td:
        tmp = Path(td)
        plain_ca_key = material_file_for_tool(ca_key, tmp, "ca.key")
        return openvpn_pki.issue_ed25519_cert(
            plain_ca_key,
            ca_pem,
            cn=cn,
            days=days,
        )


def build_openvpn_access_interface_block(iface_name: str) -> str:
    return (
        render_uci_block(
            "interface",
            iface_name,
            options={
                "proto": "none",
                "device": iface_name,
            },
        )
        + "\n"
    )


def build_openvpn_server_conf(
    *,
    group: object,
    dns_ip: str,
    ca_pem_text: str,
    cert_pem_text: str,
    key_pem_text: str,
) -> str:
    server_net = f"{getattr(group, 'subnet')}.0"

    return (
        f"port {getattr(group, 'port')}\n"
        f"proto {OPENVPN_SERVER_PROTO}\n\n"
        f"dev {getattr(group, 'name')}\n"
        f"dev-type {OPENVPN_DEV_TYPE}\n\n"
        "dh none\n\n"
        f"topology {OPENVPN_TOPOLOGY}\n"
        f"server {server_net} 255.255.255.0\n\n"
        'push "redirect-gateway def1"\n'
        f'push "dhcp-option DNS {dns_ip}"\n\n'
        f"keepalive {OPENVPN_KEEPALIVE}\n"
        "persist-key\n"
        "persist-tun\n\n"
        f"data-ciphers {OPENVPN_DATA_CIPHERS}\n\n"
        f"user {OPENVPN_USER}\n"
        f"group {OPENVPN_GROUP}\n\n"
        f"verb {OPENVPN_VERB}\n"
        "mute-replay-warnings\n\n"
        "<ca>\n"
        f"{ca_pem_text.rstrip()}\n"
        "</ca>\n\n"
        "<cert>\n"
        f"{cert_pem_text.rstrip()}\n"
        "</cert>\n\n"
        "<key>\n"
        f"{stored_key_material(key_pem_text).rstrip()}\n"
        "</key>\n"
    )


def build_openvpn_client_conf(
    *,
    remote_host: str,
    remote_port: int,
    ca_pem_text: str,
    cert_pem_text: str,
    key_pem_text: str,
) -> str:
    return (
        "client\n"
        f"dev {OPENVPN_DEV_TYPE}\n"
        f"proto {OPENVPN_CLIENT_PROTO}\n\n"
        f"remote {remote_host} {remote_port}\n\n"
        f"data-ciphers {OPENVPN_DATA_CIPHERS}\n\n"
        "resolv-retry infinite\n"
        "nobind\n"
        "persist-key\n"
        "persist-tun\n\n"
        f"verb {OPENVPN_VERB}\n"
        "mute-replay-warnings\n\n"
        "<ca>\n"
        f"{ca_pem_text.rstrip()}\n"
        "</ca>\n\n"
        "<cert>\n"
        f"{cert_pem_text.rstrip()}\n"
        "</cert>\n\n"
        "<key>\n"
        f"{stored_key_material(key_pem_text).rstrip()}\n"
        "</key>\n"
    )


def build_openvpn_uci_block(iface_name: str) -> str:
    return render_uci_block(
        PROTOCOL_OPENVPN,
        iface_name,
        options={
            "enabled": "1",
            "config": f"/etc/openvpn/{iface_name}/server.ovpn",
            "cd": f"/etc/openvpn/{iface_name}",
        },
    )


def render_openvpn_uci_text(
    groups: list[object], extra_blocks: list[str] | None = None
) -> str:
    blocks = [build_openvpn_uci_block(getattr(g, "name")) for g in groups]
    blocks.extend(extra_blocks or [])
    body = "\n\n".join(block.strip() for block in blocks if block.strip()).rstrip()
    return f"package openvpn\n\n{body}\n" if body else ""


def reconcile_router_openvpn_layout(
    cfg: object, router_name: str, iface_name: str
) -> None:
    iface_dir = router_openvpn_iface_dir(cfg, router_name, iface_name)
    iface_dir.mkdir(parents=True, exist_ok=True)
    (iface_dir / "ca").mkdir(parents=True, exist_ok=True)
    (iface_dir / "clients").mkdir(parents=True, exist_ok=True)


def reconcile_router_openvpn_dirs(
    cfg: object,
    router_name: str,
    keep_iface_names: set[str],
) -> None:
    root = router_openvpn_root(cfg, router_name)
    if not keep_iface_names:
        rm(root)
        return

    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir() and child.name not in keep_iface_names:
            rm(child)


def ensure_openvpn_server_conf(
    cfg: object,
    router_name: str,
    group: object,
    *,
    dns_ip: str,
    force: bool,
) -> None:
    router_openvpn_iface_dir(cfg, router_name, getattr(group, "name")).mkdir(
        parents=True, exist_ok=True
    )

    ca_dir = router_openvpn_ca_dir(cfg, router_name, getattr(group, "name"))
    ca_key, ca_pem = local_ca_material(ca_dir=ca_dir, force=force)

    server_conf = router_openvpn_server_conf_path(
        cfg, router_name, getattr(group, "name")
    )
    existing_text = read(server_conf) if server_conf.exists() else ""
    _ca, existing_cert, existing_key = openvpn_inline_material(existing_text)

    if force or not existing_cert or not existing_key:
        server_key_text, server_cert_text = generate_ed25519_cert_signed_by_ca(
            ca_key=ca_key,
            ca_pem=ca_pem,
            cn=openvpn_server_cn(router_name, getattr(group, "name")),
        )
    else:
        server_cert_text = existing_cert
        server_key_text = existing_key

    write(
        server_conf,
        build_openvpn_server_conf(
            group=group,
            dns_ip=dns_ip,
            ca_pem_text=read(ca_pem),
            cert_pem_text=server_cert_text,
            key_pem_text=server_key_text,
        ),
    )


def ensure_openvpn_client_material(
    cfg: object,
    router_name: str,
    iface_name: str,
    user_name: str,
    client_index_1based: int,
    *,
    force: bool,
) -> tuple[str, str]:
    clients_dir = router_openvpn_clients_dir(cfg, router_name, iface_name)
    clients_dir.mkdir(parents=True, exist_ok=True)

    ovpn_path = clients_dir / f"{user_name}.ovpn"
    if ovpn_path.exists() and not force:
        existing = read(ovpn_path)
        _ca, existing_cert, existing_key = openvpn_inline_material(existing)
        if existing_cert and existing_key:
            return existing_key, existing_cert

    ca_dir = router_openvpn_ca_dir(cfg, router_name, iface_name)
    ca_key, ca_pem = local_ca_material(ca_dir=ca_dir, force=force)

    return generate_ed25519_cert_signed_by_ca(
        ca_key=ca_key,
        ca_pem=ca_pem,
        cn=openvpn_client_cn(client_index_1based),
    )


def verify_cert(ca_pem: Path, cert_pem: Path) -> None:
    openvpn_pki.verify_cert(ca_pem, cert_pem)


def cert_subject_cn(cert_pem: Path) -> str:
    return openvpn_pki.cert_subject_cn(cert_pem)


def pubkey_from_cert(cert_pem: Path) -> str:
    return openvpn_pki.pubkey_from_cert(cert_pem)


def pubkey_from_private_key(key_pem: Path) -> str:
    with tempfile.TemporaryDirectory(
        prefix=".validate-key-", dir=LOCAL_TEMP_ROOT
    ) as td:
        tmp_key = Path(td) / "key.pem"
        tmp_key.write_text(material_plaintext(read(key_pem)), encoding="utf-8")
        tmp_key.chmod(0o600)
        return openvpn_pki.pubkey_from_private_key(tmp_key)


def verify_key_matches_cert(key_pem: Path, cert_pem: Path) -> None:
    k = pubkey_from_private_key(key_pem)
    c = pubkey_from_cert(cert_pem)
    if k != c:
        die(f"private key does not match certificate: key={key_pem} cert={cert_pem}")


def check_cert_cn(
    label: str, cert_pem: Path, expected_cn: str, *, log: object | None = None
) -> None:
    actual = cert_subject_cn(cert_pem)
    if log is not None:
        log(f"[CERT] {label}: CN={actual} expected={expected_cn}")  # type: ignore[operator]
    if actual != expected_cn:
        die(f"CN mismatch for {label}: expected {expected_cn}, got {actual}")


def validate_openvpn_inline_material(
    *,
    label: str,
    ca_pem_text: str,
    cert_pem_text: str,
    key_pem_text: str,
    expected_cn: str,
    log: object | None = None,
) -> None:
    with tempfile.TemporaryDirectory(
        prefix=".validate-cert-",
        dir=LOCAL_TEMP_ROOT,
    ) as td:
        tmp = Path(td)
        ca_pem = tmp / "ca.pem"
        cert_pem = tmp / "cert.pem"
        key_pem = tmp / "key.pem"

        ca_pem.write_text(ca_pem_text, encoding="utf-8")
        cert_pem.write_text(cert_pem_text, encoding="utf-8")
        key_pem.write_text(key_pem_text, encoding="utf-8")

        verify_cert(ca_pem, cert_pem)
        verify_key_matches_cert(key_pem, cert_pem)
        check_cert_cn(label, cert_pem, expected_cn, log=log)
        check_cert_cn(f"{label} CA", ca_pem, DEFAULT_CA_CN, log=log)
