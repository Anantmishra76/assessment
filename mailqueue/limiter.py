from pathlib import Path
from uuid import uuid4
from django.conf import settings
from redis import Redis

SCRIPT = Path(__file__).with_suffix('.lua').read_text(encoding='utf-8')

def redis_client():
    return Redis.from_url(settings.RATE_REDIS_URL, decode_responses=True,
                          socket_connect_timeout=2, socket_timeout=2)

def acquire(client=None, *, namespace=None, limit=200, window_us=61_000_000):
    if limit <= 0 or window_us <= 0:
        raise ValueError('Rate limit and window must be positive')
    client = client if client is not None else redis_client()
    key = f'{namespace or settings.RATE_NAMESPACE}:provider:window'
    allowed, value = client.eval(SCRIPT, 1, key, window_us, limit, uuid4().hex)
    return bool(allowed), int(value)
