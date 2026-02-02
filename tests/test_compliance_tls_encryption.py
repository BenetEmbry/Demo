from __future__ import annotations

import datetime as dt
import json
import ssl
import tempfile
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from urllib3.exceptions import InsecureRequestWarning
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from regression.sut import load_sut_adapter


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        if path == "/metrics":
            payload = {"device.model": "eyeSight-DEMO"}
            b = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return

        self.send_response(404)
        self.end_headers()


def _make_self_signed_cert(hostname: str) -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Demo"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )

    now_utc = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now_utc - dt.timedelta(days=1))
        .not_valid_after(now_utc + dt.timedelta(days=7))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname), x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


@pytest.fixture()
def https_base_url() -> str:
    hostname = "127.0.0.1"
    cert_pem, key_pem = _make_self_signed_cert(hostname)

    server = ThreadingHTTPServer((hostname, 0), _Handler)
    host, port = server.server_address

    # Write cert/key to temp files for SSLContext
    with tempfile.NamedTemporaryFile(delete=False) as cert_f, tempfile.NamedTemporaryFile(delete=False) as key_f:
        cert_f.write(cert_pem)
        cert_f.flush()
        key_f.write(key_pem)
        key_f.flush()

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_f.name, keyfile=key_f.name)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"https://{host}:{port}"
    finally:
        server.shutdown()


def test_encryption_verification_tls_required(monkeypatch: pytest.MonkeyPatch, https_base_url: str) -> None:
    # With verification enabled, self-signed cert must fail.
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", https_base_url)
    monkeypatch.setenv("SUT_METRICS_ENDPOINT", "/metrics")
    monkeypatch.setenv("SUT_VERIFY_TLS", "true")

    sut = load_sut_adapter()
    with pytest.raises(requests.exceptions.SSLError):
        sut.get_metric("device.model")


def test_encryption_verification_tls_disabled_allows_self_signed(monkeypatch: pytest.MonkeyPatch, https_base_url: str) -> None:
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", https_base_url)
    monkeypatch.setenv("SUT_METRICS_ENDPOINT", "/metrics")
    monkeypatch.setenv("SUT_VERIFY_TLS", "false")

    sut = load_sut_adapter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureRequestWarning)
        assert sut.get_metric("device.model") == "eyeSight-DEMO"
