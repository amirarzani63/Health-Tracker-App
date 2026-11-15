#!/bin/sh
set -e
# Persistent disks are often mounted owned by root; give the app user write access, then drop root.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "${HEALTH_DATA_DIR:-/data}"
  chown -R appuser "${HEALTH_DATA_DIR:-/data}"
  exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi
exec "$@"
