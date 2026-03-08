#!/bin/bash

git pull

pushd js || exit
npm install
popd || exit

scripts/restart.sh "$@"

# Health check after deploy
echo "Waiting 5s for service to start..."
sleep 5
if curl -sf https://api.cometa.farm/contracts > /dev/null; then
    echo "Deploy OK — backend is responding"
else
    echo "DEPLOY FAILED — backend not responding!"
    exit 1
fi
