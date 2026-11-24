import ipaddress
import socket
from urllib.parse import urlparse


class SSRFBlockedError(ValueError):
    """Raised when a custom endpoint URL violates anti-SSRF policy."""


def _is_disallowed_ip(ip_str: str, *, allow_local: bool) -> bool:
    addr = ipaddress.ip_address(ip_str.split("%", 1)[0])
    if addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        return True
    if allow_local and addr.is_loopback:
        return False
    return addr.is_private or addr.is_loopback or addr.is_reserved


def validate_custom_base_url(url: str, *, allow_local: bool = False) -> str:
    """Validate scheme, host, and resolved IPs of a custom LLM endpoint against SSRF."""
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)

    if parsed.scheme == "http":
        if not allow_local:
            raise SSRFBlockedError("Custom endpoints must use HTTPS unless local mode is enabled.")
    elif parsed.scheme != "https":
        raise SSRFBlockedError(f"Unsupported URL scheme: {parsed.scheme or 'none'}.")

    host = parsed.hostname
    if not host:
        raise SSRFBlockedError("Custom endpoint URL is missing a valid hostname.")

    # Check literal IP first so numeric metadata addresses fail immediately without DNS.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_disallowed_ip(host, allow_local=allow_local):
            raise SSRFBlockedError(f"Endpoint host '{host}' is blocked by anti-SSRF policy.")
        return cleaned

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"Could not resolve endpoint hostname '{host}'.") from exc

    if not infos:
        raise SSRFBlockedError(f"Hostname '{host}' resolved to no addresses.")

    for info in infos:
        ip_str = str(info[4][0])
        if _is_disallowed_ip(ip_str, allow_local=allow_local):
            raise SSRFBlockedError(
                f"Resolved IP '{ip_str}' for '{host}' is blocked by anti-SSRF policy."
            )

    return cleaned
