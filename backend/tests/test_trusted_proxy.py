import asyncio

import pytest

from app.core.config import parse_trusted_proxy_ips
from app.core.trusted_proxy import TrustedProxyHeadersMiddleware
from app.serve import get_uvicorn_options


@pytest.mark.parametrize("raw", ["*", "0.0.0.0/0", "not-an-ip"])
def test_trusted_proxy_configuration_rejects_wildcards_and_invalid_values(raw):
    with pytest.raises(ValueError, match="TRUSTED_PROXY_IPS"):
        parse_trusted_proxy_ips(raw)


def test_trusted_proxy_configuration_normalizes_only_explicit_networks():
    assert parse_trusted_proxy_ips(" 10.1.2.3, 192.0.2.0/24 ") == [
        "10.1.2.3/32",
        "192.0.2.0/24",
    ]
    assert parse_trusted_proxy_ips("") == []


def test_supported_uvicorn_launcher_disables_implicit_proxy_rewriting():
    assert get_uvicorn_options()["proxy_headers"] is False


def _forwarded_client(peer: str, forwarded_for: str | None, trusted: list[str]) -> str:
    observed = {}

    async def downstream(scope, _receive, _send):
        observed["host"] = scope["client"][0]

    async def run():
        headers = []
        if forwarded_for is not None:
            headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
        scope = {"type": "http", "client": (peer, 12345), "headers": headers}
        await TrustedProxyHeadersMiddleware(downstream, trusted)(scope, None, None)

    asyncio.run(run())
    return observed["host"]


def test_untrusted_peer_cannot_spoof_client_ip_with_forwarding_header():
    assert _forwarded_client(
        "198.51.100.20", "203.0.113.99", ["10.0.0.0/8"]
    ) == "198.51.100.20"


def test_configured_proxy_may_forward_client_ip_and_trusted_chain():
    assert _forwarded_client(
        "10.0.0.12", "198.51.100.20", ["10.0.0.0/8"]
    ) == "198.51.100.20"
    assert _forwarded_client(
        "10.0.0.12",
        "198.51.100.20, 10.0.0.11",
        ["10.0.0.0/8"],
    ) == "198.51.100.20"


def test_malformed_forwarded_chain_is_ignored():
    assert _forwarded_client(
        "10.0.0.12", "198.51.100.20, attacker.invalid", ["10.0.0.0/8"]
    ) == "10.0.0.12"


def test_no_configured_proxies_means_forwarding_headers_are_ignored():
    assert _forwarded_client("127.0.0.1", "203.0.113.99", []) == "127.0.0.1"
