"""Explicit deployment-owned outbound destinations; resource authors cannot widen them."""

from __future__ import annotations

from urllib.parse import urlsplit


class OutboundDenied(ValueError):
    pass


def check_destination(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise OutboundDenied(
            "Endpoint must be an HTTP(S) URL without embedded credentials or fragments"
        )
    host = parsed.hostname.lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    authority = f"{host}:{port}"
    allowed = {item.lower() for item in allowed_hosts}
    # Host-only entries allow the scheme's default port. Non-default ports must be explicit.
    if authority not in allowed and not (
        host in allowed and port == (443 if parsed.scheme == "https" else 80)
    ):
        raise OutboundDenied(
            f"Outbound destination is not configured: {authority}. Set EIVON_OUTBOUND_HOSTS on the server"
        )
    return url
