import uuid
from django.db import models
from django.utils import timezone

class EmailJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending'
        PROCESSING = 'processing'
        SENT = 'sent'
        DEAD = 'dead'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    provider_id = models.CharField(max_length=100, blank=True)
    # Local fake-provider scenario; no arbitrary network address can be supplied.
    scenario = models.CharField(max_length=20, default='success', choices=[
        ('success', 'Success'), ('transient_once', 'Fail once'), ('permanent', 'Permanent'),
        ('always_transient', 'Always transient')])
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        indexes = [models.Index(fields=['status', 'next_attempt_at'])]

class DeadLetter(models.Model):
    job = models.OneToOneField(EmailJob, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
