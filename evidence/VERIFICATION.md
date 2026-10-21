# Verification Results

Verified on 21 October 2026 on Windows with Python 3.14.2, Django 5.2.18, Celery 5.6.3 and Redis 8.10.2. Exact Python dependencies are recorded in `requirements-lock.txt`.

## Section 1

The same 250 orders with 750 items were requested through actual django-silk middleware:

| Endpoint | Silk SQL count | Measured request time |
| --- | ---: | ---: |
| Broken summary | 253 | 414.654 ms |
| Fixed summary | 3 | 15.910 ms |

Counts include two authentication/session queries. Business-query tests independently assert 251 versus one. Timings are one local sample with profiler overhead, not production p95 benchmarks. Full SQL and request identifiers are in `silk-profile.json`.

## Fast tests

`python -m pytest -q`: **12 passed, 2 integration tests deselected**. See `unit-tests.txt`.

`python manage.py check`: no issues. `python manage.py makemigrations --check --dry-run`: no changes detected. `python -m pip check`: no broken requirements. Migrations were applied to a fresh database, including Silk tables.

The fast tests exercise real Lua through fakeredis, not an actual Redis broker. Their 500-job scheduler uses virtual time. This is why the independent live tests below exist.

## Real broker and worker

`live-500-jobs.json` records a real Redis and a separate Celery worker process, not eager mode:

- Submitted: 500 jobs.
- Sent: 499.
- Dead-lettered: one intentional permanent failure.
- Provider attempts: 501, including one intentional temporary failure.
- Temporary-failure job: succeeded on its second attempt.
- Largest rolling 60-second window: 200 attempts.
- Elapsed: 131.64 seconds.

The fake provider's observed timestamps, including failures, are retained in the report. An initial real-worker run revealed that provider-call timestamps can differ slightly from admission timestamps at the window boundary. The production limiter was tightened to a 61-second admission window, while the acceptance assertion remains 60 seconds. This preserves a conservative margin at a small throughput cost. It does not prove correctness under arbitrary process/network delays; see `DESIGN.md`.

## Forced worker termination

`live-crash.json` records an actual worker process terminated after the fake provider had accepted the job but before the Django completion update. A replacement worker and the normal outbox dispatcher recovered it after 90.74 seconds, without shortening the configured recovery leases. The task entered the provider adapter twice, but the provider audit recorded only one effect because the same idempotency key returned the original receipt. Final database status was `sent`.

The two real-worker acceptance tests passed in 228.28 seconds in total. The worker termination was Windows `TerminateProcess`; on POSIX the same harness uses `subprocess.kill()` to send SIGKILL. The test exercises whole-worker/outbox recovery rather than a surviving prefork parent's child-rejection behavior.

## Environment limits

Docker and WSL were unavailable on the authoring computer. Live verification therefore used a workspace-local [Redis Windows port](https://github.com/redis-windows/redis-windows/releases/tag/8.10.2) and Celery's solo pool. The downloaded archive SHA-256 matched its GitHub release digest: `7c8cebd50347eaa1d9e784da842ed47a4f33394637835531d6614777b950ee85`.

This is actual Redis server execution, but it does not verify the supplied Linux Docker image, Compose startup, prefork child-loss semantics, or a literal POSIX SIGKILL. The Compose setup is supplied for reproduction on Linux/Docker. The optional screen recording and remote Git repository publication are not included.
