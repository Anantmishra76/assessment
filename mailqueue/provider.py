import json
from django.conf import settings
from .limiter import redis_client

class TemporaryProviderError(Exception):
    pass

class PermanentProviderError(Exception):
    pass

# A simulated external provider. Idempotency state is intentionally outside Django's
# transaction, reproducing the send-before-database-commit crash boundary.
SEND = """
local receipt = redis.call('GET', KEYS[1])
if receipt then return {'sent', receipt} end
local count = redis.call('INCR', KEYS[2])
local time = redis.call('TIME')
local at = tonumber(time[1])*1000000 + tonumber(time[2])
redis.call('RPUSH', KEYS[3], cjson.encode({job=ARGV[1], at=at, attempt=count}))
if ARGV[2] == 'permanent' then return {'permanent', 'invalid recipient'} end
if ARGV[2] == 'always_transient' or (ARGV[2] == 'transient_once' and count == 1) then
    return {'temporary', 'simulated provider unavailable'}
end
local id = 'fake-' .. ARGV[1]
redis.call('SET', KEYS[1], id)
return {'sent', id}
"""

def send(job):
    base = settings.RATE_NAMESPACE + ':provider'
    status, value = redis_client().eval(SEND, 3,
        f'{base}:receipt:{job.pk}', f'{base}:attempts:{job.pk}', f'{base}:audit',
        str(job.pk), job.scenario)
    if status == 'temporary':
        raise TemporaryProviderError(value)
    if status == 'permanent':
        raise PermanentProviderError(value)
    return value
