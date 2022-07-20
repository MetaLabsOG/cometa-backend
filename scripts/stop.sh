#!/bin/bash

ENV=${1:-testnet}

docker-compose -f "docker-compose.$ENV.yml" down
