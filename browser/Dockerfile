FROM mcr.microsoft.com/playwright/python:v1.51.0-jammy

WORKDIR /app
COPY server.py /app/server.py
RUN useradd --create-home --uid 10003 uranus-browser && \
    mkdir -p /browser-profile /workspace && \
    chown -R uranus-browser:uranus-browser /app /browser-profile /workspace
USER uranus-browser
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 5002
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5002"]
