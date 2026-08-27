FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git patch zip unzip build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10002 --shell /bin/bash uranus
WORKDIR /workspace
COPY --from=python:3.11-slim /usr/local/bin/python /usr/local/bin/python
COPY server.py /app/server.py
RUN mkdir -p /workspace /home/uranus && chown -R uranus:uranus /workspace /home/uranus /app
USER uranus
ENV HOME=/home/uranus PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 5001
CMD ["python", "/app/server.py"]
