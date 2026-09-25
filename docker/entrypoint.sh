#!/bin/sh
# Apply database migrations, then hand over to the container command.
set -e
dnd-pipeline init-db
exec "$@"
