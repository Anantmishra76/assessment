import fakeredis
import pytest
from mailqueue import limiter, provider


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(limiter, 'redis_client', lambda: client)
    monkeypatch.setattr(provider, 'redis_client', lambda: client)
    return client
