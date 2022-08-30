#!/bin/bash

# TODO: use MGOB when really sensitive data is there

CONTAINER_NAME="cometa-backend_mongodb_1"
MONGODB_PORT=27017

DUMP_DIR="/srv/db_dump"

# TODO: make more dumps
mv "$DUMP_DIR/db.dump.new" "$DUMP_DIR/db.dump.old"

docker exec -i $CONTAINER_NAME sh -c "mongodump --archive --port $MONGODB_PORT" > "$DUMP_DIR/db.dump.new"
