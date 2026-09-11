"""Bounded HTTPS fetches; source URLs are DNS-pinned to prevent SSRF/rebinding."""

import asyncio
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.errors import PipelineError


class TransientHTTP(Exception):
    pass


def check_status(response):
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientHTTP()
    if not 200 <= response.status_code < 300:
        raise PipelineError("HTTP_REJECTED", f"Remote server returned HTTP {response.status_code}")


async def retry_call(call, attempts=3):
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, TransientHTTP, TimeoutError)),
        reraise=True,
    ):
        with attempt:
            return await call()


async def public_address(url: str):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise PipelineError("UNSAFE_URL", "Only public HTTPS sources on port 443 are allowed")
    addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    ips = {a[4][0] for a in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise PipelineError("UNSAFE_URL", "Private, local and reserved source addresses are forbidden")
    ip = sorted(ips, key=lambda value: (":" in value, value))[0]
    authority = f"[{ip}]" if ":" in ip else ip
    path = parsed.path or "/"
    pinned_url = f"https://{authority}{path}" + (f"?{parsed.query}" if parsed.query else "")
    return pinned_url, parsed.hostname


async def bounded_fetch(
    url: str, *, limit: int, timeout: float, types: tuple[str, ...], destination: Path | None = None
):
    """No environment proxy, credentials or unchecked redirects. Pin TLS SNI and HTTP Host."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            pinned, host = await public_address(url)
            async with client.stream(
                "GET",
                pinned,
                headers={"Host": host, "User-Agent": "VideoTT/1.0", "Accept-Encoding": "identity"},
                extensions={"sni_hostname": host},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                check_status(response)
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in types:
                    raise PipelineError("CONTENT_TYPE", "Remote file has an unsupported content type")
                if int(response.headers.get("content-length", "0")) > limit:
                    raise PipelineError("FILE_TOO_LARGE", "Remote file exceeds configured size limit")
                size = 0
                content = bytearray()
                handle = destination.open("wb") if destination else None
                try:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        size += len(chunk)
                        if size > limit:
                            raise PipelineError("FILE_TOO_LARGE", "Download exceeds configured size limit")
                        if handle:
                            handle.write(chunk)
                        else:
                            content.extend(chunk)
                finally:
                    if handle:
                        handle.close()
                if size == 0:
                    raise PipelineError("EMPTY_DOWNLOAD", "Remote file is empty")
                return bytes(content)
    raise PipelineError("REDIRECT_LIMIT", "Too many remote redirects")
