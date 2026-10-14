from __future__ import annotations

import pytest

from app.ingestion.errors import InvalidRepositoryUrlError, RepositoryUnavailableError
from app.ingestion.network import Resolver, ensure_public_host


def _resolver(*addresses: str) -> Resolver:
    return lambda host: list(addresses)


def test_public_addresses_pass() -> None:
    ensure_public_host("github.com", _resolver("140.82.112.3", "2606:50c0:8000::153"))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1%en0",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
    ],
)
def test_non_public_addresses_are_rejected(address: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        ensure_public_host("github.com", _resolver("140.82.112.3", address))


def test_resolution_failure_is_unavailable() -> None:
    def failing(host: str) -> list[str]:
        raise OSError("nodename nor servname provided")

    with pytest.raises(RepositoryUnavailableError):
        ensure_public_host("github.com", failing)


def test_empty_resolution_is_unavailable() -> None:
    with pytest.raises(RepositoryUnavailableError):
        ensure_public_host("github.com", _resolver())
