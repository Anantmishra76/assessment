"""Isolated real-Redis/real-Celery acceptance run; never flushes shared Redis."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='assessment-live-') as directory:
        env = os.environ.copy()
        env.update(DJANGO_SETTINGS_MODULE='config.settings',
                   DATABASE_PATH=str(Path(directory) / 'live.sqlite3'),
                   RATE_NAMESPACE='verify-' + uuid.uuid4().hex)
        os.environ.update(env)
        import django
        django.setup()
        from django.core.management import call_command
        from mailqueue.models import DeadLetter, EmailJob
        from mailqueue.services import create_job
        from mailqueue.limiter import redis_client
        from mailqueue.tasks import dispatch_due
        client = redis_client()
        client.ping()
        call_command('migrate', verbosity=0)
        jobs = [create_job(recipient=f'user{i}@example.com', subject='Test', body='Test',
            scenario='transient_once' if i == 0 else 'permanent' if i == 1 else 'success')
            for i in range(500)]
        log_path = ROOT / 'evidence/live-worker.log'
        log_path.parent.mkdir(exist_ok=True)
        start = time.monotonic()
        worker = None
        try:
            with log_path.open('w', encoding='utf-8') as log:
                worker = subprocess.Popen([sys.executable, '-m', 'celery', '-A', 'config',
                    'worker', '--pool=solo', '--concurrency=1', '--loglevel=INFO',
                    '--without-gossip', '--without-mingle'], cwd=ROOT, env=env,
                    stdout=log, stderr=subprocess.STDOUT)
                dispatch_due.run()
                next_dispatch = time.monotonic() + 5
                while EmailJob.objects.exclude(status__in=['sent', 'dead']).exists():
                    if worker.poll() is not None:
                        raise AssertionError(f'Worker exited: {worker.returncode}; inspect {log_path}')
                    if time.monotonic() - start > 300:
                        raise AssertionError('500-job run exceeded 300 seconds')
                    if time.monotonic() >= next_dispatch:
                        dispatch_due.run()
                        next_dispatch = time.monotonic() + 5
                    threading.Event().wait(.25)
            records = [json.loads(value) for value in client.lrange(
                env['RATE_NAMESPACE'] + ':provider:audit', 0, -1)]
            timestamps = sorted(row['at'] for row in records)
            max_window, left = 0, 0
            for right, stamp in enumerate(timestamps):
                while timestamps[left] <= stamp - 60_000_000:
                    left += 1
                max_window = max(max_window, right - left + 1)
            jobs[0].refresh_from_db()
            assert EmailJob.objects.count() == 500
            assert EmailJob.objects.filter(status='sent').count() == 499
            assert EmailJob.objects.filter(status='dead').count() == 1
            assert DeadLetter.objects.count() == 1
            assert jobs[0].attempts == 2
            assert len(records) == 501
            assert max_window <= 200
            evidence = {'submitted': 500, 'sent': 499, 'dead_lettered': 1,
                'provider_attempts': len(records), 'max_attempts_in_rolling_60s': max_window,
                'intentional_transient_job_attempts': jobs[0].attempts,
                'elapsed_seconds': round(time.monotonic() - start, 2),
                'redis_version': client.info()['redis_version'],
                'worker_pool': 'solo', 'crash_test': 'separate test; not covered by this run',
                'audit': records}
            (ROOT / 'evidence/live-500-jobs.json').write_text(json.dumps(evidence, indent=2))
            print(json.dumps({k: v for k, v in evidence.items() if k != 'audit'}, indent=2))
        finally:
            if worker is not None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
            from django.db import connections
            connections.close_all()
            # Only this run's provider state is removed; do not FLUSHDB.
            keys = list(client.scan_iter(env['RATE_NAMESPACE'] + ':*'))
            if keys:
                client.delete(*keys)


if __name__ == '__main__':
    main()
