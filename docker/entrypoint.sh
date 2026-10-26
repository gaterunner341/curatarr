#!/bin/sh
# Run Curatarr as PUID:PGID (like linuxserver.io images) so files in /config
# are owned by the host user.
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

if [ "$(id -u)" = "0" ]; then
    mkdir -p "${CURATARR_CONFIG_DIR:-/config}"
    chown -R "$PUID:$PGID" "${CURATARR_CONFIG_DIR:-/config}"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
