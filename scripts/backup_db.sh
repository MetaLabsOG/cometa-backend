#!/bin/bash

CONTAINER_NAME="cometa-backend_mongodb_1"
MONGODB_PORT=27017
DUMP_DIR="/srv/db_dump"

# Rotate backups: keep last 7 days
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="$DUMP_DIR/db.dump.$TIMESTAMP"

docker exec -i $CONTAINER_NAME sh -c "mongodump --archive --port $MONGODB_PORT" > "$DUMP_FILE"

if [ $? -eq 0 ]; then
    echo "Backup saved: $DUMP_FILE"
    # Remove backups older than 7 days
    find "$DUMP_DIR" -name "db.dump.*" -mtime +7 -delete
else
    echo "BACKUP FAILED!"
    rm -f "$DUMP_FILE"
    exit 1
fi
