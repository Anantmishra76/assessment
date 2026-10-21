import heapq
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from redis.exceptions import ConnectionError

from mailqueue import limiter, provider
from mailqueue.models import DeadLetter, EmailJob
from mailqueue.services import backoff, claim, create_job, release, dead_letter
from mailqueue.tasks import deliver, dispatch_due


def make_job(scenario='success'):
    return create_job(recipient='user@example.com', subject='Order', body='Confirmed', scenario=scenario)


def retry_signal(**kwargs):
    raise Retry(when=kwargs['countdown'])


def test_atomic_limit_under_concurrent_clients(fake_redis):
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: limiter.acquire(), range(500)))
    assert sum(allowed for allowed, _ in results) == 200
    assert all(value > 0 for allowed, value in results if not allowed)


@pytest.mark.django_db
def test_500_jobs_retry_and_rolling_window(fake_redis, monkeypatch):
    # Virtual time speeds up the scheduler; actual production Lua executes in fakeredis.
    # The separate integration test exercises the same code with real Redis/Celery.
    clock = [1_800_000_000.0]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    monkeypatch.setattr(timezone, 'now', lambda: datetime.fromtimestamp(clock[0], dt_timezone.utc))
    monkeypatch.setattr(deliver, 'retry', retry_signal)
    jobs = [make_job('transient_once' if i == 0 else 'success') for i in range(500)]
    schedule = [(clock[0], i, str(job.pk)) for i, job in enumerate(jobs)]
    heapq.heapify(schedule)
    sequence = 500
    retries = 0
    while schedule:
        due, _, job_id = heapq.heappop(schedule)
        clock[0] = max(clock[0], due)
        try:
            deliver.run(job_id)
        except Retry as exc:
            retries += 1
            sequence += 1
            heapq.heappush(schedule, (clock[0] + float(exc.when) + .001, sequence, job_id))
        assert sequence < 10000, 'Queue did not converge'
    assert EmailJob.objects.count() == 500
    assert EmailJob.objects.filter(status='sent').count() == 500
    assert retries > 0
    jobs[0].refresh_from_db()
    assert jobs[0].attempts == 2
    records = [json.loads(value) for value in fake_redis.lrange(
        settings.RATE_NAMESPACE + ':provider:audit', 0, -1)]
    assert len(records) == 501
    timestamps = sorted(record['at'] for record in records)
    left = 0
    for right, timestamp in enumerate(timestamps):
        while timestamps[left] <= timestamp - 60_000_000:
            left += 1
        assert right - left + 1 <= 200


@pytest.mark.django_db
def test_permanent_failure_goes_to_dead_letter(fake_redis):
    job = make_job('permanent')
    assert deliver.run(str(job.pk)) == 'dead'
    job.refresh_from_db()
    assert job.status == 'dead'
    assert DeadLetter.objects.get(job=job).reason == 'invalid recipient'


@pytest.mark.django_db
def test_exhausted_transient_retry_goes_to_dead_letter(fake_redis, monkeypatch):
    job = make_job('always_transient')
    monkeypatch.setattr(deliver, 'retry', retry_signal)
    for attempt in range(1, 6):
        EmailJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        if attempt < 5:
            with pytest.raises(Retry) as retry:
                deliver.run(str(job.pk))
            assert backoff(attempt) <= retry.value.when <= backoff(attempt) + .25
        else:
            assert deliver.run(str(job.pk)) == 'dead'
    assert DeadLetter.objects.filter(job=job).exists()


@pytest.mark.django_db
def test_redis_outage_fails_closed(fake_redis, monkeypatch):
    job = make_job()
    monkeypatch.setattr(limiter, 'acquire', lambda: (_ for _ in ()).throw(ConnectionError()))
    monkeypatch.setattr(deliver, 'retry', retry_signal)
    with pytest.raises(Retry):
        deliver.run(str(job.pk))
    job.refresh_from_db()
    assert job.status == 'pending'
    assert job.attempts == 0
    assert fake_redis.llen(settings.RATE_NAMESPACE + ':provider:audit') == 0


@pytest.mark.django_db
def test_crash_after_send_recovers_without_duplicate_effect(fake_redis):
    job = make_job()
    claimed = claim(job.pk)
    first_receipt = provider.send(claimed)
    # Simulate lost process before its successful database update; lease expires.
    EmailJob.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert deliver.run(str(job.pk)) == 'sent'
    job.refresh_from_db()
    assert job.provider_id == first_receipt
    assert fake_redis.llen(settings.RATE_NAMESPACE + ':provider:audit') == 1
    assert deliver.run(str(job.pk)) == 'duplicate-or-not-due'


@pytest.mark.django_db
def test_database_outbox_survives_publish_failure(monkeypatch):
    job = make_job()
    with patch.object(deliver, 'delay', side_effect=ConnectionError()):
        with pytest.raises(ConnectionError):
            dispatch_due.run()
    job.refresh_from_db()
    assert job.status == 'pending' and job.published_at is None
    with patch.object(deliver, 'delay') as publish:
        assert dispatch_due.run() == 1
        publish.assert_called_once_with(str(job.pk))


@pytest.mark.django_db
def test_live_lease_prevents_second_claim_and_invalid_email():
    job = make_job()
    assert claim(job.pk) is not None
    assert claim(job.pk) is None
    with pytest.raises(ValidationError):
        create_job(recipient='invalid', subject='x', body='x')


@pytest.mark.django_db
def test_stale_lease_cannot_change_new_owner():
    job = make_job()
    stale = claim(job.pk)
    EmailJob.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    current = claim(job.pk)
    assert current.lease_token != stale.lease_token
    release(stale, 5, 'stale')
    dead_letter(stale, 'stale')
    job.refresh_from_db()
    assert job.status == 'processing'
    assert job.lease_token == current.lease_token
    assert not DeadLetter.objects.exists()
