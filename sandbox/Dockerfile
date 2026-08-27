FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git patch zip unzip build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY server.py /app/server.py

RUN useradd --create-home --uid 10002 --shell /bin/bash uranus && \
    mkdir -p /workspace /home/uranus && \
    chown -R uranus:uranus /workspace /home/uranus /app

USER uranus
ENV HOME=/home/uranus
WORKDIR /workspace
EXPOSE 5001
CMD ["python", "-m", "uvicorn", "--app-dir", "/app", "server:app", "--host", "0.0.0.0", "--port", "5001"]
