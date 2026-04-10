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
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    unixodbc-dev \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    # Avoid fetching "build dependencies" in isolated envs when network is flaky.
    # Most of our sdists are pure-Python and build fine with setuptools already present.
    && /opt/venv/bin/pip install --retries 5 --timeout 120 --no-cache-dir \
        "torch @ https://download-r2.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
        "torchvision @ https://download-r2.pytorch.org/whl/cpu/torchvision-0.25.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && /opt/venv/bin/pip install --retries 10 --no-cache-dir --no-build-isolation -r "/tmp/requirements.txt" \
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
