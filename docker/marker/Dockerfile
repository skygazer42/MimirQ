FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TORCH_DEVICE=cpu

WORKDIR /app

# Minimal runtime dependencies for PDF/OCR conversion.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      tesseract-ocr \
      ghostscript \
      ffmpeg \
      libglib2.0-0 \
      libgl1 && \
    rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first so Marker does not try to pull CUDA wheels.
# Use the same download-r2 wheel URLs already proven in the main backend image;
# the generic PyTorch CPU index intermittently fails SSL negotiation here.
RUN pip install --upgrade pip && \
    pip install --retries 5 --timeout 120 \
      "torch @ https://download-r2.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" \
      "torchvision @ https://download-r2.pytorch.org/whl/cpu/torchvision-0.25.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" && \
    pip install \
      marker-pdf \
      fastapi \
      uvicorn \
      python-multipart

EXPOSE 2080

CMD ["marker_server", "--host", "0.0.0.0", "--port", "2080"]
