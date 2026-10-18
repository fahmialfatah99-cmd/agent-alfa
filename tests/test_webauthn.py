"""Test End-to-End WebAuthn/passkey: registrasi attestation + login assertion.

Klien disintesis secara kriptografis di test (P-256 + CBOR none-attestation),
sehingga alur server TERVERIFIKASI SIJARIAH: challenge konsumsi sekali-pakai,
verifikasi tanda tangan asli via pywebauthn, sign-count anti klon.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import encode_cbor

RP_ID = "localhost"
ORIGIN = "http://localhost:8000"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class _SyntheticAuthenticator:
    """Klien WebAuthn sintetis: ES256, attestation \"none\", counter riil."""

    def __init__(self, rp_id: str = RP_ID, origin: str = ORIGIN) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.priv = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = secrets.token_bytes(32)
        self.counter = 0

    def _cose_public_key_bytes(self) -> bytes:
        nums = self.priv.public_key().public_numbers()
        cose = {
            1: 2,
            3: -7,
            -1: 1,
            -2: nums.x.to_bytes(32, "big"),
            -3: nums.y.to_bytes(32, "big"),
        }
        return encode_cbor(cose)

    def _reg_auth_data(self) -> bytes:
        rp_hash = hashlib.sha256(self.rp_id.encode()).digest()
        flags = 0b0100_0001  # UP | AT
        counter = (self.counter).to_bytes(4, "big")
        aaguid = b"\0" * 16
        cred_len = len(self.cred_id).to_bytes(2, "big")
        return (
            rp_hash + bytes([flags]) + counter + aaguid + cred_len + self.cred_id
        ) + self._cose_public_key_bytes()

    def _assertion_auth_data(self) -> bytes:
        rp_hash = hashlib.sha256(self.rp_id.encode()).digest()
        self.counter += 1
        counter = self.counter.to_bytes(4, "big")
        return rp_hash + bytes([0b0000_0001]) + counter  # UP only

    def _client_data(self, kind: str, challenge_b64: str) -> bytes:
        payload = {
            "type": kind,
            "challenge": challenge_b64,
            "origin": self.origin,
            "crossOrigin": False,
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    def register_response(self, challenge_b64: str) -> dict[str, Any]:
        client_data = self._client_data("webauthn.create", challenge_b64)
        attestation = {
            "fmt": "none",
            "attStmt": {},
            "authData": self._reg_auth_data(),
        }
        return {
            "id": _b64(self.cred_id),
            "rawId": _b64(self.cred_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64(client_data),
                "attestationObject": _b64(encode_cbor(attestation)),
            },
        }

    def assertion_response(self, challenge_b64: str) -> dict[str, Any]:
        client_data = self._client_data("webauthn.get", challenge_b64)
        auth_data = self._assertion_auth_data()
        signed = auth_data + hashlib.sha256(client_data).digest()
        signature = self.priv.sign(signed, ec.ECDSA(hashes.SHA256()))
        return {
            "id": _b64(self.cred_id),
            "rawId": _b64(self.cred_id),
            "type": "public-key",
            "response": {
                "authenticatorData": _b64(auth_data),
                "clientDataJSON": _b64(client_data),
                "signature": _b64(signature),
                "userHandle": _b64(b"u"),
            },
        }


def _fresh_session(client_user: str) -> tuple[str, dict]:
    """Bootstrap user + session cookie untuk akses endpoint passkey."""
    from alfa.dashboard.routes.auth import (
        _create_session_token,
        create_user,
        init_auth_db,
        store_session,
    )

    init_auth_db()
    suffix = str(int(time.time() * 1000))
    username = f"{client_user}-{suffix}"
    created = create_user(username, "pw-passkey-123", 0, True)
    user_id = int(created["user_id"])
    token = _create_session_token(user_id, username)
    store_session(user_id, token)
    return token, {"user_id": user_id, "username": username}




@pytest.fixture
def admin_cookie(monkeypatch):
    """Session admin untuk TestClient + DB creds passkey selalu bersih."""
    from alfa.security import webauthn_store

    monkeypatch.setenv("ALFA_WEBAUTHN_RP_ID", RP_ID)
    monkeypatch.setenv("ALFA_WEBAUTHN_ORIGIN", ORIGIN)
    from alfa.core.database import get_connection_pool

    webauthn_store._ensure_tables()  # sinonim fixture: paksa tabel siap dulu
    conn = get_connection_pool().acquire()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dashboard_webauthn_credentials")
        cur.execute("DELETE FROM dashboard_webauthn_challenges")
        conn.commit()
    finally:
        get_connection_pool().release(conn)
    token, info = _fresh_session("wa-admin")
    yield token, info


def _client(apply_session: str | None):
    import importlib

    from fastapi.testclient import TestClient

    app_mod = importlib.import_module("alfa.dashboard.app")
    headers = (
        {} if apply_session is None else {"Cookie": f"session_token={apply_session}"}
    )
    return TestClient(app_mod.app), headers


def test_register_options_menolak_rp_id_ip(admin_cookie, monkeypatch):
    token, _ = admin_cookie
    client, headers = _client(token)
    monkeypatch.setenv("ALFA_WEBAUTHN_RP_ID", "10.1.2.3")
    monkeypatch.delenv("ALFA_WEBAUTHN_ORIGIN", raising=False)
    resp = client.post(
        "/api/auth/webauthn/register/options",
        headers=headers,
        json={},
    )
    assert resp.status_code == 501
    assert "alamat ip" in resp.json()["detail"].lower()


def test_register_ceremony_end_to_end(admin_cookie):
    token, info = admin_cookie
    client, headers = _client(token)
    auth = _SyntheticAuthenticator()

    opts = client.post(
        "/api/auth/webauthn/register/options", headers=headers, json={}
    )
    assert opts.status_code == 200
    body = opts.json()
    assert body["rp"]["id"] == RP_ID
    challenge = body["challenge"]

    reg = auth.register_response(challenge)
    verify = client.post(
        "/api/auth/webauthn/register/verify", headers=headers, json=reg
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["status"] == "success"

    listed = client.get("/api/auth/webauthn/credentials", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert rows and rows[0]["credential_id"] == reg["id"]


def test_login_ceremony_avatar(admin_cookie):
    token, info = admin_cookie
    client, headers = _client(token)
    auth = _SyntheticAuthenticator()

    opts = client.post(
        "/api/auth/webauthn/register/options", headers=headers, json={}
    )
    reg = auth.register_response(opts.json()["challenge"])
    assert (
        client.post(
            "/api/auth/webauthn/register/verify", headers=headers, json=reg
        ).status_code
        == 200
    )

    login_opts = client.get(
        "/api/auth/webauthn/login/options", params={"username": info["username"]}
    )
    assert login_opts.status_code == 200
    keys = login_opts.json()
    assert keys["rpId"] == RP_ID
    assert len(keys["allowCredentials"]) == 1

    assertion = auth.assertion_response(keys["challenge"])
    resp = client.post("/api/auth/webauthn/login/verify", json=assertion)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["user"]["username"] == info["username"]
    assert payload["token"]
    assert "session_token" in resp.cookies


def test_tamper_signature_ditolak(admin_cookie):
    token, info = admin_cookie
    client, headers = _client(token)
    auth = _SyntheticAuthenticator()

    opts = client.post(
        "/api/auth/webauthn/register/options", headers=headers, json={}
    )
    reg = auth.register_response(opts.json()["challenge"])
    assert (
        client.post(
            "/api/auth/webauthn/register/verify", headers=headers, json=reg
        ).status_code
        == 200
    )

    login_opts = client.get("/api/auth/webauthn/login/options")
    assertion = auth.assertion_response(login_opts.json()["challenge"])
    # manipulasi clientDataJSON → signature tidak muat datanya lagi
    forged_client = json.loads(
        base64.urlsafe_b64decode(
            assertion["response"]["clientDataJSON"] + "==="
        ).decode()
    )
    forged_client["origin"] = "http://attacker.example:8000"
    assertion["response"]["clientDataJSON"] = _b64(
        json.dumps(forged_client, separators=(",", ":")).encode()
    )
    resp = client.post("/api/auth/webauthn/login/verify", json=assertion)
    assert resp.status_code in (400, 401), resp.text


def test_challenge_dipakai_dua_kali_ditolak(admin_cookie):
    token, info = admin_cookie
    client, headers = _client(token)
    auth = _SyntheticAuthenticator()

    opts = client.post(
        "/api/auth/webauthn/register/options", headers=headers, json={}
    )
    reg = auth.register_response(opts.json()["challenge"])
    assert (
        client.post(
            "/api/auth/webauthn/register/verify", headers=headers, json=reg
        ).status_code
        == 200
    )

    login_opts = client.get("/api/auth/webauthn/login/options")
    challenge = login_opts.json()["challenge"]
    assertion = auth.assertion_response(challenge)
    first = client.post("/api/auth/webauthn/login/verify", json=assertion)
    assert first.status_code == 200

    replay = auth.assertion_response(challenge)
    second = client.post("/api/auth/webauthn/login/verify", json=replay)
    assert second.status_code == 400


def test_delete_kredential_milik_sendiri(admin_cookie):
    token, info = admin_cookie
    client, headers = _client(token)
    auth = _SyntheticAuthenticator()
    opts = client.post(
        "/api/auth/webauthn/register/options", headers=headers, json={}
    )
    reg = auth.register_response(opts.json()["challenge"])
    client.post("/api/auth/webauthn/register/verify", headers=headers, json=reg)

    gone = client.delete(
        f"/api/auth/webauthn/credentials/{reg['id']}", headers=headers
    )
    assert gone.status_code == 200
    assert gone.json()["deleted"] is True
    listed = client.get("/api/auth/webauthn/credentials", headers=headers)
    assert listed.json() == []
