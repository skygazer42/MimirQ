# olmOCR FastAPI wrapper service image.
#
# This image wraps the upstream olmOCR CLI (`python -m olmocr.pipeline`) behind
# a simple HTTP API so the main MimirQ backend can call it like Marker/PaddleVL.

FROM alleninstituteforai/olmocr:v0.4.27

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python3 -m pip install -U pip && python3 -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY server.py ./server.py

RUN useradd --create-home --shell /usr/sbin/nologin appuser && \
    mkdir -p /home/appuser/.cache && \
    chown -R appuser:appuser /app /home/appuser/.cache

ENV HOME=/home/appuser

USER appuser

EXPOSE 2085

# Override upstream ENTRYPOINT (often /bin/bash) so this container runs as a service.
ENTRYPOINT ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "2085"]
