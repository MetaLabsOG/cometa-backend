FROM python:3.9

COPY . /app
WORKDIR /app

# RUN pip install pipenv
# TODO: make venv
# RUN pipenv lock --keep-outdated --requirements > requirements.txt
RUN pip install -r requirements.txt
