"""Force-kill an actual worker after provider acceptance and verify outbox recovery."""
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
    with tempfile.TemporaryDirectory(prefix='assessment-crash-') as directory:
        gate = Path(directory) / 'accepted.txt'
        env = os.environ.copy()
        env.update(DJANGO_SETTINGS_MODULE='config.settings',
            DATABASE_PATH=str(Path(directory) / 'crash.sqlite3'),
            RATE_NAMESPACE='crash-' + uuid.uuid4().hex, CRASH_GATE_FILE=str(gate))
        os.environ.update(env)
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections
        from mailqueue.limiter import redis_client
        from mailqueue.models import EmailJob
        from mailqueue.services import create_job
        from mailqueue.tasks import dispatch_due
        client = redis_client()
        client.ping()
        call_command('migrate', verbosity=0)
        job = create_job(recipient='crash@example.com', subject='Crash probe', body='Probe')
        log = (ROOT / 'evidence/crash-worker.log').open('w', encoding='utf-8')
        workers = []
        started = time.monotonic()

        def start(app):
            worker = subprocess.Popen([sys.executable, '-m', 'celery', '-A', app,
                'worker', '--pool=solo', '--concurrency=1', '--loglevel=INFO',
                '--without-gossip', '--without-mingle'], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT)
            workers.append(worker)
            return worker

        try:
            worker = start('tests.crash_app')
            dispatch_due.run()
            while not gate.exists():
                assert worker.poll() is None, 'Crash-gate worker exited unexpectedly'
                assert time.monotonic() - started < 30, 'Provider acceptance gate not reached'
                threading.Event().wait(.1)
            job.refresh_from_db()
            assert job.status == 'processing'
            assert client.get(env['RATE_NAMESPACE'] + f':provider:receipt:{job.pk}')
            worker.kill()  # SIGKILL on POSIX; TerminateProcess on Windows.
            worker.wait(timeout=10)
            start('config')
            while True:
                dispatch_due.run()
                job.refresh_from_db()
                if job.status == 'sent':
                    break
                assert time.monotonic() - started < 200, 'Recovery exceeded 200 seconds'
                threading.Event().wait(.5)
            attempts = client.llen(env['RATE_NAMESPACE'] + ':provider:audit')
            assert attempts == 1, 'Provider effect was duplicated'
            assert job.attempts == 2, 'Task did not re-execute after the crash'
            result = {'worker_force_killed': True, 'platform': sys.platform,
                'termination': 'SIGKILL' if os.name == 'posix' else 'Windows TerminateProcess',
                'status': job.status, 'task_provider_entries': job.attempts,
                'provider_effects': attempts,
                'elapsed_seconds': round(time.monotonic() - started, 2),
                'note': 'Outbox/lease recovery tested; solo pool does not test prefork child rejection'}
            (ROOT / 'evidence/live-crash.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.terminate()
                    try:
                        worker.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait()
            log.close()
            connections.close_all()
            keys = list(client.scan_iter(env['RATE_NAMESPACE'] + ':*'))
            if keys:
                client.delete(*keys)


if __name__ == '__main__':
    main()
