#!/bin/bash

CONTAINER_NAME="cometa-backend_mongodb_1"
MONGODB_PORT=27017

docker exec -i "$CONTAINER_NAME" sh -c "mongosh --port $MONGODB_PORT"
