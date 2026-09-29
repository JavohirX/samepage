"""Standard Webhooks header scheme and SSRF guard (S12).

Pure domain logic: Standard Webhooks signature formatting and URL safety verification.
Free of Django and web layers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import socket
import time
from urllib.parse import urlparse


def generate_webhook_signature(
    secret: str | bytes,
    msg_id: str,
    timestamp: int,
    payload_body: str | bytes,
) -> str:
    """Generate signature header adhering to standardwebhooks.com specification.

    Signed payload: f"{msg_id}.{timestamp}.{body}"
    Returns: "v1," + base64(hmac_sha256(secret, signed_payload))
    """
    if isinstance(secret, str):
        # Support whsec_ prefix (base64) or plain string
        if secret.startswith("whsec_"):
            sec_part = secret[6:]
            try:
                pad = len(sec_part) % 4
                padded = sec_part + ("=" * (4 - pad) if pad else "")
                raw_secret = base64.b64decode(padded)
            except Exception:
                raw_secret = secret.encode("utf-8")
        else:
            raw_secret = secret.encode("utf-8")
    else:
        raw_secret = secret

    if isinstance(payload_body, str):
        payload_bytes = payload_body.encode("utf-8")
    else:
        payload_bytes = payload_body

    to_sign = f"{msg_id}.{timestamp}.".encode("utf-8") + payload_bytes
    sig = hmac.new(raw_secret, to_sign, hashlib.sha256).digest()
    sig_b64 = base64.b64encode(sig).decode("ascii")
    return f"v1,{sig_b64}"


def verify_webhook_signature(
    secret: str | bytes,
    msg_id: str,
    timestamp: int,
    payload_body: str | bytes,
    signature_header: str,
    tolerance_seconds: int = 300,
    current_time: int | None = None,
) -> bool:
    """Verify Standard Webhook signature."""
    now = current_time if current_time is not None else int(time.time())
    if abs(now - timestamp) > tolerance_seconds:
        return False

    expected_sig = generate_webhook_signature(secret, msg_id, timestamp, payload_body)
    sigs = [s.strip() for s in signature_header.split(" ") if s.strip()]
    for s in sigs:
        if hmac.compare_digest(s, expected_sig):
            return True
    return False


def is_ssrf_safe_url(url: str, allow_local: bool = False) -> tuple[bool, str]:
    """Validate target webhook URL against SSRF attacks.

    Refuses non-http/https schemes, loopback addresses, link-local, private networks,
    unless allow_local is True.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL structure."

    if parsed.scheme not in ("http", "https"):
        return False, f"Unsupported scheme: {parsed.scheme}. Only http and https allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL."

    # If local webhooks are allowed (e.g. in test suite)
    if allow_local:
        return True, ""

    # Check for direct IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, f"Host IP address {ip} is in a reserved/private network."
        return True, ""
    except ValueError:
        # It's a hostname (e.g. example.com or localhost)
        if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, f"Blocked target: {hostname} is a loopback address."

    return True, ""
