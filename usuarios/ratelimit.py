"""Fixed-window attempt counters stored in the shared 'security' cache."""
import hashlib
import time

from django.core.cache import caches

MESSAGE = 'Muitas tentativas. Aguarde alguns minutos e tente novamente.'


def _key(scope, identifier):
    return f'ratelimit:{scope}:' + hashlib.sha256(identifier.encode()).hexdigest()


def is_limited(scope, identifier, limit):
    if not identifier:
        return False
    data = caches['security'].get(_key(scope, identifier))
    return bool(data) and data[1] > time.time() and data[0] >= limit


def hit(scope, identifier, window):
    if not identifier:
        return
    cache = caches['security']
    key = _key(scope, identifier)
    now = time.time()
    data = cache.get(key)
    if not data or data[1] <= now:
        data = (0, now + window)
    # Keep the original expiry; backend incr() would reset the timeout on some cache backends.
    cache.set(key, (data[0] + 1, data[1]), max(1, int(data[1] - now) + 1))


def reset(scope, identifier):
    if identifier:
        caches['security'].delete(_key(scope, identifier))
