# Full Stack Developer Assessment

A local Django assessment covering an order-summary regression, a durable Celery email queue, and two architecture reviews. The email provider is simulated: no real messages or credentials are used.

## Start locally

Prerequisite: Docker Desktop with Linux containers and Docker Compose v2. From this directory:

```sh
docker compose up --build -d
docker compose logs init
docker compose exec web python manage.py check
```

Migrations run automatically before the web, worker, and beat services start. Open http://localhost:8000/silk/ after generating evidence below. The root URL intentionally has no page. Image downloads depend on your connection; after downloading images, startup should take well under five minutes. This is an assessment server, not a production deployment.

## Section 1

```sh
docker compose exec web python manage.py profile_orders
```

This seeds 250 orders, authenticates a local Django test client, executes both real endpoints through Silk middleware, and exports `evidence/silk-profile.json` on your host. Browse `/silk/requests/` for the two captured requests. The export includes actual SQL and timing data, not a fabricated screenshot.

Endpoints are authenticated GET requests:

- `/api/orders/summary/broken/`: intentionally retained reproduction.
- `/api/orders/summary/`: fixed implementation.

The evidence command authenticates automatically; no shared password is needed. It replaces only orders belonging to `assessment-demo`.

## Section 2

```sh
docker compose exec web python manage.py submit_jobs --count 500
docker compose logs -f worker
docker compose exec redis redis-cli -n 0 LLEN assessment
docker compose exec redis redis-cli -n 1 ZCARD assessment:provider:window
docker compose exec redis redis-cli -n 1 LLEN assessment:provider:audit
```

First job: one temporary failure; second job: permanent failure. All others succeed. Queue length excludes reserved/delayed tasks, so it is not an authoritative completion count. Database status and the provider audit are authoritative for the demonstration:

```sh
docker compose exec web python manage.py shell -c "from mailqueue.models import EmailJob; from django.db.models import Count; print(list(EmailJob.objects.values('status').annotate(count=Count('id'))))"
```

No public job-submission endpoint is needed by the brief. The management command validates inputs and supplies a reproducible workload. `create_job()` is the reusable application service.

## Tests

Fast tests run without a Redis service:

```sh
docker compose exec web python -m pytest -q
```

Real Redis and real worker acceptance test, in an isolated temporary database and unique queue namespace:

```sh
docker compose exec web python -m pytest -m integration -q -s
```

The integration harness starts its own Celery worker and checks 500 terminal jobs, 499 sent plus one dead letter, 501 provider attempts, a successful retry, and every rolling 60-second window. A second integration test force-kills a worker after provider acceptance and checks recovery without duplicate effects. Reports are exported to `evidence/live-500-jobs.json` and `evidence/live-crash.json`, with worker logs. Together these take roughly 4–5 minutes; startup time and execution time are separate. They never flush Redis. Default tests exclude integration tests explicitly.

See `evidence/VERIFICATION.md` for the actual verification environment and results. The fast suite uses fakeredis with real Lua execution and virtual time; it is not presented as a real broker test.

## Without Docker

Python 3.13 or 3.14 and a running Redis server are needed for the complete system. On Windows, use Docker/WSL for a production-like Celery prefork worker; native `--pool=solo` is only a development fallback.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python -m pytest -q
python manage.py profile_orders
python manage.py runserver
```

In separate terminals with the same virtual environment and environment variables:

```sh
celery -A config worker --loglevel=INFO --concurrency=1
celery -A config beat --loglevel=INFO
```

Default Redis URLs use localhost port 6379. Set `REDIS_URL` and `RATE_REDIS_URL` to override. `.env.example` documents configuration; it is not automatically loaded by Django. Compose already sets its own environment. A fully resolved dependency snapshot is included as `requirements-lock.txt`.

## Optional recording walkthrough

1. Start the Compose services from a fresh terminal.
2. Submit at least 100 jobs; use 500 to demonstrate throttling beyond the first window.
3. Display the Redis commands and worker logs above.
4. Show the intentional temporary failure and its delayed retry.
5. Display the integration report's rolling-window maximum and final database counts.
6. Explain late acknowledgements, idempotency, and the outbox recovery process.

The optional 5–10 minute recording has not been created. Add your Loom link here if you choose to record it.

## Submission

Read `ANSWERS.md` and `DESIGN.md`, understand the trade-offs, and share this directory as a GitHub or GitLab repository with the reviewer. Keep evidence tracked; exclude `.env`, databases, virtual environments, and credentials. Git hosting and optional recording are separate from the local deliverable.

```sh
git status
git add .
git commit -m "Complete Django systems assessment"
# Add your own GitHub/GitLab remote, then push your branch.
```

Stop services with `docker compose down`. Named volumes retain state. The application uses SQLite and one worker for easy local setup; the design explains the production migration path.
