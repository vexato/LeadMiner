"""Outbound HTTP transport for public, untrusted URLs."""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

import aiohttp
from aiohttp.resolver import ThreadedResolver
from yarl import URL


class FetchError(Exception):
    """A request that could not safely produce a usable response."""


def _public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.sixtofour or ip.teredo or ip in ipaddress.ip_network("64:ff9b::/96"):
            return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def public_url(raw: str) -> URL:
    """Validate structure and literal IPs before the connector can bypass DNS."""
    if re.search(r"[\x00-\x20\x7f\\]", raw) or len(raw) > 4096:
        raise FetchError("invalid_url")
    try:
        parsed = urlsplit(raw)
        url = URL(raw)
        host = url.raw_host or ""
        expected_port = {"http": 80, "https": 443}.get(url.scheme)
        if (not expected_port or parsed.scheme.lower() != url.scheme or not parsed.netloc
                or not host or url.user is not None or url.password is not None
                or url.port != expected_port or "%" in parsed.netloc):
            raise FetchError("invalid_url")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.rstrip(".").split(".")
            if (len(labels) < 2 or not labels[-1][0:1].isalpha()
                    or any(not re.fullmatch(r"[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?", label, re.I)
                           for label in labels)
                    or labels[-1] in {"local", "internal", "localhost", "home", "lan"}):
                raise FetchError("invalid_host")
        else:
            if not _public_ip(host):
                raise FetchError("non_public_address")
        return url.with_fragment(None)
    except ValueError as exc:
        raise FetchError("invalid_url") from exc


class PublicResolver(ThreadedResolver):
    async def resolve(self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET):
        answers = await super().resolve(host, port, family)
        if not answers or any(not _public_ip(answer["host"]) for answer in answers):
            raise OSError("non_public_dns_answer")
        return answers


def public_session(timeout: float, limit: int = 20, per_host: int = 2) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(resolver=PublicResolver(), limit=limit, limit_per_host=per_host),
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=aiohttp.ClientTimeout(total=timeout),
        auto_decompress=False,
        headers={"User-Agent": "LeadMiner/2.0", "Accept-Encoding": "identity"},
    )


async def bounded_body(response: aiohttp.ClientResponse, maximum: int) -> bytes:
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise FetchError("unsupported_content_encoding")
    if response.content_length is not None and response.content_length > maximum:
        raise FetchError("body_too_large")
    body = bytearray()
    async for block in response.content.iter_chunked(16_384):
        body.extend(block)
        if len(body) > maximum:
            raise FetchError("body_too_large")
    return bytes(body)
