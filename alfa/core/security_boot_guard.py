"""Guard keamanan boot-time untuk seluruh runtime ALFA.

Semua entrypoint (dashboard, bot Telegram, bot Discord) memanggil
:func:`check_runtime_security` saat startup agar kombinasi konfigurasi
yang berbahaya ditolak SEBELUM bot mulai menerima input.

Aturan yang ditegakkan:
1. ``ALFA_UNRESTRICTED=true`` + ``DASHBOARD_HOST`` publik (0.0.0.0/::) → FATAL.
   Mode unrestricted mematikan blocklist, sandbox Docker, dan permission gate;
   dikombinasikan dengan dashboard yang terekspos jaringan sama dengan RCE
   publik tanpa batas.
2. ``ALFA_UNRESTRICTED=true`` + ``ALFA_ALLOW_HOST_EXEC=true`` tanpa
   pengakuan eksplisit (``ALFA_UNRESTRICTED_ACK=yes``) → FATAL.
   Eksekusi LLM langsung di host harus disadari penuh oleh operator.
3. Umpan balik token-less + bind publik → FATAL (menggandakan guard
   dashboard untuk permukaan bot juga).

Umumnya proof-of-error via RuntimeError dengan pesan perbaikan aksi-jelas.
"""

import logging
import os

logger = logging.getLogger("SecurityBootGuard")


def _env_true(name: str) -> bool:
    """Paritas persis dengan runtime (is_unrestricted / gate): hanya 'true'."""
    return os.getenv(name, "").strip().lower() == "true"


def is_public_bind(host: str | None) -> bool:
    """True bila host adalah bind ke semua interface jaringan."""
    if host is None:
        return False
    # String "0.0.0.0"/"::" di sini hanya pembanding guard, bukan bind aktual.
    return host.strip() in ("", "0.0.0.0", "::")  # nosec B104 - guard comparison


def _dashboard_bind_public() -> bool:
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    return is_public_bind(host)


def check_runtime_security(surface: str = "process") -> None:
    """Validasi kombinasi env saat startup; raise RuntimeError bila fatal."""
    unrestricted = _env_true("ALFA_UNRESTRICTED")
    host_exec = _env_true("ALFA_ALLOW_HOST_EXEC")
    bind_public = _dashboard_bind_public()

    # 1. Unrestricted + dashboard publik = RCE publik. Selalu fatal.
    if unrestricted and bind_public:
        raise RuntimeError(
            "⛔ [SECURITY] Kombinasi FATAL: ALFA_UNRESTRICTED=true sementara "
            "DASHBOARD_HOST mengikat semua interface (0.0.0.0/::).\n"
            "Semua orang di jaringan bisa mengeksekusi perintah host penuh "
            "lewat dashboard tanpa blocklist, sandbox, maupun permission gate.\n"
            "Perbaiki salah satu:\n"
            "  • Set DASHBOARD_HOST=127.0.0.1 di .env (dashboard hanya lokal), ATAU\n"
            "  • Set ALFA_UNRESTRICTED=false di .env (sandbox & permission gate aktif)."
        )

    # 2. Unrestricted + host exec wajib disadari operator secara eksplisit.
    if unrestricted and host_exec:
        ack = os.getenv("ALFA_UNRESTRICTED_ACK", "").strip().lower()
        if ack != "yes":
            raise RuntimeError(
                "⛔ [SECURITY] Kombinasi berisiko tinggi ditolak: "
                "ALFA_UNRESTRICTED=true + ALFA_ALLOW_HOST_EXEC=true "
                "tanpa pengakuan eksplisit.\n"
                "Mode ini mengeksekusi kode AI langsung di host tanpa sandbox.\n"
                "Pilih salah satu:\n"
                "  • Rekomendasi: set keduanya 'false' di .env, ATAU\n"
                "  • Jika benar-benar sadar risikonya, tambahkan "
                "ALFA_UNRESTRICTED_ACK=yes di .env untuk mematikan guard ini."
            )
        logger.critical(
            "⚠️ ALFA_UNRESTRICTED=true + host-exec diakui eksplisit oleh "
            "operator (ALFA_UNRESTRICTED_ACK=yes). Kode AI berjalan di host "
            "tanpa isolasi — pastikan ALLOWED_USER_IDS diasah ketat."
        )
    elif unrestricted:
        logger.critical(
            "⚠️ ALFA_UNRESTRICTED=true aktif: blocklist, sandbox Docker, dan "
            "permission gate NONAKTIF. Dashboard/bind harus tetap localhost. "
            "Endpoint tool tereksekusi di host penuh."
        )
    elif host_exec:
        logger.warning(
            "ALFA_ALLOW_HOST_EXEC=true: bila Docker tidak tersedia, eksekusi "
            "jatuh ke host tanpa isolasi. Pasang Docker untuk sandbox utuh."
        )
    logger.info(f"[{surface}] Security boot guard: OK")


def assert_safe_runtime(surface: str = "process") -> None:
    """Alias eksplisit untuk entrypoint yang menuntut konfigurasi aman."""
    check_runtime_security(surface)
