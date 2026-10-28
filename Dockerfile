FROM python:3.12-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="Curatarr" \
      org.opencontainers.image.description="Build Plex collections from IMDb, TMDB, Trakt and MDBList lists" \
      org.opencontainers.image.source="https://github.com/gaterunner341/curatarr" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CURATARR_CONFIG_DIR=/config \
    CURATARR_PORT=8585 \
    PUID=1000 \
    PGID=1000 \
    TZ=Etc/UTC

# DejaVu fonts draw the posters for holidays you add yourself.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /config

VOLUME /config
EXPOSE 8585

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"CURATARR_PORT\",\"8585\")}/api/health', timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app"]
