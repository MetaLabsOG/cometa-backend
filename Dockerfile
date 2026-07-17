FROM nikolaik/python-nodejs:python3.12-nodejs22-slim@sha256:15a5d044754b9c8d7a86df9b7bb44087b8737070ea249af084d2670aeaad75ba

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIPENV_NOSPIN=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG PIPENV_VERSION=2024.4.0

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock ./
RUN python -m pip install "pipenv==${PIPENV_VERSION}" \
    && pipenv verify \
    && pipenv sync --system

RUN groupadd --system --gid 10001 cometa \
    && useradd --system --uid 10001 --gid cometa --home-dir /home/cometa --create-home cometa

COPY --chown=cometa:cometa . .

USER cometa

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl --fail --silent --show-error "http://127.0.0.1:${SERVER_PORT:-8000}/status" || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT ["/app/scripts/run.sh"]
