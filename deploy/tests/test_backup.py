"""Exercise the real shell loop with failing PostgreSQL/filesystem commands."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'backup.sh'


class BackupTests(unittest.TestCase):
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
                text=True,
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
                process.terminate()
                output, _ = process.communicate(timeout=3)
            self.assertIn('FAILED: pg_dump did not complete', output)


if __name__ == '__main__':
    unittest.main()
