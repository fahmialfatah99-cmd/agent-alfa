"""Guard URL untuk tool fetch/download — mitigasi SSRF.

Setiap fetch URL yang URL-nya datang dari LLM/user WAJIB melewati
:func:`assert_public_http_url`. Aturan:

1. Skema hanya ``http``/``https`` (blokir ``file:``, ``gopher:``, dll.).
2. Host/IP literal loopback (127.x/::1), private (RFC1918/ULA), link-local
   (169.254.x — termasuk cloud metadata 169.254.169.254), multicast,
   reserved, dan unspecified ditolak.
3. Host yang direseksi DNS menjadi alamat forbidden pun ditolak.
4. Bypass eksplisit operator: ``ALFA_ALLOW_PRIVATE_FETCH=true``
   (untuk penggunaan LAN internal yang disengaja).
"""

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

logger = logging.getLogger("NetGuard")

PUBLIC_SCHEMES = ("http", "https")


class UnsafeUrlError(ValueError):
    """URL ditolak oleh SSRF guard (detail alasan ada di pesan)."""


def _allow_private() -> bool:
    return os.getenv("ALFA_ALLOW_PRIVATE_FETCH", "false").strip().lower() == "true"


def _ip_is_forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_candidates(host: str) -> list[str]:
    """Resolve hostname → daftar string IP (kosong bila DNS gagal)."""
    candidates: list[str] = []
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, UnicodeError):
        return candidates
    for _fam, _typ, _proto, _canon, _sockaddr in infos:
        ip_str = _sockaddr[0]
        if ip_str and ip_str not in candidates:
            candidates.append(ip_str)
    return candidates


def is_public_http_url(url: str) -> tuple[bool, str]:
    """Return (aman?, alasan). Alasan berisi detail host/IP terlarang."""
    try:
        parsed = urlparse(url.strip())
    except (ValueError, AttributeError) as e:
        return False, f"URL tidak dapat di-parse: {e}"

    if parsed.scheme.lower() not in PUBLIC_SCHEMES:
        return False, f"Skema '{parsed.scheme or '(kosong)'}' tidak diizinkan (hanya http/https)"

    host = parsed.hostname
    if not host:
        return False, "URL tanpa hostname tidak diizinkan"

    # Bypass eksplisit operator (untuk fetch LAN internal yang disengaja) —
    # tetap SETELAH validasi skema/hostname dasar, SEBELUM semua cek IP.
    if _allow_private():
        return True, ""

    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost") or lowered == "metadata.google.internal":
        return False, f"Host internal '{host}' ditolak (SSRF)"

    # IP literal
    try:
        ip = ipaddress.ip_address(lowered)
        if _ip_is_forbidden(ip):
            return False, f"IP '{ip}' berada di rentang terlarang (SSRF)"
    except ValueError:
        pass  # hostname, bukan IP literal

    # Cek username:password@ (sering dipakai menyembunyikan target SSRF)
    if parsed.username:
        return False, "URL dengan userinfo (user:pass@) tidak diizinkan"

    # Resolve DNS — tolak bila ada kandidat IP forbidden
    for ip_str in _resolve_candidates(lowered):
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_is_forbidden(ip):
            return False, (
                f"Host '{host}' resolve ke IP terlarang {ip_str} (SSRF)"
            )

    return True, ""


def assert_public_http_url(url: str) -> None:
    """Raise :class:`UnsafeUrlError` bila URL teriorintasi ke jaringan internal."""
    ok, reason = is_public_http_url(url)
    if not ok:
        logger.warning("[SECURITY] SSRF guard menolak URL: %s (%s)", _truncate(url), reason)
        raise UnsafeUrlError(f"[SSRF-GUARD] URL ditolak: {reason}")


def verify_hop_url(url: str) -> str:
    """Verifikasi satu hop redirect; wajib dipanggil per hop fetch manual."""
    assert_public_http_url(url)
    return url


def _truncate(url: str, limit: int = 160) -> str:
    return url if len(url) <= limit else url[:limit] + "…"
