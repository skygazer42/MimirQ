ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.11-slim@sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3
FROM ${PYTHON_BASE_IMAGE} AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_NO_CACHE_DIR=0 \
    PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

# Keep package installation on mirrors that are reachable from the runner host.
RUN sed -i \
    -e 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
    -e 's|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
    -e 's|http://security.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
    /etc/apt/sources.list.d/debian.sources


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
    && TORCH_WHL="torch-2.13.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && TORCHVISION_WHL="torchvision-0.28.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
    && curl --fail --location --continue-at - --retry 10 --retry-all-errors --retry-delay 5 \
        -o "/tmp/torch-wheels/${TORCH_WHL}" \
        "https://download-r2.pytorch.org/whl/cpu/${TORCH_WHL}" \
    && curl --fail --location --continue-at - --retry 10 --retry-all-errors --retry-delay 5 \
        -o "/tmp/torch-wheels/${TORCHVISION_WHL}" \
        "https://download-r2.pytorch.org/whl/cpu/${TORCHVISION_WHL}" \
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

ENV PATH="/opt/venv/bin:$PATH" \
    XDG_CACHE_HOME=/app/.cache \
    HF_HOME=/app/.cache/huggingface \
    # Uvicorn defaults (override via env)
    UVICORN_WORKERS=1 \
    UVICORN_LOG_LEVEL=info

COPY --from=builder /opt/venv /opt/venv

# 创建必要的目录
RUN mkdir -p uploads logs vector_faiss vector_chroma chroma_db /data/uploads \
    /app/.cache/huggingface \
    /opt/venv/lib/python3.11/site-packages/rapidocr/models \
    /opt/venv/lib/python3.11/site-packages/rapid_table/models \
    && adduser --disabled-password --gecos "" --home /app appuser \
    && touch /app/.env /app/.env.lock \
    && chown root:appuser /app \
    && chmod 1775 /app \
    && chown appuser:appuser /app/.env /app/.env.lock \
    && chown -R appuser:appuser \
        uploads \
        logs \
        vector_faiss \
        vector_chroma \
        chroma_db \
        /app/.cache \
        /data \
        /opt/venv/lib/python3.11/site-packages/rapidocr/models \
        /opt/venv/lib/python3.11/site-packages/rapid_table/models

COPY scripts/bootstrap_mimirq_models.py ./scripts/bootstrap_mimirq_models.py
# Parsing weights are pinned and verified during the image build; runtime stays offline.
RUN --mount=type=cache,target=/app/.cache/huggingface \
    /opt/venv/bin/python scripts/bootstrap_mimirq_models.py

# Avoid making the first prompt-preview request download the token encoding.
ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && /opt/venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")' \
    && chown -R appuser:appuser "$TIKTOKEN_CACHE_DIR"

# Build metadata changes frequently and must not invalidate the model layer above.
ARG MIMIRQ_BUILD_SHA=""
ARG MIMIRQ_BUILD_TIME=""
ENV MIMIRQ_BUILD_SHA="${MIMIRQ_BUILD_SHA}" \
    MIMIRQ_BUILD_TIME="${MIMIRQ_BUILD_TIME}"

# 复制运行时需要的应用路径，避免把构建上下文整体带入镜像。
COPY app ./app
COPY alembic ./alembic
COPY config ./config
COPY ci/perf_suite_baseline.v1.json ci/perf_regression_policy.v1.json ./ci/
COPY alembic.ini main.py ./
COPY scripts/alembic_cli.py scripts/run_db_maintenance_jobs.py scripts/run_nightly_ablations.py scripts/run_periodic_audit_jobs.py scripts/run_retention_jobs.py ./scripts/
COPY docker/start_backend.sh ./docker/start_backend.sh

USER appuser

# 暴露端口
EXPOSE 8000

# Image-level healthcheck (compose may override)
HEALTHCHECK --interval=30s --timeout=5s --start-period=240s --retries=3 \
  CMD curl --noproxy '*' -fsS http://localhost:8000/api/v1/health/ready || exit 1

# 启动命令
CMD ["sh", "docker/start_backend.sh"]
