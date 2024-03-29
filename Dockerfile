FROM nikolaik/python-nodejs:python3.12-nodejs21-slim-canary

COPY . /app
WORKDIR /app

RUN apt update && apt install -y git

RUN pip install pipenv
RUN pipenv install --deploy
RUN pip install python-telegram-bot==20.0a0
