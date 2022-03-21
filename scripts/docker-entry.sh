#!/bin/bash

uvicorn src.app:app --host 0.0.0.0 --port 5000 # TODO: --workers "$WORKERS_NUM"
