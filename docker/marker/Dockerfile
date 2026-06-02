FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TORCH_DEVICE=cpu

WORKDIR /app

# Minimal runtime dependencies for PDF/OCR conversion, followed by CPU-only
# PyTorch and Marker. Keep this in one RUN layer to avoid stale intermediate
# images and Sonar's consecutive-RUN warning.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      tesseract-ocr \
      ghostscript \
      ffmpeg \
      libglib2.0-0 \
      libgl1 && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip && \
    pip install --retries 5 --timeout 120 \
      "torch @ https://download-r2.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
      "torchvision @ https://download-r2.pytorch.org/whl/cpu/torchvision-0.25.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" && \
    pip install \
      marker-pdf \
      fastapi \
      uvicorn \
      python-multipart && \
    useradd --create-home --shell /usr/sbin/nologin appuser && \
    mkdir -p /home/appuser/.cache && \
    chown -R appuser:appuser /app /home/appuser/.cache

ENV HOME=/home/appuser

USER appuser

EXPOSE 2080

CMD ["marker_server", "--host", "0.0.0.0", "--port", "2080"]
