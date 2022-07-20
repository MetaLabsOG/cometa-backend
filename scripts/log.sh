#!/bin/bash

ENV=${1:-testnet}

docker logs "cometa-backend_${ENV}_1" -f
