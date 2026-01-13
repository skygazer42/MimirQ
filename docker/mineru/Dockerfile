# MinerU local FastAPI service image (for /file_parse ZIP mode).
#
# This is adapted from the upstream MinerU Dockerfiles (see /data/temp34/MinerU/docker/*).
# Notes:
# - Default CMD runs `mineru-api` on port 8000.
# - Model download can be heavy; it is enabled by default for a ready-to-serve image.

FROM vllm/vllm-openai:v0.10.1.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

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

ARG MINERU_PIP_SPEC="mineru[core]>=2.7.0"
RUN python3 -m pip install -U "${MINERU_PIP_SPEC}" --break-system-packages && \
    python3 -m pip cache purge

# Optional: pre-download models during build (recommended for offline/production use).
ARG MINERU_DOWNLOAD_MODELS=1
ARG MINERU_MODEL_DOWNLOAD_SOURCE="huggingface"
ARG MINERU_MODEL_DOWNLOAD_TYPE="all"
RUN if [ "${MINERU_DOWNLOAD_MODELS}" = "1" ]; then \
      mineru-models-download -s "${MINERU_MODEL_DOWNLOAD_SOURCE}" -m "${MINERU_MODEL_DOWNLOAD_TYPE}"; \
    fi

# MinerU API uses MINERU_MODEL_SOURCE env var to select local models.
ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]

EXPOSE 8000

CMD ["mineru-api", "--host", "0.0.0.0", "--port", "8000"]

