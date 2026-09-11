FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 videott && useradd --uid 10001 --gid videott --create-home videott \
    && mkdir -p /data/media && chown -R videott:videott /data/media
WORKDIR /app
COPY worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/ /app/
COPY scripts/ /app/scripts/
COPY workflows/ /app/workflows/
USER videott
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS test
ENV RUFF_CACHE_DIR=/tmp/ruff-cache PYTEST_ADDOPTS="-p no:cacheprovider"
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER videott
CMD ["pytest", "-q"]

FROM base AS production
