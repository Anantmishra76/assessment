from datetime import timedelta
import random
from celery import shared_task
from django.db.models import F, Q
from django.utils import timezone
from redis.exceptions import RedisError
from . import limiter, provider
from .models import EmailJob
from .services import MAX_ATTEMPTS, backoff, claim, dead_letter, release

@shared_task(bind=True, max_retries=None, name='mailqueue.tasks.deliver')
def deliver(self, job_id):
    job = claim(job_id)
    if job is None:
        return 'duplicate-or-not-due'
    try:
        allowed, value = limiter.acquire()
    except RedisError as exc:
        release(job, 5, 'Redis unavailable; sending postponed')
        raise self.retry(exc=exc, countdown=5)
    if not allowed:
        delay = value / 1_000_000 + random.uniform(0.02, 0.2)
        release(job, delay, 'Rate limited')
        raise self.retry(countdown=delay)
    EmailJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(attempts=F('attempts') + 1)
    # Preserve the original fencing token if a newer worker has reclaimed this row.
    job.refresh_from_db(fields=['attempts'])
    try:
        receipt = provider.send(job)
    except provider.PermanentProviderError as exc:
        dead_letter(job, str(exc))
        return 'dead'
    except (provider.TemporaryProviderError, RedisError) as exc:
        if job.attempts >= MAX_ATTEMPTS:
            dead_letter(job, str(exc))
            return 'dead'
        delay = backoff(job.attempts) + random.uniform(0, 0.25)
        release(job, delay, str(exc))
        raise self.retry(exc=exc, countdown=delay)
    EmailJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(
        status='sent', provider_id=receipt, completed_at=timezone.now(),
        lease_until=None, lease_token=None, last_error='')
    return 'sent'

@shared_task(name='mailqueue.tasks.dispatch_due')
def dispatch_due():
    now = timezone.now()
    eligible = (Q(status='pending', next_attempt_at__lte=now) |
                Q(status='processing', lease_until__lte=now))
    stale = Q(published_at__isnull=True) | Q(published_at__lte=now - timedelta(seconds=90))
    ids = list(EmailJob.objects.filter(eligible).filter(stale).values_list('pk', flat=True)[:500])
    published = 0
    for job_id in ids:
        # Reserve before publish. Crash here is repaired after the publication lease.
        if EmailJob.objects.filter(pk=job_id).filter(eligible).filter(stale).update(published_at=now):
            try:
                deliver.delay(str(job_id))
            except Exception:
                EmailJob.objects.filter(pk=job_id, published_at=now).update(published_at=None)
                raise
            published += 1
    return published
