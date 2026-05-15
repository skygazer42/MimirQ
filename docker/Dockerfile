# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_NO_CACHE_DIR=0


FROM base AS builder

# 复制依赖文件
COPY requirements.txt /tmp/requirements.txt

# 安装系统依赖 + Python 依赖（builder stage）
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/tmp/torch-wheels \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    unixodbc-dev \
    curl \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    # Avoid fetching "build dependencies" in isolated envs when network is flaky.
    # Most of our sdists are pure-Python and build fine with setuptools already present.
    && mkdir -p /tmp/torch-wheels \
    && TORCH_WHL="torch-2.11.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && TORCHVISION_WHL="torchvision-0.26.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && curl --fail --location --continue-at - --retry 10 --retry-all-errors --retry-delay 5 \
        -o "/tmp/torch-wheels/${TORCH_WHL}" \
        "https://download-r2.pytorch.org/whl/cpu/torch-2.11.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && curl --fail --location --continue-at - --retry 10 --retry-all-errors --retry-delay 5 \
        -o "/tmp/torch-wheels/${TORCHVISION_WHL}" \
        "https://download-r2.pytorch.org/whl/cpu/torchvision-0.26.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && /opt/venv/bin/pip install --retries 5 --timeout 120 \
        "/tmp/torch-wheels/${TORCH_WHL}" \
        "/tmp/torch-wheels/${TORCHVISION_WHL}" \
    && for attempt in 1 2 3; do \
        /opt/venv/bin/pip install --retries 10 --timeout 120 --no-build-isolation -r "/tmp/requirements.txt" \
        && break; \
        if [ "$attempt" = "3" ]; then exit 1; fi; \
        sleep "$((attempt * 10))"; \
    done \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*


FROM base AS runtime

# Runtime tools (healthcheck uses curl in docker-compose)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    apt-transport-https \
    libgl1 \
    unixodbc \
    pandoc \
    libreoffice \
    # SQLServer: install Microsoft ODBC driver (msodbcsql18)
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/microsoft-prod.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

ARG MIMIRQ_BUILD_SHA=""
ARG MIMIRQ_BUILD_TIME=""

ENV PATH="/opt/venv/bin:$PATH" \
    # Optional build metadata (exposed via /api/v1/meta)
    MIMIRQ_BUILD_SHA="${MIMIRQ_BUILD_SHA}" \
    MIMIRQ_BUILD_TIME="${MIMIRQ_BUILD_TIME}" \
    # Uvicorn defaults (override via env)
    UVICORN_WORKERS=1 \
    UVICORN_LOG_LEVEL=info

COPY --from=builder /opt/venv /opt/venv

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p uploads logs vector_faiss vector_chroma chroma_db /data/uploads \
    && adduser --disabled-password --gecos "" --home /app appuser \
    && chown -R appuser:appuser /app /data

USER appuser

# 暴露端口
EXPOSE 8000

# Image-level healthcheck (compose may override)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/v1/health/ready || exit 1

# 启动命令
CMD ["sh", "docker/start_backend.sh"]
