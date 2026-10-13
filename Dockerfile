# ==============================================================================
# ALFA Sovereign AI - Production Multi-Stage Container
# ==============================================================================
FROM python:3.12-slim as base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies & multimedia runtimes
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    sqlite3 \
    ffmpeg \
    procps \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create application user
RUN useradd -ms /bin/bash -u 1000 alfa && \
    mkdir -p /app /home/alfa/Dokumen/ALFA_SWARM_OUTPUTS /dev/shm/alfa_sandbox && \
    chown -R alfa:alfa /app /home/alfa /dev/shm/alfa_sandbox

WORKDIR /app

# Copy dependency specifications
COPY requirements.txt pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy source code and static assets
COPY --chown=alfa:alfa . .

USER alfa

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command starts the Web Command Center; can be overridden in docker-compose
CMD ["python3", "web_dashboard.py"]
