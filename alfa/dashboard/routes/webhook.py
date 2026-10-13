"""Webhook integration router for ALFA Sovereign AI.

Enables secure inbound triggers from external automation systems (n8n, Zapier,
GitHub webhooks, custom cron, or curl scripts) with token/secret validation
and autonomous agent turn execution.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from alfa.dashboard.common import DASHBOARD_AUTH_TOKEN, get_primary_user_id
from alfa.dashboard.schemas.webhook import (
    GitHubWebhookResponse,
    WebhookStatusResponse,
    WebhookTriggerRequest,
    WebhookTriggerResponse,
)

logger = logging.getLogger("Dashboard.Webhook")

webhook_router = APIRouter(prefix="/api/v1/webhook", tags=["External Webhooks"])

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip() or DASHBOARD_AUTH_TOKEN


def _verify_webhook_auth(
    authorization: str | None = None,
    x_webhook_secret: str | None = None,
    client_host: str = "127.0.0.1",
) -> bool:
    """Validate webhook authentication against configured secrets."""
    expected = WEBHOOK_SECRET or DASHBOARD_AUTH_TOKEN

    # If secret is set, verify either header
    if expected:
        # Check X-Webhook-Secret / X-ALFA-Webhook-Secret
        if x_webhook_secret and secrets.compare_digest(x_webhook_secret, expected):
            return True

        # Check Bearer token in Authorization header
        if authorization:
            token = authorization.replace("Bearer ", "").strip()
            if secrets.compare_digest(token, expected):
                return True

        return False

    # If no secret is configured, allow only loopback/localhost requests
    return client_host in ("127.0.0.1", "localhost", "::1")


@webhook_router.get(
    "/status",
    response_model=WebhookStatusResponse,
    summary="Check Webhook Listener Status",
)
async def webhook_status():
    """Verify webhook endpoint availability and requirements."""
    return WebhookStatusResponse(
        status="ready",
        endpoint="/api/v1/webhook/trigger",
        auth_required=bool(WEBHOOK_SECRET or DASHBOARD_AUTH_TOKEN),
        supported_events=["custom_event", "n8n_alert", "scheduled_job", "github_event"],
    )


@webhook_router.post(
    "/trigger",
    response_model=WebhookTriggerResponse,
    summary="Trigger Autonomous Agent Task via Webhook",
)
async def trigger_webhook(
    request: Request,
    payload: WebhookTriggerRequest,
    authorization: str | None = Header(None),
    x_webhook_secret: str | None = Header(None, alias="X-Webhook-Secret"),
    x_alfa_secret: str | None = Header(None, alias="X-ALFA-Webhook-Secret"),
):
    """
    Execute an autonomous ALFA agent task triggered by an external system.

    Accepts instructions from n8n, Zapier, Make, GitHub, or curl, executes real tools,
    and optionally dispatches result notifications to the owner's Telegram chat.
    """
    client_ip = (
        getattr(request.client, "host", "127.0.0.1") if request.client else "127.0.0.1"
    )
    secret_candidate = x_webhook_secret or x_alfa_secret

    if not _verify_webhook_auth(
        authorization=authorization,
        x_webhook_secret=secret_candidate,
        client_host=client_ip,
    ):
        logger.warning(f"Unauthorized webhook trigger attempt from {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akses webhook ditolak: Kredensial tidak valid atau secret belum disetel.",
        )

    start_time = time.monotonic()
    primary_uid = get_primary_user_id()

    # Build contextual prompt for the agent
    meta_str = ""
    if payload.metadata:
        meta_str = (
            f"\nMetadata Terlampir: {json.dumps(payload.metadata, ensure_ascii=False)}"
        )

    formatted_prompt = (
        f"⚡ [INBOUND WEBHOOK TRIGGER: {payload.event.upper()}]\n"
        f"Asal Pemicu: {payload.source}\n"
        f"Instruksi: {payload.prompt}{meta_str}\n\n"
        "Jalankan tugas ini secara otonom dengan tool nyata yang relevan dan berikan ringkasan yang jelas."
    )

    try:
        from alfa.bot.turn_executor import run_agent_turn

        result_text = await run_agent_turn(
            user_id=primary_uid,
            user_prompt=formatted_prompt,
            override_model=payload.model,
        )
    except Exception as e:
        logger.error(f"Gagal mengeksekusi giliran agent via webhook: {e}")
        result_text = f"❌ Eksekusi webhook gagal: {e}"

    elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
    telegram_dispatched = False

    # Forward alert to Telegram if requested
    if payload.dispatch_telegram:
        try:
            from alfa.bot.helpers import safe_send_message
            from alfa.swarm import subagents

            app = subagents.get_telegram_app()
            if app:
                msg = (
                    f"🔔 **[WEBHOOK ALERT: {payload.event.upper()}]**\n"
                    f"Sumber: `{payload.source}`\n\n"
                    f"{result_text}"
                )
                await safe_send_message(app, primary_uid, msg)
                telegram_dispatched = True
        except Exception as tg_err:
            logger.warning(f"Gagal mengirim notifikasi webhook ke Telegram: {tg_err}")

    return WebhookTriggerResponse(
        status="success" if not result_text.startswith("❌") else "error",
        event=payload.event,
        response=result_text,
        telegram_dispatched=telegram_dispatched,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@webhook_router.post(
    "/github",
    response_model=GitHubWebhookResponse,
    summary="Handle GitHub Repository Webhook Events",
)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default="ping", alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
):
    """
    Receive and process GitHub repository webhook events (push, issues, pull_request).
    """
    body = await request.body()
    github_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

    if github_secret and x_hub_signature_256:
        signature = x_hub_signature_256.replace("sha256=", "")
        mac = hmac.new(github_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not secrets.compare_digest(mac, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GitHub webhook signature",
            )

    try:
        data: dict[str, Any] = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        data = {}

    repo_name = data.get("repository", {}).get("full_name", "unknown_repo")
    sender = data.get("sender", {}).get("login", "unknown_sender")

    summary = f"GitHub event '{x_github_event}' received on repo '{repo_name}' from @{sender}."
    logger.info(summary)

    # Ingest event notification to Telegram
    try:
        from alfa.bot.helpers import safe_send_message
        from alfa.swarm import subagents

        app = subagents.get_telegram_app()
        if app:
            primary_uid = get_primary_user_id()
            await safe_send_message(
                app,
                primary_uid,
                f"🐙 **[GITHUB EVENT: {x_github_event.upper()}]**\n"
                f"Repository: `{repo_name}`\n"
                f"Actor: @{sender}",
            )
    except Exception as e:
        logger.debug(f"GitHub event Telegram forward skipped: {e}")

    return GitHubWebhookResponse(
        status="accepted",
        event=x_github_event,
        message=summary,
        action_taken="dispatched_to_dashboard_event_stream",
    )
