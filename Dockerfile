# ==============================================================================
# ALFA Sovereign AI - Production Multi-Stage Container
# ==============================================================================

# Stage 1: build native Rust acceleration (alfa_accel) dengan Python yang sama
# dengan runtime agar ABI wheel cocok (cp312).
FROM python:3.12-slim AS rust-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install --no-cache-dir "maturin>=1.7,<2.0"

WORKDIR /build
COPY crates/alfa_accel ./crates/alfa_accel
RUN cd crates/alfa_accel && maturin build --release --out /wheels

# Stage 2: runtime image
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

# Install native Rust acceleration built in stage 1
COPY --from=rust-builder /wheels/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

# Copy source code and static assets
COPY --chown=alfa:alfa . .

USER alfa

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command starts the Web Command Center; can be overridden in docker-compose
CMD ["python3", "-m", "alfa.dashboard.app"]
