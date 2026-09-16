from __future__ import annotations

import ipaddress
from urllib.parse import SplitResult, urlsplit, urlunsplit


class InvalidSourceUrl(ValueError):
    """Raised when a source URL is not a supported public HTTP URL."""


def normalize_url(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise InvalidSourceUrl("source URL must use http or https")
    if not parsed.hostname:
        raise InvalidSourceUrl("source URL must include a hostname")
    if parsed.username or parsed.password:
        raise InvalidSourceUrl("source URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as error:
        raise InvalidSourceUrl("source URL has an invalid port") from error

    hostname = parsed.hostname.lower()
    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    if port is not None and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc = f"{netloc}:{port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def validate_fetch_host(value: str, allow_private_hosts: bool = False) -> str:
    normalized = normalize_url(value)
    hostname = urlsplit(normalized).hostname or ""
    if allow_private_hosts:
        return normalized
    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"}:
        raise InvalidSourceUrl("private hosts are disabled")
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return normalized
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise InvalidSourceUrl("private hosts are disabled")
    return normalized


def default_source_name(value: str) -> str:
    parsed: SplitResult = urlsplit(value)
    return parsed.hostname or value

