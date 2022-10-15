#!/bin/bash

source .env
if [ "$ALGO_NETWORK" = "testnet" ];
then
  PREF="-testnet"
fi

docker logs "cometa-backend${PREF}_app_1" -f $@
