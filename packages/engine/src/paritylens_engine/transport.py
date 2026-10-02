"""An HTTP transport that checks every connection against an EgressPolicy.

Checking the URL is not enough. A hostname is only a name; what matters is
the address it resolves to, and an attacker controls that:

  - evil.example can simply have an A record of 169.254.169.254.
  - DNS rebinding: it resolves to a public address when checked and to an
    internal one a moment later when the connection is made.

So resolving, checking, and connecting happen in one place, on one answer.
The name is resolved once, every address in the answer is checked, and the
socket is opened to one of those checked addresses, never to the name.
TLS still verifies the certificate against the original hostname.
"""

import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import anyio
import httpcore2
import httpx2

from paritylens_engine.egress import EgressDeniedError, EgressPolicy, IPAddress, parse_address

type Resolver = Callable[[str, int], Awaitable[list[IPAddress]]]


async def system_resolver(host: str, port: int) -> list[IPAddress]:
    """Resolve a hostname with the operating system's resolver."""
    try:
        results = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise httpcore2.ConnectError(f"could not resolve {host!r}") from exc
    addresses: list[IPAddress] = []
    for *_, sockaddr in results:
        address = parse_address(str(sockaddr[0]).split("%", 1)[0])  # drop any IPv6 zone
        if address is not None and address not in addresses:
            addresses.append(address)
    return addresses


class GuardedBackend(httpcore2.AsyncNetworkBackend):
    """Opens TCP connections only to addresses the policy accepts."""

    def __init__(
        self,
        policy: EgressPolicy,
        *,
        resolver: Resolver = system_resolver,
        inner: httpcore2.AsyncNetworkBackend | None = None,
    ) -> None:
        self._policy = policy
        self._resolve = resolver
        self._inner = inner or httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        literal = parse_address(host)
        if literal is not None:
            addresses = [literal]
        else:
            with anyio.fail_after(timeout):
                addresses = await self._resolve(host, port)
        if not addresses:
            raise httpcore2.ConnectError(f"{host!r} did not resolve to any address")

        # Every address in the answer must pass, not just the one used.
        # A name that resolves to both a public and an internal address is
        # refused outright rather than connected to on a good day.
        for address in addresses:
            self._policy.check_address(address)

        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    str(address),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore2.ConnectError(f"could not connect to {host!r}")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        raise EgressDeniedError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class GuardedTransport(httpx2.AsyncHTTPTransport):
    """httpx2's standard transport with GuardedBackend doing the connecting."""

    def __init__(
        self,
        policy: EgressPolicy,
        *,
        resolver: Resolver = system_resolver,
        max_connections: int = 20,
    ) -> None:
        # trust_env=False: ignore proxy and certificate settings from the
        # environment. A proxy would connect on our behalf, past the checks.
        super().__init__(trust_env=False)
        # httpx2 offers no parameter for the network backend, so the pool it
        # built is replaced by an equivalent one that has ours. The tests in
        # test_transport.py connect through this class for real and fail if
        # a library update ever makes this assignment stop taking effect.
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=httpx2.create_ssl_context(trust_env=False),
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=5.0,
            network_backend=GuardedBackend(policy, resolver=resolver),
        )
