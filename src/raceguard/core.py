from __future__ import annotations

import logging
import os
import sys
import threading
import time
import asyncio
import contextlib
from functools import wraps
from typing import Any

# =========================================================================
# Errors & Config
# =========================================================================

logger = logging.getLogger("raceguard")


class RaceConditionError(Exception):
    """Raised when an unsynchronized concurrent access is detected."""
    pass


class RaceConditionWarning:
    """Container for race condition details when in 'warn' mode."""

    __slots__ = (
        "object_type", "object_repr", "mode", "previous_mode",
        "current_thread", "previous_thread",
        "current_location", "previous_location",
        "time_gap_ms", "race_window_ms",
    )

    def __init__(
        self, *, object_type: str, object_repr: str,
        mode: str, previous_mode: str,
        current_thread: str, previous_thread: str,
        current_location: tuple[str, int, str],
        previous_location: tuple[str, int, str],
        time_gap_ms: float, race_window_ms: float,
    ) -> None:
        self.object_type = object_type
        self.object_repr = object_repr
        self.mode = mode
        self.previous_mode = previous_mode
        self.current_thread = current_thread
        self.previous_thread = previous_thread
        self.current_location = current_location
        self.previous_location = previous_location
        self.time_gap_ms = time_gap_ms
        self.race_window_ms = race_window_ms

    def __repr__(self) -> str:
        cur = self.current_location
        prev = self.previous_location
        return (
            f"RaceConditionWarning("
            f"{self.object_type}, {self.mode} vs {self.previous_mode}, "
            f"{cur[0]}:{cur[1]} vs {prev[0]}:{prev[1]})"
        )


# Modes: "raise", "warn", "log"
#   raise — throw RaceConditionError immediately (default)
#   warn  — collect warnings in raceguard.warnings list + log
#   log   — only log via logging module, do not collect

_CONFIG: dict[str, Any] = {
    "enabled": int(os.environ.get("RACEGUARD_ENABLED", "1")) != 0,
    "race_window": float(os.environ.get("RACEGUARD_WINDOW", "0.01")),
    "strict": int(os.environ.get("RACEGUARD_STRICT", "0")) != 0,
    "mode": os.environ.get("RACEGUARD_MODE", "raise"),
    "max_warnings": 1000,
}

# Global warnings collector for "warn" mode
warnings: list[RaceConditionWarning] = []
_warnings_lock = threading.Lock()


def configure(
    *,
    enabled: bool | None = None,
    race_window: float | None = None,
    strict: bool | None = None,
    mode: str | None = None,
    max_warnings: int | None = None,
) -> None:
    """Configure raceguard behaviour.

    Args:
        enabled: Enable or disable detection. When disabled, protect()
                 returns the raw object with zero overhead.
        race_window: Time window in seconds (default 0.01) within which
                     concurrent accesses are considered a race.
        strict: If True, bypass the race_window heuristic and flag any un-synchronized
                access by a different thread/task as a race.
        mode: Detection mode — "raise" (default), "warn", or "log".
        max_warnings: Max warnings to collect in warn mode (default 1000).
    """
    if enabled is not None:
        _CONFIG["enabled"] = enabled
    if race_window is not None:
        _CONFIG["race_window"] = race_window
    if strict is not None:
        _CONFIG["strict"] = strict
    if mode is not None:
        if mode not in ("raise", "warn", "log"):
            raise ValueError(f"Invalid mode {mode!r}. Use 'raise', 'warn', or 'log'.")
        _CONFIG["mode"] = mode
    if max_warnings is not None:
        _CONFIG["max_warnings"] = max_warnings


def get_config() -> dict[str, Any]:
    """Return a copy of the current configuration."""
    return dict(_CONFIG)


def clear_warnings() -> list[RaceConditionWarning]:
    """Clear and return all collected warnings."""
    with _warnings_lock:
        result = list(warnings)
        warnings.clear()
        return result


# =========================================================================
# Synchronization Helpers
# =========================================================================

def _acquire_all(proxies: tuple) -> list[threading.Lock]:
    """Acquire locks for multiple proxies in a consistent order to avoid deadlocks."""
    locks = sorted(
        (object.__getattribute__(p, "_rg_lock") for p in proxies),
        key=id,
    )
    acquired: list[threading.Lock] = []
    try:
        for lock in locks:
            lock.acquire()
            acquired.append(lock)
    except Exception:
        for lock in reversed(acquired):
            lock.release()
        raise
    return acquired


def _release_all(acquired: list[threading.Lock]) -> None:
    for lock in reversed(acquired):
        lock.release()


def with_lock(*proxies: Any):
    """Decorator that acquires the lock(s) of the given protected proxy(ies)
    before calling the decorated function, and releases afterward.

    Example::

        results = protect([])

        @with_lock(results)
        def add_result(val):
            results.append(val)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            acquired = _acquire_all(proxies)
            try:
                return func(*args, **kwargs)
            finally:
                _release_all(acquired)
        return wrapper
    return decorator


@contextlib.contextmanager
def locked(*proxies: Any):
    """Context manager that acquires the lock(s) of the given protected
    proxy(ies), yielding control once all locks are held.

    Example::

        shared = protect({'count': 0})

        with locked(shared):
            shared['count'] += 1
    """
    acquired = _acquire_all(proxies)
    try:
        yield
    finally:
        _release_all(acquired)


# =========================================================================
# Proxy Core
# =========================================================================

_MUTATING_METHODS: dict[type, frozenset[str]] = {
    list: frozenset({
        "append", "extend", "insert", "remove", "pop",
        "clear", "sort", "reverse", "__iadd__",
    }),
    dict: frozenset({
        "update", "pop", "popitem", "clear", "setdefault",
    }),
    set: frozenset({
        "add", "remove", "discard", "pop", "clear", "update",
        "intersection_update", "difference_update",
        "symmetric_difference_update",
    }),
    bytearray: frozenset({
        "append", "extend", "insert", "remove", "pop",
        "clear", "reverse",
    }),
}


def _is_mutating(obj: Any, name: str) -> bool:
    for cls, methods in _MUTATING_METHODS.items():
        if isinstance(obj, cls) and name in methods:
            return True
    return False


def _wrap_as_write(method: Any, proxy: "_ProtectedProxy") -> Any:
    @wraps(method)
    def _checked(*args: Any, **kwargs: Any) -> Any:
        object.__getattribute__(proxy, "_rg_check")("write")
        return method(*args, **kwargs)
    return _checked


_INTERNAL: frozenset[str] = frozenset({
    "_rg_obj",
    "_rg_lock",
    "_rg_last_actor",
    "_rg_last_time",
    "_rg_last_was_locked",
    "_rg_last_mode",
    "_rg_last_location",
    "_rg_state_lock",
})


def _get_caller_info() -> tuple[str, int, str]:
    """Walk the stack using sys._getframe (50x faster than inspect.stack).

    Returns the (filename, lineno, function_name) of the first caller
    outside of raceguard's own module file.
    """
    this_file = os.path.normcase(os.path.abspath(__file__))
    try:
        frame = sys._getframe(1)
        while frame is not None:
            fname = os.path.normcase(os.path.abspath(frame.f_code.co_filename))
            if fname != this_file:
                return (frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name)
            frame = frame.f_back
    except (AttributeError, ValueError):
        pass
    return ("<unknown>", 0, "<unknown>")


def _format_race_message(
    obj: Any,
    mode: str, last_mode: str,
    current_thread_name: str, last_thread_name: str,
    cur_loc: tuple[str, int, str], prev_loc: tuple[str, int, str],
    delta_ms: float, window_ms: float,
) -> str:
    """Build a human-readable race condition report."""
    obj_repr = repr(obj)
    if len(obj_repr) > 60:
        obj_repr = obj_repr[:57] + "..."
    return (
        f"\n{'-' * 60}\n"
        f"  Race condition detected!\n"
        f"{'-' * 60}\n"
        f"  Object       : {type(obj).__name__}  ->  {obj_repr}\n"
        f"  Operation    : {mode} (previous was {last_mode})\n"
        f"{'-' * 60}\n"
        f"  > Current access:\n"
        f"      Thread   : {current_thread_name!r}\n"
        f"      Location : {cur_loc[0]}:{cur_loc[1]} in {cur_loc[2]}()\n"
        f"  > Previous access:\n"
        f"      Thread   : {last_thread_name!r}\n"
        f"      Location : {prev_loc[0]}:{prev_loc[1]} in {prev_loc[2]}()\n"
        f"{'-' * 60}\n"
        f"  Time gap     : {delta_ms:.2f} ms  (window: {window_ms:.0f} ms)\n"
        f"  Lock held    : No\n"
        f"{'-' * 60}\n"
        f"  Fix: wrap the access in 'with locked(obj):'\n"
        f"       or decorate with @with_lock(obj).\n"
    )


class _SyncMemory:
    """Shared race-detection state used across a hierarchy of proxies."""
    def __init__(self) -> None:
        self.last_actor: Any = None
        self.last_time: float = 0.0
        self.last_was_locked: bool = False
        self.last_mode: str = "read"
        self.last_location: tuple = (None, None, 0)
        self.state_lock: threading.Lock = threading.Lock()


def _safe_protect(obj: Any, lock: threading.Lock | None = None, memory: _SyncMemory | None = None) -> Any:
    """Silently ignore primitives. Used internally for nested value proxying."""
    if not _CONFIG["enabled"]:
        return obj
    if isinstance(obj, (int, float, str, tuple, bool, bytes, frozenset, type(None))):
        return obj
    if isinstance(obj, _ProtectedProxy):
        return obj
    return _ProtectedProxy(obj, lock=lock, memory=memory)


class _ProxyIterator:
    def __init__(self, proxy: '_ProtectedProxy', iterator: Any) -> None:
        self.proxy = proxy
        self.iterator = iterator

    def __iter__(self):
        return self

    def __next__(self):
        # Ping the active reader flag on *every single iteration*
        object.__getattribute__(self.proxy, "_rg_check")("read")
        val = next(self.iterator)
        # Inherit lock and context memory from the parent proxy
        return _safe_protect(
            val, 
            lock=object.__getattribute__(self.proxy, "_rg_lock"),
            memory=object.__getattribute__(self.proxy, "_rg_memory")
        )


class _ProtectedProxy:

    def __init__(self, obj: Any, lock: threading.Lock | None = None, memory: _SyncMemory | None = None) -> None:
        object.__setattr__(self, "_rg_obj", obj)
        object.__setattr__(self, "_rg_lock", lock if lock is not None else threading.RLock())
        object.__setattr__(self, "_rg_memory", memory if memory is not None else _SyncMemory())

    @property
    def __class__(self):
        return type(object.__getattribute__(self, "_rg_obj"))

    def _rg_check(self, mode: str) -> None:
        if not _CONFIG["enabled"]:
            return

        current_thread = threading.current_thread()
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        current_actor = (current_thread, current_task)
        
        now = time.monotonic()
        mem: _SyncMemory = object.__getattribute__(self, "_rg_memory")

        with mem.state_lock:
            # Check if lock is held (works for Lock and RLock)
            obj_lock: threading.Lock = object.__getattribute__(self, "_rg_lock")
            if hasattr(obj_lock, "locked"):
                currently_locked = obj_lock.locked()
            elif hasattr(obj_lock, "_is_owned"):
                # CPython RLock: check if held by current thread
                currently_locked = obj_lock._is_owned()
            else:
                # Generic fallback for RLock: try to acquire it. 
                if obj_lock.acquire(blocking=False):
                    obj_lock.release()
                    currently_locked = False
                else:
                    currently_locked = True

            def _update(location: tuple) -> None:
                mem.last_actor = current_actor
                mem.last_time = now
                mem.last_was_locked = currently_locked
                mem.last_mode = mode
                mem.last_location = location

            # Rule 1: First access or same actor — always safe
            if mem.last_actor is None or mem.last_actor == current_actor:
                _update(_get_caller_info())
                return

            # Rule 2: Previous access was under a lock — safe
            if mem.last_was_locked:
                _update(_get_caller_info())
                return

            # Rule 3: Both lockless, within time window (or strict mode)
            delta = now - mem.last_time
            if (delta < _CONFIG["race_window"] or _CONFIG["strict"]) and not currently_locked:
                # Concurrent reads are always safe
                if mode == "read" and mem.last_mode == "read":
                    _update(_get_caller_info())
                    return

                # --- RACE DETECTED ---
                current_location = _get_caller_info()               
                
                def _actor_name(actor):
                    th, task = actor
                    if task is not None:
                        return f"{th.name} ({task.get_name()})"
                    return th.name

                obj = object.__getattribute__(self, "_rg_obj")
                delta_ms = delta * 1000
                window_ms = _CONFIG["race_window"] * 1000
                msg = _format_race_message(
                    obj, mode, mem.last_mode,
                    _actor_name(current_actor), _actor_name(mem.last_actor),
                    current_location, mem.last_location,
                    delta_ms, window_ms,
                )

                cfg_mode = _CONFIG["mode"]

                if cfg_mode == "raise":
                    raise RaceConditionError(msg)
                elif cfg_mode == "warn":
                    w = RaceConditionWarning(
                        object_type=type(obj).__name__,
                        object_repr=repr(obj)[:80],
                        mode=mode, previous_mode=mem.last_mode,
                        current_thread=_actor_name(current_actor),
                        previous_thread=_actor_name(mem.last_actor),
                        current_location=current_location,
                        previous_location=mem.last_location,
                        time_gap_ms=delta_ms,
                        race_window_ms=window_ms,
                    )
                    with _warnings_lock:
                        if len(warnings) < _CONFIG["max_warnings"]:
                            warnings.append(w)
                    logger.warning(msg)
                elif cfg_mode == "log":
                    logger.warning(msg)

                _update(current_location)
                return

            # Rule 4: Sequential access — safe
            _update(_get_caller_info())

    @property
    def lock(self) -> threading.Lock:
        """The underlying lock for this protected object."""
        return object.__getattribute__(self, "_rg_lock")

    # --- Attribute access ---

    def __getattr__(self, name: str) -> Any:
        obj = object.__getattribute__(self, "_rg_obj")
        attr = getattr(obj, name)

        if callable(attr):
            if _is_mutating(obj, name):
                return _wrap_as_write(attr, self)
            else:
                object.__getattribute__(self, "_rg_check")("read")
            return attr

        object.__getattribute__(self, "_rg_check")("read")
        return _safe_protect(attr, lock=object.__getattribute__(self, "_rg_lock"))

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _INTERNAL:
            object.__setattr__(self, name, value)
            return
        object.__getattribute__(self, "_rg_check")("write")
        setattr(object.__getattribute__(self, "_rg_obj"), name, value)

    def __delattr__(self, name: str) -> None:
        if name in _INTERNAL:
            object.__delattr__(self, name)
            return
        object.__getattribute__(self, "_rg_check")("write")
        delattr(object.__getattribute__(self, "_rg_obj"), name)

    # --- Container protocol ---

    def __len__(self) -> int:
        object.__getattribute__(self, "_rg_check")("read")
        return len(object.__getattribute__(self, "_rg_obj"))

    def __bool__(self) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        return bool(object.__getattribute__(self, "_rg_obj"))

    def __iter__(self):
        object.__getattribute__(self, "_rg_check")("read")
        return _ProxyIterator(self, iter(object.__getattribute__(self, "_rg_obj")))

    def __reversed__(self):
        object.__getattribute__(self, "_rg_check")("read")
        val = reversed(object.__getattribute__(self, "_rg_obj"))
        return _safe_protect(
            val, 
            lock=object.__getattribute__(self, "_rg_lock"),
            memory=object.__getattribute__(self, "_rg_memory")
        )

    def __contains__(self, item: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        return item in object.__getattribute__(self, "_rg_obj")

    def __getitem__(self, key: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        val = object.__getattribute__(self, "_rg_obj")[key]
        return _safe_protect(
            val, 
            lock=object.__getattribute__(self, "_rg_lock"),
            memory=object.__getattribute__(self, "_rg_memory")
        )

    def __setitem__(self, key: Any, value: Any) -> None:
        object.__getattribute__(self, "_rg_check")("write")
        object.__getattribute__(self, "_rg_obj")[key] = value

    def __delitem__(self, key: Any) -> None:
        object.__getattribute__(self, "_rg_check")("write")
        del object.__getattribute__(self, "_rg_obj")[key]

    # --- Context manager ---

    def __enter__(self):
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        return obj.__enter__()

    def __exit__(self, *args: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        return obj.__exit__(*args)

    # --- In-place operators (mutating) ---

    def __iadd__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj += other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __isub__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj -= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __imul__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj *= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __ifloordiv__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj //= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __itruediv__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj /= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __imod__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj %= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __ior__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj |= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __iand__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj &= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    def __ixor__(self, other: Any) -> "_ProtectedProxy":
        object.__getattribute__(self, "_rg_check")("write")
        obj = object.__getattribute__(self, "_rg_obj")
        obj ^= other
        object.__setattr__(self, "_rg_obj", obj)
        return self

    # --- Binary operators (read) ---

    def __add__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj + other

    def __radd__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        return other + object.__getattribute__(self, "_rg_obj")

    def __sub__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj - other

    def __mul__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj * other

    def __rmul__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        return other * object.__getattribute__(self, "_rg_obj")

    def __floordiv__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj // other

    def __truediv__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj / other

    def __mod__(self, other: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj % other

    # --- Callable ---

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        return obj(*args, **kwargs)

    # --- Numeric conversions ---

    def __int__(self) -> int:
        return int(object.__getattribute__(self, "_rg_obj"))

    def __float__(self) -> float:
        return float(object.__getattribute__(self, "_rg_obj"))

    def __index__(self) -> int:
        return object.__getattribute__(self, "_rg_obj").__index__()

    def __abs__(self) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        return abs(object.__getattribute__(self, "_rg_obj"))

    def __neg__(self) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        return -object.__getattribute__(self, "_rg_obj")

    def __pos__(self) -> Any:
        object.__getattribute__(self, "_rg_check")("read")
        return +object.__getattribute__(self, "_rg_obj")

    # --- Comparison ---

    def __eq__(self, other: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj == other

    def __ne__(self, other: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj != other

    def __lt__(self, other: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj < other

    def __le__(self, other: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj <= other

    def __gt__(self, other: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj > other

    def __ge__(self, other: Any) -> bool:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        if isinstance(other, _ProtectedProxy):
            other = object.__getattribute__(other, "_rg_obj")
        return obj >= other

    def __hash__(self):
        object.__getattribute__(self, "_rg_check")("read")
        return hash(object.__getattribute__(self, "_rg_obj"))

    # --- String ---

    def __repr__(self) -> str:
        object.__getattribute__(self, "_rg_check")("read")
        obj = object.__getattribute__(self, "_rg_obj")
        return f"<Protected {type(obj).__name__}: {obj!r}>"

    def __str__(self) -> str:
        object.__getattribute__(self, "_rg_check")("read")
        return str(object.__getattribute__(self, "_rg_obj"))

    def __format__(self, format_spec: str) -> str:
        object.__getattribute__(self, "_rg_check")("read")
        return format(object.__getattribute__(self, "_rg_obj"), format_spec)

    def __bytes__(self) -> bytes:
        object.__getattribute__(self, "_rg_check")("read")
        return bytes(object.__getattribute__(self, "_rg_obj"))


def protect(obj: Any, lock: threading.Lock | None = None) -> Any:
    """Wrap a mutable object so that raceguard monitors all accesses.

    When ``RACEGUARD_ENABLED=0`` or ``configure(enabled=False)`` is set,
    this returns the raw *obj* with zero overhead — no proxy, no cost.

    Args:
        obj: A mutable object (list, dict, set, custom class instance, etc.).
        lock: An optional external lock.  If not provided, a new
              ``threading.Lock()`` is created per object.

    Raises:
        ValueError: If *obj* is an immutable primitive (int, str, etc.).
    """
    if not _CONFIG["enabled"]:
        return obj

    if isinstance(obj, (int, float, str, tuple, bool, bytes, frozenset)):
        raise ValueError(
            f"Cannot protect immutable primitives ({type(obj).__name__}). "
            "Wrap the mutable container that holds them instead."
        )

    if isinstance(obj, _ProtectedProxy):
        return obj
    return _ProtectedProxy(obj, lock=lock)


class Value:
    """A wrapper for primitive types (int, float, str, bool, etc.) to allow them
    to be protected by raceguard.
    
    Example::
        shared_counter = protect(Value(0))
        with locked(shared_counter):
            shared_counter.value += 1
    """
    __slots__ = ("value",)
    
    def __init__(self, value: Any) -> None:
        self.value = value
        
    def __repr__(self) -> str:
        return f"Value({self.value!r})"
        
    def __str__(self) -> str:
        return str(self.value)
        
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Value):
            return self.value == other.value
        return self.value == other
        
    def set(self, val: Any) -> None:
        self.value = val
        
    def get(self) -> Any:
        return self.value


def reset(obj: Any) -> None:
    """Explicitly clear the proxy's synchronization memory. Use this after an OS-level thread
    barrier or Queue dispatch to prevent strict mode from raising false-positive races.
    """
    if isinstance(obj, _ProtectedProxy):
        mem: _SyncMemory = object.__getattribute__(obj, "_rg_memory")
        with mem.state_lock:
            mem.last_actor = None
            mem.last_time = 0.0
            mem.last_was_locked = False
            mem.last_mode = "read"



def unbind(obj: Any) -> Any:
    """Return the raw underlying python object, shedding the Raceguard proxy wrapper.
    Use this if you desperately need to evaluate object identity via `is`.
    """
    if isinstance(obj, _ProtectedProxy):
        return object.__getattribute__(obj, "_rg_obj")
    return obj
