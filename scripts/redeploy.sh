#!/bin/bash

git pull

pushd js
npm install
popd

scripts/restart.sh
