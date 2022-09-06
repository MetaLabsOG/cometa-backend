#!/bin/bash

source .env
docker-compose --profile "$ALGO_NETWORK" up -d "$@"
