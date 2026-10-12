"""Defense-in-depth SSRF check: allowed hosts must resolve to public addresses.

The host allowlist is the primary control. This check additionally refuses to
clone when DNS points an allowed name at loopback, private, link-local (cloud
metadata) or otherwise non-global addresses. git resolves the name again when
it connects, so this does not defeat a deliberate DNS-rebinding attacker; it
does catch misconfigured allowlists and poisoned resolvers.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

from app.ingestion.errors import InvalidRepositoryUrlError, RepositoryUnavailableError

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def ensure_public_host(host: str, resolver: Resolver = system_resolver) -> None:
    try:
        addresses = resolver(host)
    except OSError as exc:
        raise RepositoryUnavailableError(f"Could not resolve host {host}") from exc
    if not addresses:
        raise RepositoryUnavailableError(f"Could not resolve host {host}")

    for raw in addresses:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global:
            raise InvalidRepositoryUrlError(f"Host {host} resolves to a non-public address")
