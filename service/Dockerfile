FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash coreutils default-jre-headless findutils libgl1 procps unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts /app/scripts
COPY service /app/service

RUN chmod +x /app/scripts/build_harmony_zip.sh

ENV HOST=0.0.0.0
ENV PORT=8080
ENV JOBS_DIR=/data/jobs
ENV BUILD_SCRIPT=/app/scripts/build_harmony_zip.sh
ENV TOOLS_DIR=/opt/harmony/command-line-tools
ENV MAX_UPLOAD_MB=500
ENV MAX_CONCURRENT_BUILDS=1
ENV BUILD_TIMEOUT_SECONDS=1200

EXPOSE 8080

CMD ["python3", "/app/service/server.py"]
