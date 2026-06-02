# MagicPDF FastAPI wrapper service image.
#
# This image keeps the `magic-pdf` CLI and model runtime outside the main API
# container so parser dependencies, CUDA, and long-running jobs are isolated.
#
# MagicPDF 1.3.x officially supports torch 2.2~2.6 while excluding 2.5, so we
# pin the base image to 2.6 and preinstall the matching torchvision wheel to
# avoid pip re-resolving a newer CUDA stack at build time.

FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      libgl1 \
      libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r requirements.txt && \
    python -m pip install torchvision==0.21.0 && \
    python -m pip install "magic-pdf[full]==1.3.12"

COPY server.py ./server.py

RUN useradd --create-home --shell /usr/sbin/nologin appuser && \
    mkdir -p /home/appuser/.cache /var/lib/mimirq/magicpdf-artifacts && \
    chown -R appuser:appuser /app /home/appuser/.cache /var/lib/mimirq

ENV HOME=/home/appuser

USER appuser

EXPOSE 2095

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "2095"]
