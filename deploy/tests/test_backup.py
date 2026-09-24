"""Exercise the real shell loop with failing PostgreSQL/filesystem commands."""
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'backup.sh'
COPY_SCRIPT = SCRIPT.with_name('copy-backup.sh')
PULL_SCRIPT = SCRIPT.with_name('pull-backup.sh')
HASH_COMMAND = 'sha256sum' if shutil.which('sha256sum') else 'shasum -a 256'


class BackupTests(unittest.TestCase):
    def test_mac_pull_verifies_before_promotion_and_marker(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            binaries = root / 'bin'
            local = root / 'off-host'
            source = root / 'newsintel-20260924-010000.dump'
            marker = root / 'marker'
            binaries.mkdir()
            local.mkdir()
            source.write_bytes(b'complete verified archive')
            target = local / source.name
            target.write_bytes(b'previous copy')
            expired = local / 'newsintel-20000101-000000.dump'
            expired.write_bytes(b'old verified copy')
            os.utime(expired, (1, 1))
            ssh = binaries / 'ssh'
            ssh.write_text('''#!/bin/sh
case "$*" in
  *'ls -t /backups/newsintel-'*) printf '/backups/%s\\n' "$(basename "$SOURCE_DUMP")" ;;
  *'sha256sum '*) shasum -a 256 "$SOURCE_DUMP" ;;
  *'stat -c %s '*) wc -c < "$SOURCE_DUMP" | tr -d ' ' ;;
  *'backup cat '*) if [ "${CORRUPT:-0}" = 1 ]; then printf bad; else cat "$SOURCE_DUMP"; fi ;;
  *'.offsite-last.partial'*) basename "$SOURCE_DUMP" > "$MARKER" ;;
  *) exit 2 ;;
esac
''')
            ssh.chmod(0o755)
            if not shutil.which('shasum'):
                shim = binaries / 'shasum'
                shim.write_text('#!/bin/sh\nshift 2\nexec sha256sum "$@"\n')
                shim.chmod(0o755)
            env = {**os.environ, 'PATH': f'{binaries}:{os.environ["PATH"]}',
                   'BACKUP_SOURCE_HOST': 'source-test', 'BACKUP_SOURCE_KEY': str(root / 'key'),
                   'BACKUP_LOCAL_DIR': str(local), 'SOURCE_DUMP': str(source),
                   'MARKER': str(marker)}
            failed = subprocess.run(['sh', str(PULL_SCRIPT)], env={**env, 'CORRUPT': '1'},
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
            self.assertEqual(target.read_bytes(), b'previous copy')
            self.assertFalse(marker.exists())
            self.assertTrue(expired.exists())
            self.assertEqual(list(local.glob('.*.partial')), [])

            succeeded = subprocess.run(['sh', str(PULL_SCRIPT)], env=env,
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(succeeded.returncode, 0, succeeded.stdout + succeeded.stderr)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(marker.read_text().strip(), source.name)
            self.assertFalse(expired.exists())

            again = subprocess.run(['sh', str(PULL_SCRIPT)], env={**env, 'CORRUPT': '1'},
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_offsite_copy_is_verified_before_replacing_the_last_good_copy(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            binaries = root / 'bin'
            remote = root / 'remote'
            binaries.mkdir()
            remote.mkdir()
            source = root / 'newsintel-20260924-010000.dump'
            source.write_bytes(b'verified archive')
            previous = remote / source.name
            previous.write_bytes(b'previous copy')
            commands = {
                'docker': '''#!/bin/sh
case " $* " in
  *'.offsite-last.partial'*) basename "$SOURCE_DUMP" > "$(dirname "$SOURCE_DUMP")/.offsite-last" ;;
  *' backup sh -c '*) printf '%s\\n' "$SOURCE_DUMP" ;;
  *' backup sha256sum '*) [ "${FAIL_HASH:-0}" != 1 ] && shasum -a 256 "$SOURCE_DUMP" ;;
  *' backup cat '*) if [ "${CORRUPT:-0}" = 1 ]; then printf bad; else cat "$SOURCE_DUMP"; fi ;;
  *) exit 2 ;;
esac
''',
                'ssh': '''#!/bin/sh
shift 5
sh -c "$1"
''',
                'sha256sum': f'''#!/bin/sh
{shutil.which('sha256sum') or '/usr/bin/shasum -a 256'} "$@"
''',
            }
            for name, body in commands.items():
                target = binaries / name
                target.write_text(body.replace('shasum -a 256 "$SOURCE_DUMP"',
                                               f'{HASH_COMMAND} "$SOURCE_DUMP"'))
                target.chmod(0o755)
            env = {**os.environ, 'PATH': f'{binaries}:{os.environ["PATH"]}',
                   'BACKUP_TARGET': 'backup-test', 'BACKUP_REMOTE_DIR': str(remote),
                   'SOURCE_DUMP': str(source)}
            no_hash = subprocess.run(['sh', str(COPY_SCRIPT)], env={**env, 'FAIL_HASH': '1'},
                                     capture_output=True, text=True, timeout=10)
            self.assertNotEqual(no_hash.returncode, 0)
            self.assertEqual(previous.read_bytes(), b'previous copy')
            self.assertFalse((root / '.offsite-last').exists())

            failed = subprocess.run(['sh', str(COPY_SCRIPT)], env={**env, 'CORRUPT': '1'},
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
            self.assertEqual(previous.read_bytes(), b'previous copy')
            self.assertFalse((remote / (source.name + '.partial')).exists())
            self.assertFalse((root / '.offsite-last').exists())

            succeeded = subprocess.run(['sh', str(COPY_SCRIPT)], env=env,
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(succeeded.returncode, 0, succeeded.stdout + succeeded.stderr)
            self.assertEqual(previous.read_bytes(), source.read_bytes())
            self.assertTrue((root / '.offsite-last').exists())

            again = subprocess.run(['sh', str(COPY_SCRIPT)], env={**env, 'CORRUPT': '1'},
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertIn('verified existing', again.stdout)
            self.assertEqual(previous.read_bytes(), source.read_bytes())

    def test_publication_and_retention_require_success(self):
        for failure in ('pg_dump', 'pg_restore', 'mv', ''):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                binaries = root / 'bin'
                backups = root / 'backups'
                binaries.mkdir()
                backups.mkdir()
                old = backups / 'newsintel-20000101-000000.dump'
                old.write_bytes(b'old backup')
                os.utime(old, (1, 1))
                commands = {
                    'pg_dump': 'for arg; do case "$arg" in --file=*) printf archive > "${arg#--file=}";; esac; done',
                    'pg_restore': 'exit 0',
                    'chgrp': 'exit 0',
                }
                if failure:
                    commands[failure] = 'exit 1'
                for name, body in commands.items():
                    target = binaries / name
                    target.write_text('#!/bin/sh\n' + body + '\n')
                    target.chmod(0o755)
                result = subprocess.run(
                    ['sh', str(SCRIPT)], capture_output=True, text=True, timeout=10,
                    env={**os.environ, 'PATH': f'{binaries}:{os.environ["PATH"]}',
                         'BACKUP_DIR': str(backups), 'POSTGRES_DB': 'newsintel',
                         'BACKUP_ONCE': '1'},
                )
                if failure:
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(list(backups.glob('*.dump')), [old])
                    self.assertEqual(list(backups.glob('*.partial')), [])
                    self.assertNotIn('wrote ', result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse(old.exists())
                    archives = list(backups.glob('*.dump'))
                    self.assertEqual(len(archives), 1)
                    self.assertEqual(archives[0].read_bytes(), b'archive')
                    self.assertEqual(archives[0].stat().st_mode & 0o777, 0o640)

    def test_a_startup_race_retries_before_the_daily_interval(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            binaries = root / 'bin'
            backups = root / 'backups'
            attempts = root / 'attempts'
            binaries.mkdir()
            backups.mkdir()
            commands = {
                'pg_dump': f'''count=$(cat {shlex.quote(str(attempts))} 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > {shlex.quote(str(attempts))}
[ "$count" -gt 1 ] || exit 1
for arg; do case "$arg" in --file=*) printf archive > "${{arg#--file=}}";; esac; done''',
                'pg_restore': 'exit 0',
                'chgrp': 'exit 0',
            }
            for name, body in commands.items():
                target = binaries / name
                target.write_text('#!/bin/sh\n' + body + '\n')
                target.chmod(0o755)

            process = subprocess.Popen(
                ['sh', str(SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
                env={**os.environ, 'PATH': f'{binaries}:{os.environ["PATH"]}',
                     'BACKUP_DIR': str(backups), 'POSTGRES_DB': 'newsintel',
                     'BACKUP_RETRY_SECONDS': '0', 'BACKUP_INTERVAL_SECONDS': '3600'},
            )
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not list(backups.glob('*.dump')):
                    time.sleep(0.02)
                self.assertTrue(list(backups.glob('*.dump')), 'the failed startup dump was not retried')
                self.assertGreaterEqual(int(attempts.read_text()), 2)
            finally:
                # Kill the shell and its sleep child; otherwise the child retains the
                # stdout pipe and communicate waits for the full hour on Linux.
                os.killpg(process.pid, signal.SIGTERM)
                output, _ = process.communicate(timeout=3)
            self.assertIn('FAILED: pg_dump did not complete', output)


if __name__ == '__main__':
    unittest.main()
