# MinerU FastAPI service image (for /file_parse ZIP mode).
#
# This is adapted from the upstream MinerU Dockerfiles (see /data/temp34/MinerU/docker/*).
# Notes:
# - Default CMD runs `mineru-api` on port 8000.
# - The same image is used by the `mineru-vlm` profile with command `mineru-vllm-server`.
# - By default, models are downloaded lazily on first use via HuggingFace/ModelScope cache.
#   (the `docker-compose.parsers.yml` mounts `/root/.cache` to persist downloads).

FROM vllm/vllm-openai:v0.10.1.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    # Default model source; override via compose env (e.g. modelscope).
    MINERU_MODEL_SOURCE=huggingface

# Fonts for CJK + OpenCV runtime deps + curl (healthcheck).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      fonts-noto-core \
      fonts-noto-cjk \
      fontconfig \
      libgl1 \
      curl && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ARG MINERU_PIP_SPEC="mineru[core]==3.4.4"
RUN python3 -m pip install -U "${MINERU_PIP_SPEC}" --break-system-packages

# Optional: pre-download models during build (offline/air-gapped deployments).
ARG MINERU_PREFETCH_MODELS=0
ARG MINERU_MODEL_DOWNLOAD_SOURCE="huggingface"
ARG MINERU_MODEL_DOWNLOAD_TYPE="all"
RUN if [ "${MINERU_PREFETCH_MODELS}" = "1" ]; then \
      MINERU_MODEL_SOURCE="${MINERU_MODEL_DOWNLOAD_SOURCE}" mineru-models-download -s "${MINERU_MODEL_DOWNLOAD_SOURCE}" -m "${MINERU_MODEL_DOWNLOAD_TYPE}"; \
    fi

COPY start_local_api.py /app/start_local_api.py
COPY start_vlm_server.py /app/start_vlm_server.py

EXPOSE 8000 30000

# Reset the inherited vLLM entrypoint. MinerU local ZIP mode should start the
# `mineru-api` service directly, not the OpenAI-compatible vLLM server baked
# into the upstream image.
ENTRYPOINT []
CMD ["python3", "/app/start_local_api.py"]
