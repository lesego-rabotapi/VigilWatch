"""SSRF guard for user-supplied monitoring targets.

The checker Lambda fetches whatever URL a visitor registers, so every URL is
validated on registration and again before each probe (DNS can change between
the two). Only http/https to globally routable addresses is allowed.

Residual risk: a hostname could re-resolve between validation and connect
(classic DNS rebinding). The functions run outside a VPC, where the only
non-public target is the Lambda runtime API on 127.0.0.1, so the impact is low.
"""

import hashlib
import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_PORTS = {"http": 80, "https": 443}


class UnsafeURL(ValueError):
    """The URL must not be probed."""


class UnresolvableHost(UnsafeURL):
    """The hostname has no DNS records (right now)."""


Resolver = Callable[[str], Iterable[str]]


def default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnresolvableHost(f"cannot resolve {host}") from exc
    return sorted({info[4][0] for info in infos})


def normalize(url: str) -> str:
    if not isinstance(url, str):
        raise UnsafeURL("url must be a string")
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeURL(f"url must be 1-{MAX_URL_LENGTH} characters")

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL("only http and https URLs can be monitored")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("credentials in URLs are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeURL("url has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL("invalid port") from exc
    if port == 0:
        raise UnsafeURL("invalid port")

    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def endpoint_id(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:16]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def validate(url: str, resolver: Resolver = default_resolver) -> str:
    """Return the normalized URL, or raise UnsafeURL."""
    normalized = normalize(url)
    host = urlsplit(normalized).hostname

    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = list(resolver(host))

    if not addresses:
        raise UnresolvableHost(f"cannot resolve {host}")
    for address in addresses:
        if not _is_public(address):
            raise UnsafeURL("url resolves to a private or reserved address")
    return normalized
