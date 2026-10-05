"""Shared in-process mutation boundary for one local project.

This coordinates repository instances, not separate API/CLI processes. Atomic
file replacement still publishes each JSON file; the lock serializes the whole
read/validate/write operation and is not a multi-file crash transaction.
"""

from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary

_project_locks: WeakValueDictionary[Path, RLock] = WeakValueDictionary()
_registry_lock = Lock()


def project_mutation_lock(directory: Path) -> RLock:
    """Share a reentrant lock for equivalent paths while repositories use it."""
    with _registry_lock:
        key = directory.resolve()
        lock = _project_locks.get(key)
        if lock is None:
            lock = RLock()
            _project_locks[key] = lock
        return lock
