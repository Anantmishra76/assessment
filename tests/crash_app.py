"""Worker entrypoint used ONLY by the destructive process-recovery acceptance test."""
import os
from pathlib import Path
import threading
from config.celery import app
from celery.signals import worker_init


@worker_init.connect
def install_crash_gate(**kwargs):
    from mailqueue import provider
    original = provider.send

    def gated_send(job):
        receipt = original(job)
        # Simulate a stalled process after the external side effect but before commit.
        Path(os.environ['CRASH_GATE_FILE']).write_text(str(job.pk))
        threading.Event().wait(120)
        return receipt

    provider.send = gated_send
