#!/bin/sh
# Run on the FileVault-enabled Mac. Pull a published VPS dump without exposing Mac SSH.
set -eu
umask 077

source_host=${BACKUP_SOURCE_HOST:-root@45.139.10.12}
source_key=${BACKUP_SOURCE_KEY:-$HOME/.ssh/vps_45_139_10_12}
local_dir=${BACKUP_LOCAL_DIR:-$HOME/Backups/NEWS_ANALYSIS}
mkdir -p "$local_dir"
chmod 700 "$local_dir"

ssh_source() {
    ssh -i "$source_key" -o IdentitiesOnly=yes -o BatchMode=yes \
        -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "$source_host" "$1"
}
compose='cd /opt/apps/news-intel/deploy && docker compose -f docker-compose.prod.yml'
archive=$(ssh_source "$compose exec -T backup sh -c 'ls -t /backups/newsintel-*.dump 2>/dev/null | head -n 1'")
case "$archive" in
    /backups/newsintel-*.dump) ;;
    *) echo 'no published database dump found' >&2; exit 1 ;;
esac
name=${archive##*/}
case "$name" in
    *[!a-zA-Z0-9_.-]*) echo 'unexpected dump filename' >&2; exit 1 ;;
esac
remote_hash=$(ssh_source "$compose exec -T backup sha256sum '$archive'" | cut -d ' ' -f 1)
case "$remote_hash" in
    *[!a-fA-F0-9]*) echo 'invalid VPS checksum' >&2; exit 1 ;;
esac
[ "${#remote_hash}" -eq 64 ] || { echo 'invalid VPS checksum' >&2; exit 1; }

local_hash() { shasum -a 256 "$1" | cut -d ' ' -f 1; }
target=$local_dir/$name
if [ ! -f "$target" ] || [ "$(local_hash "$target")" != "$remote_hash" ]; then
    available_kb=$(df -Pk "$local_dir" | awk 'END {print $4}')
    archive_bytes=$(ssh_source "$compose exec -T backup stat -c %s '$archive'")
    case "$archive_bytes" in *[!0-9]*|'') echo 'invalid archive size' >&2; exit 1 ;; esac
    [ "$available_kb" -gt "$((archive_bytes / 1024 + 1048576))" ] || {
        echo 'less than 1 GiB of disk headroom after backup' >&2; exit 1;
    }
    partial=$(mktemp "$local_dir/.$name.XXXXXX")
    trap 'rm -f "$partial"' EXIT HUP INT TERM
    ssh_source "$compose exec -T backup cat '$archive'" > "$partial"
    [ "$(local_hash "$partial")" = "$remote_hash" ] || {
        echo 'backup checksum mismatch; previous copy preserved' >&2; exit 1;
    }
    mv -f "$partial" "$target"
    trap - EXIT HUP INT TERM
fi

# The marker lives on the VPS backup volume and is written only after local verification.
ssh_source "$compose exec -T backup sh -c 'printf \"%s\\n\" \"\$1\" > /backups/.offsite-last.partial && mv -f /backups/.offsite-last.partial /backups/.offsite-last' sh '$name'"
find "$local_dir" -maxdepth 1 -type f -name 'newsintel-*.dump' -mtime +30 -delete
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) verified off-host copy $name"
