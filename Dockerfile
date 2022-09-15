FROM nikolaik/python-nodejs:python3.9-nodejs16-bullseye

COPY . /app
WORKDIR /app

RUN pip install pipenv
RUN pipenv install --deploy
RUN pip install python-telegram-bot==20.0a0
