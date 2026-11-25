"""A read cache for one UI refresh.

Drawing the window asks Windows the same questions many times: opening TrueStretch ran QueryDisplayConfig 33
times and listed the displays 21 times (2.1.0), every page refresh 5-8 times more, each a driver round trip that
is slow on some laptops. Inside `with reads():` the display readers (`display.list_displays`,
`display.available_modes`, `display.mode_accepted`, `displayconfig.monitors`, `monitors.list_monitor_devices`)
answer from the first result instead. Outside such a block nothing is cached, so the engine - which changes the
screen and must read it back fresh - is never affected: it only ever runs outside a refresh. Thread-local, so a
worker thread never sees the UI thread's cache."""

import threading
from contextlib import contextmanager

_local = threading.local()


def memo(key, compute):
    """compute() once per `reads()` block for this key; plain compute() outside one."""
    store = getattr(_local, "store", None)
    if store is None:
        return compute()
    if key not in store:
        store[key] = compute()
    return store[key]


@contextmanager
def reads():
    """Cache every display read for the duration of the block. Nested blocks share the outer cache."""
    if getattr(_local, "store", None) is not None:
        yield
        return
    _local.store = {}
    try:
        yield
    finally:
        _local.store = None


def active():
    return getattr(_local, "store", None) is not None
