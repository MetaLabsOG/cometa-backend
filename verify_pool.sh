#!/bin/bash

source .env

set -x

API_URL="https://api.cometa.farm"
POOL_ID=$1

# Check if '-l' argument is provided
if [ "$1" == "-l" ]; then
  # Extract the ID from the provided link
  POOL_ID=$(echo $2 | awk -F'/' '{print $NF}')
fi

# not moved password to a variable because quotes in bash work weird
curl -X 'PATCH' "${API_URL}/pools/verify?pool_id=${POOL_ID}&password=%24C0metaT0TheM000n%24" -H 'accept: application/json'
