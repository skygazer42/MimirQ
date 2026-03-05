FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OpenCV runtime deps (paddleocr pulls opencv-python); plus common font/graphics libs.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      libgomp1 \
      libgl1 \
      libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY server.py ./server.py

EXPOSE 9030

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9030"]
