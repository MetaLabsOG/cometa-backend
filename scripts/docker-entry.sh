#!/bin/bash

uvicorn app:app --host 0.0.0.0 --port 5001 # TODO: --workers "$WORKERS_NUM"
