#!/bin/bash

git pull

pushd js || exit
npm install
popd || exit

scripts/restart.sh "$@"
