#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re
import tempfile
from pathlib import Path

try:
    from .process import die, need, run_checked
    from .default import LOCAL_TEMP_ROOT
except ImportError:
    from process import die, need, run_checked
    from default import LOCAL_TEMP_ROOT


def _run(args: list[str]) -> None:
    need("openssl")
    run_checked(args, quiet=True)


def _out(args: list[str]) -> str:
    need("openssl")
    return run_checked(args, quiet=True)


def req_subject(cn: str) -> str:
    return f"/CN={cn}"


def generate_ed25519_private_key(path: Path) -> None:
    _run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(path)])


def self_sign_ca(ca_key: Path, ca_pem: Path, *, cn: str, days: int) -> None:
    _run(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-key",
            str(ca_key),
            "-out",
            str(ca_pem),
            "-days",
            str(days),
            "-subj",
            req_subject(cn),
        ]
    )


def issue_ed25519_cert(
    ca_key: Path, ca_pem: Path, *, cn: str, days: int
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix=".cert-", dir=LOCAL_TEMP_ROOT) as td:
        tmp = Path(td)
        key = tmp / "cert.key"
        csr = tmp / "cert.csr"
        crt = tmp / "cert.pem"
        srl = tmp / "ca.srl"
        _run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)])
        _run(
            [
                "openssl",
                "req",
                "-new",
                "-key",
                str(key),
                "-out",
                str(csr),
                "-subj",
                req_subject(cn),
            ]
        )
        _run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca_pem),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-CAserial",
                str(srl),
                "-out",
                str(crt),
                "-days",
                str(days),
            ]
        )
        return key.read_text(encoding="utf-8"), crt.read_text(encoding="utf-8")


def verify_cert(ca_pem: Path, cert_pem: Path) -> None:
    _run(["openssl", "verify", "-CAfile", str(ca_pem), str(cert_pem)])


def cert_subject_cn(cert_pem: Path) -> str:
    subj = _out(
        [
            "openssl",
            "x509",
            "-in",
            str(cert_pem),
            "-noout",
            "-subject",
            "-nameopt",
            "RFC2253",
        ]
    )
    m = re.search(r"CN=([^,]+)", subj)
    if not m:
        die(f"certificate has no CN: {cert_pem}")
    return m.group(1).strip()


def pubkey_from_cert(cert_pem: Path) -> str:
    return _out(["openssl", "x509", "-in", str(cert_pem), "-pubkey", "-noout"])


def pubkey_from_private_key(key_pem: Path) -> str:
    return _out(["openssl", "pkey", "-in", str(key_pem), "-pubout"])
