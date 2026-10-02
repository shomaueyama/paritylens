"""The guarded transport: the address that is checked is the address that is connected to."""

import asyncio
from collections.abc import Iterable
from ipaddress import ip_address
from typing import Any

import httpcore2
import httpx2
import pytest
from paritylens_engine.egress import EgressDeniedError, EgressMode, EgressPolicy, IPAddress
from paritylens_engine.transport import GuardedBackend, GuardedTransport, system_resolver

from conftest import Serve

PUBLIC_ONLY = EgressPolicy(mode=EgressMode.PUBLIC_ONLY)
PERMISSIVE = EgressPolicy(mode=EgressMode.PERMISSIVE)


class RecordingBackend(httpcore2.AsyncNetworkBackend):
    """Stands in for the real network and records where connections were opened."""

    def __init__(self, unreachable: Iterable[str] = ()) -> None:
        self.connected_to: list[tuple[str, int]] = []
        self._unreachable = set(unreachable)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        self.connected_to.append((host, port))
        if host in self._unreachable:
            raise httpcore2.ConnectError("unreachable")
        return httpcore2.AsyncMockStream([])


class FakeDns:
    """Answers each lookup with the next prepared answer, repeating the last one."""

    def __init__(self, *answers: list[str]) -> None:
        self._answers = [[ip_address(a) for a in answer] for answer in answers]
        self.lookups: list[str] = []

    async def __call__(self, host: str, port: int) -> list[IPAddress]:
        self.lookups.append(host)
        return self._answers[min(len(self.lookups), len(self._answers)) - 1]


def connect(
    policy: EgressPolicy, dns: FakeDns, inner: RecordingBackend, host: str = "api.example.com"
) -> None:
    backend = GuardedBackend(policy, resolver=dns, inner=inner)
    asyncio.run(backend.connect_tcp(host, 443, timeout=5))


def test_the_connection_goes_to_the_resolved_address_not_the_name() -> None:
    inner = RecordingBackend()

    connect(PUBLIC_ONLY, FakeDns(["93.184.216.34"]), inner)

    assert inner.connected_to == [("93.184.216.34", 443)]


def test_a_name_that_resolves_to_an_internal_address_is_refused() -> None:
    inner = RecordingBackend()

    with pytest.raises(EgressDeniedError):
        connect(PUBLIC_ONLY, FakeDns(["10.0.0.5"]), inner)

    assert inner.connected_to == []


def test_a_name_that_resolves_to_the_metadata_service_is_refused_in_every_mode() -> None:
    for policy in (PUBLIC_ONLY, PERMISSIVE):
        inner = RecordingBackend()

        with pytest.raises(EgressDeniedError):
            connect(policy, FakeDns(["169.254.169.254"]), inner)

        assert inner.connected_to == []


def test_one_internal_address_among_public_ones_refuses_the_whole_name() -> None:
    """Otherwise the attacker just retries until the internal one is picked."""
    inner = RecordingBackend()

    with pytest.raises(EgressDeniedError):
        connect(PUBLIC_ONLY, FakeDns(["93.184.216.34", "127.0.0.1"]), inner)

    assert inner.connected_to == []


def test_dns_rebinding_gets_no_second_lookup_to_exploit() -> None:
    """The name is resolved once; the answer that was checked is the one used.

    A rebinding attack answers the first lookup with a public address and
    the next with an internal one. That only works if the client checks
    one lookup and connects with another.
    """
    dns = FakeDns(["93.184.216.34"], ["127.0.0.1"])
    inner = RecordingBackend()

    connect(PUBLIC_ONLY, dns, inner)

    assert dns.lookups == ["api.example.com"]
    assert inner.connected_to == [("93.184.216.34", 443)]


def test_an_ip_literal_is_checked_without_a_lookup() -> None:
    dns = FakeDns(["93.184.216.34"])
    inner = RecordingBackend()

    with pytest.raises(EgressDeniedError):
        connect(PUBLIC_ONLY, dns, inner, host="127.0.0.1")
    connect(PUBLIC_ONLY, dns, inner, host="93.184.216.34")

    assert dns.lookups == []
    assert inner.connected_to == [("93.184.216.34", 443)]


def test_the_next_address_is_tried_when_one_does_not_answer() -> None:
    inner = RecordingBackend(unreachable=["2606:4700:4700::1111"])

    connect(PUBLIC_ONLY, FakeDns(["2606:4700:4700::1111", "1.1.1.1"]), inner)

    assert inner.connected_to == [("2606:4700:4700::1111", 443), ("1.1.1.1", 443)]


def test_a_name_with_no_addresses_is_a_connection_error() -> None:
    with pytest.raises(httpcore2.ConnectError):
        connect(PUBLIC_ONLY, FakeDns([]), RecordingBackend())


def test_unix_sockets_are_refused() -> None:
    backend = GuardedBackend(PERMISSIVE)

    with pytest.raises(EgressDeniedError):
        asyncio.run(backend.connect_unix_socket("/var/run/docker.sock"))


def test_the_system_resolver_returns_addresses() -> None:
    addresses = asyncio.run(system_resolver("localhost", 80))

    assert addresses
    assert all(address.is_loopback for address in addresses)


# --- through httpx2, against a real local server -------------------------------


async def echo_host(scope: Any, receive: Any, send: Any) -> None:
    """A tiny ASGI app that answers with the Host header it was sent."""
    if scope["type"] != "http":
        return
    host = dict(scope["headers"]).get(b"host", b"")
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": host})


def get(url: str, transport: GuardedTransport) -> httpx2.Response:
    async def request() -> httpx2.Response:
        async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
            return await client.get(url)

    return asyncio.run(request())


def test_permissive_reaches_a_local_server(serve: Serve) -> None:
    with serve(echo_host) as base_url:
        response = get(base_url, GuardedTransport(PERMISSIVE))

    assert response.status_code == 200


def test_public_only_refuses_a_local_server_by_address_and_by_name(serve: Serve) -> None:
    """This fails if GuardedTransport ever stops installing its backend."""
    with serve(echo_host) as base_url:
        port = base_url.rsplit(":", 1)[1]
        for url in (base_url, f"http://localhost:{port}"):
            with pytest.raises(EgressDeniedError):
                get(url, GuardedTransport(PUBLIC_ONLY))


def test_the_host_header_keeps_the_name_while_the_socket_uses_the_address(serve: Serve) -> None:
    """Connecting by IP must not change what the server is asked for."""
    dns = FakeDns(["127.0.0.1"])
    with serve(echo_host) as base_url:
        port = base_url.rsplit(":", 1)[1]
        response = get(f"http://shop.internal:{port}/", GuardedTransport(PERMISSIVE, resolver=dns))

    assert response.text == f"shop.internal:{port}"
    assert dns.lookups == ["shop.internal"]
