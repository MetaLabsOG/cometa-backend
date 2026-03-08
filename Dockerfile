FROM nikolaik/python-nodejs:python3.12-nodejs21-slim-canary

WORKDIR /app

RUN apt update && apt install -y git

# Install dependencies first for layer caching
COPY Pipfile Pipfile.lock ./
RUN pip install pipenv
RUN pipenv install --deploy
RUN pip install python-telegram-bot==20.0a0

# Copy application code (changes here don't invalidate pip cache)
COPY . /app
