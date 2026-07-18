FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIPENV_NOSPIN=1 \
    PIPENV_VENV_IN_PROJECT=1 \
    PIPENV_IGNORE_VIRTUALENVS=1

ARG PIPENV_RELEASE=2024.4.0

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock ./
RUN python -m venv /opt/pipenv \
    && /opt/pipenv/bin/pip install "pipenv==${PIPENV_RELEASE}" \
    && /opt/pipenv/bin/pipenv verify \
    && /opt/pipenv/bin/pipenv sync

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

COPY --from=builder /app/.venv /app/.venv

RUN groupadd --system --gid 10001 cometa \
    && useradd --system --uid 10001 --gid cometa --home-dir /home/cometa --create-home cometa

COPY --chown=cometa:cometa app.py env.py telegram_bot.py ./
COPY --chown=cometa:cometa api ./api
COPY --chown=cometa:cometa blockchain ./blockchain
COPY --chown=cometa:cometa bot ./bot
COPY --chown=cometa:cometa core ./core
COPY --chown=cometa:cometa dexes ./dexes
COPY --chown=cometa:cometa flex ./flex
COPY --chown=cometa:cometa scripts/run.sh ./scripts/run.sh

USER cometa

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/status' % os.getenv('SERVER_PORT', '8000'), timeout=4).close()"]

STOPSIGNAL SIGTERM
ENTRYPOINT ["/app/scripts/run.sh"]
