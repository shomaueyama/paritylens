"""Which destinations the engine is allowed to connect to.

ParityLens sends requests to URLs that users supply. Run on a server, that
is a way to make the server reach places the user cannot: a cloud metadata
endpoint, a database on the internal network. EgressPolicy is the single
place that decides whether a destination is acceptable.

It is consulted twice per request: once for the URL as written, and once
for the IP address actually being connected to (see transport.py). The
second check is the one that matters; a harmless-looking hostname can
resolve to anything.
"""

from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

type IPAddress = IPv4Address | IPv6Address


class EgressDeniedError(Exception):
    """The policy does not allow connecting to this destination."""


class EgressMode(StrEnum):
    # Only the hosts listed in allow_hosts. For a public demo deployment.
    ALLOWLIST = "allowlist"
    # Only addresses reachable on the public internet. For a hosted service
    # that accepts URLs from strangers.
    PUBLIC_ONLY = "public_only"
    # Private networks allowed. For the CLI and local development, where
    # the user runs the engine on their own machine against their own APIs.
    PERMISSIVE = "permissive"


# Cloud metadata services and everything else link-local. Reaching these is
# never a legitimate API test, so no mode allows them.
_ALWAYS_DENIED: tuple[IPv4Network | IPv6Network, ...] = (
    IPv4Network("169.254.0.0/16"),  # AWS, GCP, Azure metadata; ECS 169.254.170.2
    IPv4Network("168.63.129.16/32"),  # Azure WireServer
    IPv4Network("100.100.100.200/32"),  # Alibaba Cloud metadata
    IPv4Network("192.0.0.192/32"),  # Oracle Cloud metadata
    IPv6Network("fe80::/10"),
    IPv6Network("fd00:ec2::/32"),  # AWS metadata over IPv6
)

# IPv6 ranges whose last 32 bits are an IPv4 address that the network may
# deliver the packet to.
_EMBEDS_IPV4: tuple[IPv6Network, ...] = (
    IPv6Network("::/96"),  # IPv4-compatible (deprecated, still routed by some stacks)
    IPv6Network("::ffff:0:0:0/96"),  # IPv4-translated (SIIT)
    IPv6Network("64:ff9b::/96"),  # NAT64
    IPv6Network("64:ff9b:1::/48"),  # NAT64, local use
)


class EgressPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: EgressMode
    # ALLOWLIST: hostnames, optionally with a port ("api.example.com:8443").
    allow_hosts: frozenset[str] = frozenset()
    # PUBLIC_ONLY: ports a URL may use.
    allowed_ports: frozenset[int] = frozenset({80, 443})

    def check_url(self, url: str) -> None:
        """Reject a URL that should not be requested at all."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise EgressDeniedError(f"malformed URL: {exc}") from exc

        if parts.scheme not in ("http", "https"):
            raise EgressDeniedError(f"scheme {parts.scheme!r} is not allowed")
        if parts.username is not None or parts.password is not None:
            raise EgressDeniedError("credentials in the URL are not allowed")
        host = parts.hostname
        if not host:
            raise EgressDeniedError("the URL has no host")
        port = port or (443 if parts.scheme == "https" else 80)

        if self.mode is EgressMode.ALLOWLIST:
            if host not in self.allow_hosts and f"{host}:{port}" not in self.allow_hosts:
                raise EgressDeniedError(f"host {host!r} is not on the allowlist")
        elif self.mode is EgressMode.PUBLIC_ONLY and port not in self.allowed_ports:
            raise EgressDeniedError(f"port {port} is not allowed")

    def check_address(self, address: IPAddress) -> None:
        """Reject an IP address that should not be connected to."""
        for candidate in _with_embedded_ipv4(address):
            if any(candidate in network for network in _ALWAYS_DENIED):
                raise EgressDeniedError(f"{address} is a link-local or metadata address")
            if self.mode is EgressMode.PUBLIC_ONLY and not _is_public(candidate):
                raise EgressDeniedError(f"{address} is not a public address")


def _is_public(address: IPAddress) -> bool:
    """Whether an address is an ordinary host on the public internet.

    is_global is False for loopback, private (RFC 1918), carrier NAT,
    unique-local IPv6, documentation and reserved ranges. It is True for
    some multicast addresses, which are globally routable but are not a
    server anyone should be sending API requests to, so that is checked
    separately.
    """
    if isinstance(address, IPv6Address) and address.is_site_local:
        return False  # fec0::/10, deprecated but private in intent
    return address.is_global and not address.is_multicast


def _with_embedded_ipv4(address: IPAddress) -> list[IPAddress]:
    """The address, plus any IPv4 address it wraps.

    ::ffff:10.0.0.1 is 10.0.0.1 wearing an IPv6 costume, and the operating
    system will connect to 10.0.0.1. Each such form is unwrapped so the
    inner address is judged too.
    """
    candidates: list[IPAddress] = [address]
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped is not None:
            candidates.append(address.ipv4_mapped)
        if address.sixtofour is not None:
            candidates.append(address.sixtofour)
        if address.teredo is not None:
            candidates.extend(address.teredo)
        if any(address in network for network in _EMBEDS_IPV4):
            candidates.append(IPv4Address(int(address) & 0xFFFFFFFF))
    return candidates


def parse_address(text: str) -> IPAddress | None:
    """Parse text as an IP address, or return None if it is a hostname."""
    try:
        return ip_address(text.strip("[]"))
    except ValueError:
        return None
