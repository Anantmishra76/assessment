from datetime import timedelta
import uuid
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import EmailJob, DeadLetter

MAX_ATTEMPTS = 5
LEASE_SECONDS = 45

def create_job(**fields):
    job = EmailJob(**fields)
    job.full_clean()
    job.save()
    # The database row IS the outbox. Beat publishes it, even after broker failure.
    return job

def claim(job_id):
    now = timezone.now()
    token = uuid.uuid4()
    eligible = (Q(status='pending', next_attempt_at__lte=now) |
                Q(status='processing', lease_until__lte=now))
    changed = EmailJob.objects.filter(pk=job_id).filter(eligible).update(
        status='processing', lease_token=token,
        lease_until=now + timedelta(seconds=LEASE_SECONDS))
    return EmailJob.objects.get(pk=job_id) if changed else None

def release(job, delay, error=''):
    EmailJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(
        status='pending', lease_until=None, lease_token=None, published_at=None,
        next_attempt_at=timezone.now() + timedelta(seconds=delay), last_error=error[:500])

@transaction.atomic
def dead_letter(job, reason):
    changed = EmailJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(
        status='dead', lease_until=None, lease_token=None, completed_at=timezone.now(),
        last_error=reason[:500])
    if changed:
        DeadLetter.objects.get_or_create(job=job, defaults={'reason': reason[:500]})

def backoff(attempt):
    # Deterministic capped exponential backoff; jitter is added at scheduling time.
    return min(60, 2 ** attempt)
