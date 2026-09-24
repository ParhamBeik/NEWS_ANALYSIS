#!/bin/sh
# Run on the VPS host after the backup service has published a verified dump.
# BACKUP_TARGET is an SSH alias or user@host with a pinned host key; no key lives here.
set -eu

: "${BACKUP_TARGET:?set BACKUP_TARGET to the existing SSH backup destination}"
: "${BACKUP_REMOTE_DIR:?set BACKUP_REMOTE_DIR to an absolute destination directory}"
case "$BACKUP_REMOTE_DIR" in
    /*) ;;
    *) echo 'BACKUP_REMOTE_DIR must be absolute' >&2; exit 1 ;;
esac
case "$BACKUP_REMOTE_DIR" in
    *[!a-zA-Z0-9_./-]*) echo 'BACKUP_REMOTE_DIR has unsupported characters' >&2; exit 1 ;;
esac

cd "$(dirname "$0")"
compose() { docker compose -f docker-compose.prod.yml "$@"; }
archive=$(compose exec -T backup sh -c 'ls -t /backups/*.dump 2>/dev/null | head -n 1')
[ -n "$archive" ] || { echo 'no verified database dump found' >&2; exit 1; }
name=${archive##*/}
case "$name" in
    *[!a-zA-Z0-9_.-]*|'') echo 'unexpected dump filename' >&2; exit 1 ;;
esac

local_hash=$(compose exec -T backup sha256sum "$archive" | cut -d ' ' -f 1)
[ "${#local_hash}" -eq 64 ] || { echo 'could not hash local dump' >&2; exit 1; }
remote="${BACKUP_REMOTE_DIR}/${name}"
record_copy() {
    compose exec -T backup sh -c '
        printf "%s\n" "$1" > /backups/.offsite-last.partial &&
        mv -f /backups/.offsite-last.partial /backups/.offsite-last
    ' sh "$name"
}
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BACKUP_TARGET" \
    "mkdir -p -- '$BACKUP_REMOTE_DIR'"
existing_hash=$(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BACKUP_TARGET" \
    "sha256sum '$remote'" 2>/dev/null | cut -d ' ' -f 1 || true)
if [ "$local_hash" = "$existing_hash" ]; then
    record_copy
    echo "verified existing off-host copy $name"
    exit 0
fi
compose exec -T backup cat "$archive" | ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
    "$BACKUP_TARGET" "cat > '$remote.partial'"
remote_hash=$(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BACKUP_TARGET" \
    "sha256sum '$remote.partial'" | cut -d ' ' -f 1)
if [ "$local_hash" != "$remote_hash" ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BACKUP_TARGET" \
        "rm -f -- '$remote.partial'"
    echo 'off-host copy checksum mismatch; previous copy preserved' >&2
    exit 1
fi
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BACKUP_TARGET" \
    "mv -f -- '$remote.partial' '$remote'"
record_copy
echo "copied and verified $name"
