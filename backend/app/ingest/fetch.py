"""Server-side URL fetch with SSRF protection.

http/https only, default ports or >= 1024 except well-known internal ones; every hop (redirects are followed
manually, at most MAX_REDIRECTS) is resolved first and refused if ANY address is not globally routable
(private, loopback, link-local incl. 169.254.169.254, CGNAT, multicast, reserved, IPv4-mapped IPv6 of those).
The connection then goes to the vetted IP with the original Host header and TLS SNI, so a second DNS answer
(rebinding) cannot redirect it. Body capped at MAX_BYTES, whole fetch capped at TIMEOUT seconds.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from app.ingest.ir import FetchFailed, URLBlocked

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT = 20.0
MAX_REDIRECTS = 5
USER_AGENT = "Mozilla/5.0 (compatible; LexMatchesReader/1.0; +reading-app)"
_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchFailed(f"Could not resolve {host}.") from e
    return list(dict.fromkeys(info[4][0] for info in infos))


def _check_ip(ip_text: str) -> None:
    ip = ipaddress.ip_address(ip_text.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:
        raise URLBlocked("This address is not allowed (private or local network).")


def vet(url: str) -> tuple[str, str, int, str]:
    """-> (scheme, host, port, ip). Raises URLBlocked for anything that is not a public http(s) URL."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise URLBlocked("Only http and https links can be imported.")
    if not parts.hostname or parts.username or parts.password:
        raise URLBlocked("Invalid link.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in (80, 443) and port < 1024:
        raise URLBlocked("This port is not allowed.")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise URLBlocked("This address is not allowed (private or local network).")
    ips = _resolve(host, port)
    if not ips:
        raise FetchFailed(f"Could not resolve {host}.")
    for ip in ips:
        _check_ip(ip)
    return parts.scheme, host, port, ips[0]


def fetch(url: str) -> tuple[bytes, str]:
    """-> (body bytes, final URL)."""
    deadline = time.monotonic() + TIMEOUT
    with httpx.Client(transport=_transport, timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False,
                      trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            scheme, host, port, ip = vet(url)
            parts = urlsplit(url)
            ip_host = f"[{ip}]" if ":" in ip else ip
            target = f"{scheme}://{ip_host}:{port}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")
            headers = {"Host": parts.netloc.split("@")[-1], "User-Agent": USER_AGENT,
                       "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"}
            try:
                with client.stream("GET", target, headers=headers, extensions={"sni_hostname": host}) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        raise FetchFailed(f"The page answered HTTP {r.status_code}.")
                    if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                        raise FetchFailed("The page is too large (over 10 MB).")
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise FetchFailed("The page is too large (over 10 MB).")
                        if time.monotonic() > deadline:
                            raise FetchFailed("The page took too long to download.")
                    return bytes(body), url
            except httpx.HTTPError as e:
                raise FetchFailed(f"Could not download the page ({type(e).__name__}).") from e
    raise FetchFailed("Too many redirects.")
