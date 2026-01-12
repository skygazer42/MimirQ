FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt

# Base tools (git for clone; ca-certificates for HTTPS).
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Clone Marker
RUN git clone --depth 1 https://github.com/VikParuchuri/marker.git /opt/marker
WORKDIR /opt/marker

# System dependencies.
# Marker provides a list under scripts/install/apt-requirements.txt; we also include common OCR/PDF tools.
RUN apt-get update && \
    apt-get install -y --no-install-recommends $(cat scripts/install/apt-requirements.txt) && \
    apt-get install -y --no-install-recommends tesseract-ocr ghostscript ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies (poetry-managed).
RUN pip install --upgrade pip && \
    pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi

# API server deps (Marker provides marker_server entrypoint).
RUN pip install -U uvicorn fastapi python-multipart

EXPOSE 2080

CMD ["poetry", "run", "marker_server", "--host", "0.0.0.0", "--port", "2080"]

