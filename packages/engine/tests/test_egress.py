"""EgressPolicy: which URLs and addresses each mode accepts."""

from ipaddress import ip_address

import pytest
from paritylens_engine.egress import EgressDeniedError, EgressMode, EgressPolicy, parse_address

PUBLIC_ONLY = EgressPolicy(mode=EgressMode.PUBLIC_ONLY)
PERMISSIVE = EgressPolicy(mode=EgressMode.PERMISSIVE)
ALLOWLIST = EgressPolicy(
    mode=EgressMode.ALLOWLIST, allow_hosts=frozenset({"legacy-shop-api", "api.example.com:8443"})
)

NOT_PUBLIC = [
    "127.0.0.1",  # loopback
    "127.8.8.8",
    "0.0.0.0",  # noqa: S104 - "this host"
    "10.0.0.1",  # private (RFC 1918)
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "100.64.0.1",  # carrier-grade NAT
    "192.0.2.1",  # documentation
    "198.18.0.1",  # benchmarking
    "224.0.0.1",  # multicast
    "240.0.0.1",  # reserved
    "255.255.255.255",
    "::1",
    "::",
    "fc00::1",  # unique local
    "fd12:3456::1",
    "2001:db8::1",  # documentation
    "ff02::1",  # multicast
    "::ffff:10.0.0.1",  # private IPv4 written as IPv6
    "::ffff:127.0.0.1",
    "2002:a00:1::",  # 6to4 wrapping 10.0.0.1
    "64:ff9b::a00:1",  # NAT64 wrapping 10.0.0.1
    "64:ff9b::7f00:1",  # NAT64 wrapping 127.0.0.1
]

METADATA_AND_LINK_LOCAL = [
    "169.254.169.254",  # AWS, GCP, Azure metadata
    "169.254.170.2",  # ECS task metadata
    "169.254.0.1",
    "fe80::1",
    "fd00:ec2::254",  # AWS metadata over IPv6
    "::ffff:169.254.169.254",
    "64:ff9b::a9fe:a9fe",  # NAT64 wrapping 169.254.169.254
]

PUBLIC = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "64:ff9b::808:808"]


@pytest.mark.parametrize("address", NOT_PUBLIC + METADATA_AND_LINK_LOCAL)
def test_public_only_refuses_everything_that_is_not_the_public_internet(address: str) -> None:
    with pytest.raises(EgressDeniedError):
        PUBLIC_ONLY.check_address(ip_address(address))


@pytest.mark.parametrize("address", PUBLIC)
def test_public_only_accepts_public_addresses(address: str) -> None:
    PUBLIC_ONLY.check_address(ip_address(address))


@pytest.mark.parametrize("policy", [PUBLIC_ONLY, PERMISSIVE, ALLOWLIST])
@pytest.mark.parametrize("address", METADATA_AND_LINK_LOCAL)
def test_no_mode_reaches_metadata_or_link_local_addresses(
    policy: EgressPolicy, address: str
) -> None:
    with pytest.raises(EgressDeniedError):
        policy.check_address(ip_address(address))


@pytest.mark.parametrize("policy", [PERMISSIVE, ALLOWLIST])
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "192.168.1.1", "::1", "8.8.8.8"])
def test_permissive_and_allowlist_accept_private_addresses(
    policy: EgressPolicy, address: str
) -> None:
    """The CLI runs on the user's machine against the user's own network."""
    policy.check_address(ip_address(address))


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://example.com",
        "http://user:pass@example.com/",
        "http://user@example.com/",
        "http:///no-host",
        "http://example.com:99999/",
        "//example.com/",
        "example.com",
    ],
)
@pytest.mark.parametrize("policy", [PUBLIC_ONLY, PERMISSIVE])
def test_urls_no_mode_accepts(policy: EgressPolicy, url: str) -> None:
    with pytest.raises(EgressDeniedError):
        policy.check_url(url)


@pytest.mark.parametrize("url", ["http://example.com/a", "https://example.com:443/a?b=c"])
def test_public_only_accepts_standard_ports(url: str) -> None:
    PUBLIC_ONLY.check_url(url)


@pytest.mark.parametrize("url", ["http://example.com:8080/", "https://example.com:22/"])
def test_public_only_refuses_other_ports(url: str) -> None:
    """Otherwise the service is a port scanner for anything on the internet."""
    with pytest.raises(EgressDeniedError):
        PUBLIC_ONLY.check_url(url)


def test_public_only_ports_can_be_extended() -> None:
    policy = EgressPolicy(mode=EgressMode.PUBLIC_ONLY, allowed_ports=frozenset({80, 443, 8443}))

    policy.check_url("https://example.com:8443/")


def test_permissive_accepts_any_port() -> None:
    PERMISSIVE.check_url("http://localhost:8001/orders")


@pytest.mark.parametrize("url", ["http://legacy-shop-api/orders", "https://api.example.com:8443/x"])
def test_allowlist_accepts_listed_hosts(url: str) -> None:
    ALLOWLIST.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "https://api.example.com/",  # listed with port 8443 only
        "http://legacy-shop-api.evil.test/",
        "http://127.0.0.1/",
    ],
)
def test_allowlist_refuses_everything_else(url: str) -> None:
    with pytest.raises(EgressDeniedError):
        ALLOWLIST.check_url(url)


def test_parse_address() -> None:
    assert parse_address("127.0.0.1") == ip_address("127.0.0.1")
    assert parse_address("[::1]") == ip_address("::1")
    assert parse_address("example.com") is None
    # Not an address to Python, so treated as a name and resolved by DNS,
    # where the address check applies to whatever comes back.
    assert parse_address("0x7f.1") is None
    assert parse_address("2130706433") is None


# --- found in review ----------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "fec0::1",  # site-local
        "::127.0.0.1",  # IPv4-compatible
        "::10.0.0.1",
        "::ffff:0:127.0.0.1",  # IPv4-translated
        "64:ff9b:1::7f00:1",  # local-use NAT64 wrapping 127.0.0.1
    ],
)
def test_public_only_refuses_less_common_ipv6_forms_of_internal_addresses(address: str) -> None:
    with pytest.raises(EgressDeniedError):
        PUBLIC_ONLY.check_address(ip_address(address))


@pytest.mark.parametrize("policy", [PUBLIC_ONLY, PERMISSIVE, ALLOWLIST])
@pytest.mark.parametrize(
    "address",
    [
        "::169.254.169.254",
        "::ffff:0:169.254.169.254",
        "64:ff9b:1::a9fe:a9fe",
        "168.63.129.16",  # Azure WireServer
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",  # Oracle Cloud
    ],
)
def test_no_mode_reaches_metadata_services_in_any_form(policy: EgressPolicy, address: str) -> None:
    with pytest.raises(EgressDeniedError):
        policy.check_address(ip_address(address))
