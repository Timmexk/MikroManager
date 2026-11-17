"""Small in-process cache for answers that cost several REST calls to a router.

A page that refreshes every 10 seconds should not make the router print the same eight menus each
time. Entries live for a few seconds, and every change made through MikroManager (any request that
is not a GET) empties the cache, so what you see right after saving is never stale.
"""
import time

_store: dict[tuple, tuple[float, object]] = {}
generation = 0          # bumped on every change; part of keys for things derived from the poller state


def get(key: tuple):
    hit = _store.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def put(key: tuple, value, ttl: float):
    if len(_store) > 500:
        now = time.time()
        for k in [k for k, (until, _) in _store.items() if until <= now]:
            _store.pop(k, None)
    _store[key] = (time.time() + ttl, value)
    return value


def clear() -> None:
    global generation
    generation += 1
    _store.clear()
