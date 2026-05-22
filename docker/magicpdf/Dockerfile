# MagicPDF FastAPI wrapper service image.
#
# This image keeps the `magic-pdf` CLI and model runtime outside the main API
# container so parser dependencies, CUDA, and long-running jobs are isolated.

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

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
    python -m pip install magic-pdf==1.3.12

COPY server.py ./server.py

EXPOSE 2095

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "2095"]
