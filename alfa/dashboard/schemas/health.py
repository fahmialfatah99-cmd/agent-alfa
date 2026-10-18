"""Pydantic schemas for health and system metrics endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class HealthCheckResponse(BaseModel):
    """Response model for system health check endpoints."""

    status: str = Field(
        ..., description="Overall health status ('healthy' or 'degraded')"
    )
    service: str = Field(..., description="Service identifier")
    version: str = Field(..., description="Application version")
    database: str = Field(..., description="Database connectivity status")
    database_tables: int | None = Field(
        None, description="Total active database tables count"
    )
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    memory_rss_mb: float = Field(
        ..., description="Process resident set size in megabytes"
    )
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")


class SystemMetricsResponse(BaseModel):
    """Response model for detailed system resource telemetry."""

    service: str
    version: str
    timestamp: str
    system: dict[str, Any] = Field(
        ..., description="Host OS CPU, memory, and disk usage"
    )
    process: dict[str, Any] = Field(..., description="Process-specific telemetry")
    database_pool: dict[str, Any] = Field(..., description="Connection pool metrics")
    agent: dict[str, Any] = Field(
        default_factory=dict,
        description="Metrik runtime agent: turns, tool-calls, latensi p50/p95",
    )
