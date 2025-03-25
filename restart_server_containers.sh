#!/bin/bash

# Container names
CONTAINERS=("image-server" "bottle-nginx")
RESTART_NEEDED=0

# Check each container
for CONTAINER in "${CONTAINERS[@]}"; do
    STATUS=$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)

    if [ "$STATUS" != "true" ]; then
        echo "Container '$CONTAINER' is not running."
        RESTART_NEEDED=1
    else
        echo "Container '$CONTAINER' is running."
    fi
done

# Restart if needed
if [ "$RESTART_NEEDED" -eq 1 ]; then
    echo "Restarting containers with docker compose..."
    docker compose down
    docker compose up -d
else
    echo "All containers are healthy. No restart needed."
fi
