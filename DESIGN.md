# Rate Limited Async Email Queue

## Requirements and interpretation

One email-provider account admits at most 200 provider attempts in a rolling 60-second window across all workers. Retries consume capacity. A burst of 2,000 jobs is durably accepted without attempting to deliver it immediately. All jobs have an explicit terminal state: sent or dead-lettered. The provider is a deterministic fake with external idempotency state in Redis; the task/limiter boundary is the same one a real adapter would use.

The prompt initially asks to compare queue frameworks but later explicitly requires Celery with Redis. I therefore compare the alternatives and implement Celery. Although fixed windows are also listed, I choose the stricter sliding-window interpretation. No `time.sleep()` appears in the queue or limiter.

## Architecture choice

| Option | Advantages | Costs and decision |
| --- | --- | --- |
| Celery + Redis | Established task delivery, retry countdowns, process pools, worker tooling and late acknowledgements | Requires broker configuration and separate workers; Redis durability needs explicit configuration. Chosen because it is required and provides the needed lifecycle. |
| Django Q / Q2 | Django-oriented administration and scheduled work; approachable for small teams | Would still require a shared atomic limiter and crash/idempotency reasoning. Q2 is the maintained continuation; choosing it would not meet the explicit Celery requirement. |
| Custom queue | Complete control over reservation and admission | Requires implementing acknowledgement, redelivery, retry scheduling, shutdown and observability correctly. Too much bespoke infrastructure for this scope. |

`EmailJob` is both the durable business record and an outbox. Creating it does not require an available broker. Beat runs `dispatch_due` every five seconds, publishing due records. A publication timestamp is a 90-second lease: a crash between recording publication and broker delivery cannot strand the job forever. Publication can happen twice; execution is designed for at-least-once delivery.

Task execution claims a row through a conditional database `UPDATE`, setting a UUID lease token and 45-second lease. Duplicate deliveries cannot claim the same live lease. Final updates match that token, preventing a stale worker from overwriting the new owner's state. No database transaction is held across Redis or provider I/O. SQLite is sufficient for the single-worker local demonstration; PostgreSQL is the recommended production store for concurrency and operational resilience.

## Atomic sliding window

`limiter.lua` uses one sorted set per provider account, shared across workers. Within one Lua execution it:

1. Reads Redis `TIME` in microseconds, avoiding worker clock disagreement.
2. Removes admissions at or before `now - 61 seconds` with `ZREMRANGEBYSCORE`. The extra second conservatively covers normal local admission-to-provider scheduling delay.
3. Uses `ZCARD` to count the remaining admissions.
4. If full, returns the delay until the oldest admission leaves the window.
5. Otherwise inserts a unique attempt UUID with `ZADD` and sets an idle TTL.

The admission interval is `(now - 61s, now]`, a deliberately stricter limit than 200 per 60 seconds. The test still checks provider attempts in every 60-second window. Lua serializes the check and insertion so concurrent workers cannot both claim the last slot. An ordinary pipeline does not by itself guarantee this conditional atomicity. Unique members avoid collapsing attempts that share a timestamp. The working set is bounded at 200 entries per account. Cleanup and inserts cost approximately O(log N), plus removed entries. The safety margin sacrifices about 1.6% of maximum steady-state throughput.

A fixed-window counter is simpler but can allow 200 sends just before a boundary and another 200 immediately after. A correctly implemented token bucket allows configurable bursts and sustained throughput, but a bucket of 200 replenished at 200/minute does not enforce the same strict rolling-window bound. `DECR` plus TTL alone is not a complete continuously replenishing token bucket.

The limiter controls provider-call admission, not the arrival timestamp inside a remote provider. A process paused between admission and network I/O, or network jitter, can shift arrival times. The one-second safety margin covers the measured local workload but cannot prove safety under unbounded process pauses. A real provider contract may require a larger margin or a centrally paced dispatcher. The submitted integration test also checks the fake provider's observed attempt timestamps; that measurement is evidence for this workload, not a proof about arbitrary network pauses. An initial real-worker test exposed this admission/arrival boundary effect; the stricter window is an intentional correction, not a change to the test's 60-second assertion.

## Retry and failure policy

Rate denial releases the database lease and uses Celery `retry(countdown=...)`. It does not spend a provider-failure attempt. Provider failures are recorded separately in `EmailJob.attempts`. Temporary failures receive 2, 4, 8, and 16 second exponential delays with small random jitter. The fifth failed provider attempt becomes a dead letter. Permanent failures go directly to `DeadLetter`, created in the same database transaction as the terminal state update. This explicit application table is the dead-letter store; it is not claimed to be a Redis-native DLQ.

The task's `max_retries=None` allows indefinite quota waiting or Redis-outage recovery. The database bounds actual provider failures. Unexpected exceptions leave a recoverable processing lease and are visible in worker logs. A persistently unexpected programming error may repeatedly recover; production should alert and quarantine these separately rather than silently dropping jobs.

Redis failures fail closed: no available admission means no provider call. If publication fails, the durable outbox remains pending. Redis uses AOF with `appendfsync always`, a named volume, and `noeviction` in Compose. These improve local durability but do not guarantee availability or survive every disk/corruption failure. Loss of limiter history requires pausing sending for a full window before resuming. The project does not implement automated failover; a database backup and operational recovery procedure remain necessary.

## Worker termination and delivery semantics

`task_acks_late=True` acknowledges after task execution. `task_reject_on_worker_lost=True` is also required: a surviving Celery parent can otherwise acknowledge a task whose child was killed. A parent observing child loss can reject/requeue promptly. If the entire worker dies, Redis transport visibility-timeout recovery makes unacknowledged messages eligible for redelivery, with restoration timing depending on transport polling. All relevant visibility-timeout settings are 120 seconds. A 30-second hard task limit and at most about 60 seconds of quota countdown fit below it. Prefetch is one to avoid hoarding work. The database lease/outbox recovery provides another route if transport redelivery is delayed.

Exactly-once external email delivery is not promised. If the provider accepts a request and the worker dies before updating Django, the retry supplies the same job UUID as provider idempotency key. The fake provider atomically stores the receipt and deduplicates later calls. A real provider must support equivalent durable idempotency. A database `sent` flag alone cannot close the external side-effect crash window. If a provider lacks idempotency, this design can produce duplicate emails; reconciliation or a different provider is needed.

## Testing and limits

Fast tests execute the actual Lua via fakeredis, including 500 concurrent admission requests, rolling-window simulation of 500 jobs, retries, permanent and exhausted failures, broker failure, live leases, and the send-before-commit crash boundary. ORM tests assert constant query count and matching results.

`tools/verify_live.py` independently uses a real Redis service and a separate Celery worker with a temporary database and unique queue. It persists 500 jobs, submits them through the broker, and checks every provider audit timestamp. A deliberate permanent failure is accounted for as one dead letter, not counted as a lost job. `tools/verify_crash.py` separately force-kills a worker after provider acceptance and before database completion, then checks recovery and idempotency.

Native Windows verification uses the solo pool. Linux Compose uses the prefork pool and a pinned Redis 7.4 image. Results identify the environment actually exercised; a Windows solo result does not establish Linux prefork-specific behavior. The Docker manifest is supplied for the reviewer to reproduce that environment.

## Production improvements

Use PostgreSQL, supervised workers and beat, provider HTTP timeouts shorter than the job lease, structured metrics for outbox age/retries/DLQ count, TLS/authenticated Redis on a private network, and a global provider-account key shared by every sending service. Protect profiler output and remove Silk outside development. Route OTP separately only if all queues still share the same account-wide limiter. Do not introduce per-worker built-in Celery rate limits as a replacement for the shared limiter.

## References

- [Celery task configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html)
- [Celery Redis visibility timeout](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
- [Redis Lua atomic execution](https://redis.io/docs/latest/develop/programmability/eval-intro/)
