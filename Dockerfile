FROM node:22-slim AS css

WORKDIR /src
COPY package.json package-lock.json ./
COPY assets ./assets
COPY app/templates ./app/templates
RUN npm ci && mkdir -p app/static && npm run build:css

FROM python:3.12-slim

# ffmpeg is required for audio assembly + loudness normalization.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=css /src/app/static/style.css ./app/static/style.css

ENV DATA_DIR=/data \
    PYTHONUNBUFFERED=1

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=8)" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
