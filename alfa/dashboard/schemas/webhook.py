"""Pydantic schemas for external webhooks."""

from typing import Any

from pydantic import BaseModel, Field


class WebhookTriggerRequest(BaseModel):
    """Payload to trigger an autonomous agent turn via external webhook."""

    event: str = Field(
        default="custom_event",
        description="Event name or type (e.g. 'n8n_alert', 'scheduled_job', 'inbound_lead')",
    )
    prompt: str = Field(
        ...,
        description="Instruction or message for ALFA to execute or process",
        min_length=1,
    )
    source: str = Field(
        default="external_webhook",
        description="Origin of the trigger (e.g. 'n8n', 'zapier', 'curl', 'github')",
    )
    dispatch_telegram: bool = Field(
        default=False,
        description="Whether to forward the execution summary and alerts to Telegram owner chat",
    )
    model: str | None = Field(
        default=None,
        description="Optional AI model override for this turn",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional contextual metadata passed alongside the event",
    )


class WebhookTriggerResponse(BaseModel):
    """Response model returned after webhook execution."""

    status: str = Field(..., description="Execution status: 'success' or 'error'")
    event: str = Field(..., description="Processed event name")
    response: str = Field(
        ..., description="Autonomous agent output or execution summary"
    )
    telegram_dispatched: bool = Field(
        default=False, description="Whether notification was forwarded to Telegram"
    )
    duration_ms: float = Field(
        ..., description="Execution elapsed time in milliseconds"
    )
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")


class WebhookStatusResponse(BaseModel):
    """Response model for webhook service status check."""

    status: str = Field("ready", description="Webhook listener status")
    endpoint: str = Field(
        "/api/v1/webhook/trigger", description="Trigger endpoint path"
    )
    auth_required: bool = Field(
        True, description="Whether API key or token authentication is required"
    )
    supported_events: list[str] = Field(
        default_factory=lambda: [
            "custom_event",
            "n8n_alert",
            "scheduled_job",
            "github_event",
        ],
        description="List of commonly supported event types",
    )


class GitHubWebhookResponse(BaseModel):
    """Response model for GitHub event webhook."""

    status: str
    event: str
    message: str
    action_taken: str | None = None
