"""Endpoint WebAuthn/passkey end-to-end (option UI + verify + login + kelola
kredential) untuk dashboard.

Dipisah dari ``routes.auth`` agar modul login password tidak membengkak; infra
bersama (_create_session_token, store_session, require_admin, rate limit,
cookie) diimpor dari sana.

Konfigurasi env:
- ``ALFA_WEBAUTHN_RP_ID``  : RP ID (domain / ``localhost``) — default localhost
- ``ALFA_WEBAUTHN_ORIGIN`` : origin klien — default ``http://<rp_id>:8000``

Spesifikasi WebAuthn melarang rp_id berupa alamat IP — endpoint menolak
konfigurasi itu dengan pesan jujur (pakai hostname; produksi wajib HTTPS).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from alfa.dashboard.routes.auth import require_admin
from alfa.security import webauthn_store as store
from alfa.security.webauthn_store import (
    consume_challenge,
    delete_credential,
    get_authenticator_config,
    list_credentials,
    store_challenge,
    update_sign_count,
    upsert_credential,
    user_handle,
)

generate_authentication_options: Any = None
generate_registration_options: Any = None
options_to_json: Any = None
verify_authentication_response: Any = None
verify_registration_response: Any = None
InvalidAuthenticationResponse: Any = Exception
InvalidRegistrationResponse: Any = Exception
AuthenticatorSelectionCriteria: Any = None
PublicKeyCredentialDescriptor: Any = None
PublicKeyCredentialType: Any = None
ResidentKeyRequirement: Any = None
UserVerificationRequirement: Any = None

try:  # pywebauthn (venv); tanpa pustaka router tetap hidup tapi fitur 501
    from webauthn import (
        generate_authentication_options as _gen_auth_opts,
    )
    from webauthn import (
        generate_registration_options as _gen_reg_opts,
    )
    from webauthn import (
        options_to_json as _opts_to_json,
    )
    from webauthn import (
        verify_authentication_response as _ver_auth_resp,
    )
    from webauthn import (
        verify_registration_response as _ver_reg_resp,
    )
    from webauthn.helpers.exceptions import (
        InvalidAuthenticationResponse as _InvAuthResp,
    )
    from webauthn.helpers.exceptions import (
        InvalidRegistrationResponse as _InvRegResp,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria as _AuthSelCrit,
    )
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor as _PubKeyCredDesc,
    )
    from webauthn.helpers.structs import (
        PublicKeyCredentialType as _PubKeyCredType,
    )
    from webauthn.helpers.structs import (
        ResidentKeyRequirement as _ResKeyReq,
    )
    from webauthn.helpers.structs import (
        UserVerificationRequirement as _UserVerReq,
    )

    generate_authentication_options = _gen_auth_opts
    generate_registration_options = _gen_reg_opts
    options_to_json = _opts_to_json
    verify_authentication_response = _ver_auth_resp
    verify_registration_response = _ver_reg_resp
    InvalidAuthenticationResponse = _InvAuthResp
    InvalidRegistrationResponse = _InvRegResp
    AuthenticatorSelectionCriteria = _AuthSelCrit
    PublicKeyCredentialDescriptor = _PubKeyCredDesc
    PublicKeyCredentialType = _PubKeyCredType
    ResidentKeyRequirement = _ResKeyReq
    UserVerificationRequirement = _UserVerReq
except ImportError:  # pragma: no cover — env tanpa pywebauthn
    pass

logger = logging.getLogger("alfa.dashboard.webauthn")

webauthn_router = APIRouter(tags=["webauthn"])


def _require_lib() -> None:
    if verify_registration_response is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "WebAuthn tidak tersedia: paket 'webauthn' tidak terpasang di env ini"
            ),
        )


def _b64url_decode(value: str) -> bytes:
    """Decode base64url yang toleran padding (input unpadded from browser)."""
    return base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))


def _b64url_encode(raw: bytes) -> str:
    """Encode bytes → base64url tanpa padding (format kredensial WebAuthn)."""
    return base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")


def _ip_like(rp_id: str) -> bool:
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", rp_id):
        return True
    return bool(re.fullmatch(r"\[[0-9a-fA-F:]+\]", rp_id))


def _webauthn_config() -> tuple[str, str]:
    """Validasi konfigurasi RP; HTTPException bila tidak memenuhi spesifikasi."""
    rp_id, origin = get_authenticator_config()
    if not rp_id or _ip_like(rp_id):
        raise HTTPException(
            status_code=501,
            detail=(
                "WebAuthn hanya support RP ID bergaya hostname ('localhost' juga "
                f"boleh) — konfigurasi sekarang '{rp_id}'. Dalam spesifikasi "
                "WebAuthn rp_id tidak boleh alamat IP. Produksi: hostname + HTTPS, "
                "lalu set ALFA_WEBAUTHN_RP_ID dan ALFA_WEBAUTHN_ORIGIN."
            ),
        )
    return rp_id, origin


def _current_user(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Login diperlukan untuk endpoint passkey",
            headers={
                "WWW-Authenticate": 'Bearer realm="ALFA Dashboard Session"',
            },
        )
    return dict(user)


def _user_by_username(username: str) -> dict[str, Any] | None:
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, is_admin FROM dashboard_users "
            "WHERE username = ? AND is_active = 1",
            (username,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {"user_id": int(row[0]), "username": row[1], "is_admin": bool(row[2])}
    finally:
        db.get_connection_pool().release(conn)


def _user_by_id(user_id: int) -> dict[str, Any] | None:
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, is_admin FROM dashboard_users "
            "WHERE id = ? AND is_active = 1",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {"user_id": int(row[0]), "username": row[1], "is_admin": bool(row[2])}
    finally:
        db.get_connection_pool().release(conn)


def _descriptors(user_id: int) -> list[Any]:
    if PublicKeyCredentialDescriptor is None:
        return []
    rows = list_credentials(user_id)
    descriptors = []
    for row in rows:
        cred_bytes = _b64url_decode(row["credential_id"])
        descriptors.append(
            PublicKeyCredentialDescriptor(
                id=cred_bytes, transports=None,
                type=PublicKeyCredentialType.PUBLIC_KEY,
            )
        )
    return descriptors


def _session_response(user: dict[str, Any]) -> Response:
    """Response login berhasil — bentuk identik dengan login password."""
    from alfa.dashboard.app import SESSION_DURATION_HOURS
    from alfa.dashboard.routes.auth import (
        _create_session_token,
        store_session,
    )

    token = _create_session_token(int(user["user_id"]), user["username"])
    store_session(int(user["user_id"]), token)
    payload = {
        "status": "success",
        "message": "Login passkey berhasil",
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "is_admin": user["is_admin"],
        },
    }
    response = Response(
        content=json.dumps(payload), media_type="application/json"
    )
    response.set_cookie(
        key="session_token",
        value=token,
        max_age=SESSION_DURATION_HOURS * 3600,
        httponly=True,
        secure=False,
        samesite="lax",
    )
    return response


def _parse_client_data(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = _b64url_decode(payload["response"]["clientDataJSON"])
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — payload browser bebas bentuknya
        raise HTTPException(
            status_code=400, detail="clientDataJSON tidak dapat diparse"
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=400, detail="clientDataJSON tidak dapat diparse"
        )
    return parsed


# ─── registrasi passkey (user yang sedang login, miliknya sendiri) ───────────


@webauthn_router.post("/api/auth/webauthn/register/options", dependencies=[Depends(require_admin)])
async def webauthn_register_options(request: Request):
    """Challenge registrasi passkey untuk user yang sedang login."""
    _require_lib()
    user = _current_user(request)
    user_id = int(user["user_id"])
    rp_id, _origin = _webauthn_config()

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="ALFA Sovereign Command Center",
        user_name=str(user["username"]),
        user_id=user_handle(user_id),
        user_display_name=str(user["username"]),
        exclude_credentials=_descriptors(user_id),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    store_challenge("reg", base64.urlsafe_b64encode(options.challenge).decode().rstrip("="), user_id)
    return json.loads(options_to_json(options))


@webauthn_router.post("/api/auth/webauthn/register/verify", dependencies=[Depends(require_admin)])
async def webauthn_register_verify(request: Request):
    """Verify attestation; challenge harus satu-pakai & bind ke sesi pemanggil."""
    _require_lib()
    current = _current_user(request)
    current_id = int(current["user_id"])
    rp_id, origin = _webauthn_config()
    payload = await request.json()
    client_data = _parse_client_data(payload)

    challenge_row = consume_challenge("reg", str(client_data.get("challenge", "")))
    if not challenge_row:
        raise HTTPException(
            status_code=400,
            detail="Challenge tidak dikenal / kedaluwarsa / sudah dipakai",
        )
    if challenge_row["user_id"] != current_id:
        raise HTTPException(
            status_code=403, detail="Challenge registrasi tidak milik sesi ini"
        )

    try:
        verified = verify_registration_response(
            credential=payload,
            expected_challenge=_b64url_decode(str(client_data["challenge"])),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_presence=True,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(
            status_code=400, detail=f"Attestasi ditolak: {exc}"
        ) from exc

    upsert_credential(
        user_id=current_id,
        credential_id=_b64url_encode(verified.credential_id),
        public_key=_b64url_encode(verified.credential_public_key),
        sign_count=int(verified.sign_count or 0),
        aaguid=str(getattr(verified, "aaguid", "") or ""),
        fmt=str(
            getattr(getattr(verified, "fmt", None), "value", None) or "none"
        ),
        device_type=str(
            getattr(getattr(verified, "credential_device_type", None), "value", None)
            or "singleDevice"
        ),
    )
    logger.info("passkey teregis untuk user %s", current_id)
    return {"status": "success", "message": "Passkey teregis"}


# ─── login passkey ────────────────────────────────────────────────────────────


@webauthn_router.get("/api/auth/webauthn/login/options")
async def webauthn_login_options(request: Request, username: str = ""):
    """Challenge login; bila username diketahui → dibatasi passkey milik itu."""
    _require_lib()
    rp_id, _origin = _webauthn_config()

    allow: list[Any] = []
    if username:
        row = _user_by_username(username)
        if row:
            allow = _descriptors(int(row["user_id"]))

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    store_challenge(
        "login",
        base64.urlsafe_b64encode(options.challenge).decode().rstrip("="),
        None,
    )
    return json.loads(options_to_json(options))


@webauthn_router.post("/api/auth/webauthn/login/verify")
async def webauthn_login_verify(request: Request):
    """Verifikasi assertion → terbitkan session (bentuk sama dgn login password)."""
    from alfa.dashboard.routes.auth import _rate_limit, _request_ip

    _require_lib()
    allowed, retry_after = _rate_limit(
        f"webauthn-login:{_request_ip(request)}", 10, 300
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak upaya login passkey. Tunggu {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    rp_id, origin = _webauthn_config()
    payload = await request.json()
    client_data = _parse_client_data(payload)

    if not consume_challenge("login", str(client_data.get("challenge", ""))):
        raise HTTPException(
            status_code=400,
            detail="Challenge tidak dikenal / kedaluwarsa / sudah dipakai",
        )

    credential_id = str(payload.get("id") or payload.get("rawId") or "")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Passkey tanpa identifier")
    cred_row = store.get_credential(credential_id)
    if not cred_row:
        raise HTTPException(status_code=401, detail="Passkey tidak terdaftar")

    try:
        verified = verify_authentication_response(
            credential=payload,
            expected_challenge=_b64url_decode(str(client_data["challenge"])),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=_b64url_decode(cred_row["public_key"]),
            credential_current_sign_count=int(cred_row["sign_count"]),
        )
    except InvalidAuthenticationResponse as exc:
        raise HTTPException(
            status_code=401, detail=f"Assertion ditolak: {exc}"
        ) from exc

    new_count = int(verified.new_sign_count or 0)
    if (
        cred_row["sign_count"] > 0
        and new_count > 0
        and new_count <= int(cred_row["sign_count"])
    ):
        # counter tidak naik → indikasi klon; cabut defensively
        logger.error(
            "sign_count passkey user %s tidak maju (%s <= %s) — dihapus defensif",
            cred_row["user_id"], new_count, cred_row["sign_count"],
        )
        delete_credential(credential_id, 0, True)
        raise HTTPException(
            status_code=401,
            detail="Passkey gagal integritas counter (indikasi klon) — "
            "dicabut, daftar ulang",
        )

    user = _user_by_id(int(cred_row["user_id"]))
    if not user:
        raise HTTPException(status_code=401, detail="User tidak aktif")
    update_sign_count(credential_id, new_count)
    logger.info("login passkey sukses: user %s", user["user_id"])
    return _session_response(user)


# ─── kelola kredential ────────────────────────────────────────────────────────


@webauthn_router.get("/api/auth/webauthn/credentials")
async def webauthn_list_credentials(request: Request):
    """Daftar passkey milik sendiri."""
    user = _current_user(request)
    return list_credentials(int(user["user_id"]))


@webauthn_router.delete("/api/auth/webauthn/credentials/{credential_id}", dependencies=[Depends(require_admin)])
async def webauthn_delete_credential(request: Request, credential_id: str):
    """Hapus passkey milik sendiri; admin boleh milik pengguna mana pun."""
    user = _current_user(request)
    is_admin = bool(user.get("is_admin"))
    removed = delete_credential(credential_id, int(user["user_id"]), is_admin)
    if not removed:
        return {"status": "not_found", "deleted": False}
    logger.info(
        "passkey %s dihapus oleh user %s (admin=%s)", credential_id, user["user_id"],
        is_admin,
    )
    return {"status": "removed", "deleted": True}
