#!/bin/bash

uvicorn app:app --host 0.0.0.0 --port 5000 --ssl-keyfile ./key.pem --ssl-certfile ./cert.pem # TODO: --workers "$WORKERS_NUM"
