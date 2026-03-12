FROM nikolaik/python-nodejs:python3.12-nodejs21-slim-canary

WORKDIR /app

RUN apt update && apt install -y --no-install-recommends git

# Install dependencies first for layer caching
COPY Pipfile Pipfile.lock ./
RUN pip install pipenv
RUN pipenv install --deploy
RUN pip install python-telegram-bot==20.0a0

# Install curl for healthcheck
RUN apt install -y curl && rm -rf /var/lib/apt/lists/*

# Copy application code (changes here don't invalidate pip cache)
COPY . /app

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/status || exit 1
