#!/bin/bash

ENV=${1:-testnet}

scripts/stop.sh "$@" && scripts/start.sh "$@"
