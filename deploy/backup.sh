#!/bin/sh
# Nightly Postgres dump, run by the `backup` service in docker-compose.prod.yml.
#
# Runs inside the SAME pgvector/pgvector:pg16 image the database uses. That is deliberate:
# pg_dump refuses to dump a server newer than itself, so a backup tool pinned to its own
# postgres version starts failing the day the database is upgraded - and it fails at 3am,
# into a log nobody reads. Reusing the image the server already runs makes that mismatch
# impossible and pulls no additional image onto a VPS with four other apps on it.
#
# The dump is custom format (-Fc): compressed, and restorable table-by-table with
# pg_restore, which is what you want at 4am when one table was truncated and the other
# nineteen are fine.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
RETRY_SECONDS="${BACKUP_RETRY_SECONDS:-300}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }

dump_once() {
    stamp=$(date -u +%Y%m%d-%H%M%S)
    final="${BACKUP_DIR}/${POSTGRES_DB}-${stamp}.dump"
    # Write to a .partial name and rename only after pg_dump AND the readback both succeed.
    # A dump interrupted by a restart or a full disk otherwise sits in the directory looking
    # exactly like a good one, and the retention sweep below happily deletes the real
    # backups around it. A rename is atomic on the same filesystem; a redirect is not.
    partial="${final}.partial"

    if ! pg_dump --format=custom --compress=6 --file="$partial"; then
        log "FAILED: pg_dump did not complete"
        rm -f "$partial"
        return 1
    fi

    # Read the data blocks too: --list only checks the archive's table of contents.
    if ! pg_restore --file=/dev/null "$partial"; then
        log "FAILED: dump is not a readable archive"
        rm -f "$partial"
        return 1
    fi

    # pg_dump creates mode 0600 files; the app's UID 10001 needs read access for monitoring.
    # The group is shared with the app image, while other local users get no dump access.
    if ! chgrp "${BACKUP_READ_GID:-10001}" "$partial" || ! chmod 640 "$partial"; then
        log "FAILED: cannot set backup permissions"
        rm -f "$partial"
        return 1
    fi
    # Explicit checks matter: this function is called in an `if`, disabling shell errexit.
    if ! mv "$partial" "$final"; then
        log "FAILED: cannot promote dump"
        rm -f "$partial"
        return 1
    fi
    log "wrote $(basename "$final") ($(du -h "$final" | cut -f1))"
}

sweep_old() {
    # Only ever deletes files this script's own naming produces, never the directory's
    # whole contents: a stray -delete on a mount that failed to attach is unrecoverable.
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "${POSTGRES_DB}-*.dump" \
        ! -name "$(basename "$final")" -mtime "+${RETENTION_DAYS}" -print -delete
    # A .partial older than a day is the residue of a killed container, not work in flight.
    find "$BACKUP_DIR" -maxdepth 1 -name "*.dump.partial" -mtime +1 -delete
}

mkdir -p "$BACKUP_DIR"
log "starting: every ${INTERVAL_SECONDS}s into ${BACKUP_DIR}, keeping ${RETENTION_DAYS} days"

while true; do
    result=0
    # Preserve the last usable backups through an outage, even beyond the retention window.
    if dump_once; then
        sweep_old || log "retention sweep failed"
    else
        result=1
        log "continuing after a failed dump; retrying in ${RETRY_SECONDS}s"
    fi
    [ "${BACKUP_ONCE:-0}" = 1 ] && exit "$result"
    if [ "$result" = 0 ]; then
        sleep "$INTERVAL_SECONDS"
    else
        # Compose startup ordering is not replayed when the Docker daemon restarts existing
        # containers. A host reboot can therefore start this service seconds before Postgres;
        # waiting a whole day after that race silently loses the night's backup.
        sleep "$RETRY_SECONDS"
    fi
done
