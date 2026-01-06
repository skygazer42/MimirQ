FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1


FROM base AS builder

# Allow selecting a smaller dependency set for Docker builds.
# - requirements-minimal.txt: default (API-based LLM/Embeddings; smaller image)
# - requirements.txt: full (includes heavy optional parsers/local embeddings)
ARG REQUIREMENTS_FILE=requirements-minimal.txt

# 复制依赖文件
COPY requirements*.txt /tmp/

# 安装系统依赖 + Python 依赖（builder stage）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r "/tmp/${REQUIREMENTS_FILE}" \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*


FROM base AS runtime

# Runtime tools (healthcheck uses curl in docker-compose)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

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

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
