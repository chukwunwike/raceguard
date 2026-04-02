# raceguard

Raceguard is a pragmatic, zero-overhead production-ready library for hunting down threading bugs in Python by detecting un-synchronized concurrent access to shared mutable objects.

## The Problem
Python threading bugs often cause silent data corruption or unpredictable behavior due to race conditions. Typical tools slow down your execution massively or require writing complex annotations.

## The Solution
Wrap any shared object with `protect()`. Whenever two threads access it concurrently without a lock, a `RaceConditionError` is thrown, indicating exactly the thread names, time gap, and operation.

Crucially, **raceguard is designed for production**:
In production, setting `RACEGUARD_ENABLED=0` guarantees that `protect()` returns the raw, original object with exactly **zero overhead**. 
This eliminates performance penalties and ensures 100% C-extension compatibility in live environments.

## Features
- **Smart lock-aware heuristic**: Avoids false positives by recognizing when a previous write was synchronized.
- **Zero-Friction**: Disabled globally via `RACEGUARD_ENABLED=0` or `configure(enabled=False)`, converting protections to a zero-overhead passthrough.
- **Asyncio Tracking**: Tracks underlying `asyncio` task identities directly within standard loops to seamlessly identify thread interleaving between pure async tasks.
- **Strict Mode**: Use `configure(strict=True)` to bypass the lenient time heuristic and catch un-synchronized lockless accesses regardless of time delays.
- **Primitive Value Wrapper**: Provides a custom `Value` wrapper for protecting and updating immutable semantic types natively without having to resort to wrapping standard primitives in dictionaries.

## Installation

```bash
pip install .
```

## Usage

```python
import threading
from raceguard import protect, with_lock, locked

# 1. Protect a mutable container
shared_list = protect([])

# 2. Access unsafely (Will throw RaceConditionError if races are detected)
def unsafe_worker():
    shared_list.append(1) 

# 3. Access Safely via Context Manager
def safe_worker_ctx():
    with locked(shared_list):
        shared_list.append(1)

# 4. Access Safely via Decorator
@with_lock(shared_list)
def safe_worker_dec():
    shared_list.append(1)
```

## Limitations & Architecture
- By default, it operates on a heuristic based on time proximity, meaning you generally rely on the execution scheduler to interleave execution, unless explicitly running with `configure(strict=True)`.
- Explicitly tracks concurrent multi-threading accesses including standard Python `asyncio` tasks across asynchronous event loops. (Note: does not cross `multiprocessing` memory segment bounds).
- Intentionally skips wrapping immutable primitives directly (`int`, `str`, `float`, `tuple`) to maintain fundamental Python language semantics. Instead, wrap the primitive inside the explicitly provided `raceguard.Value` wrapper.

## Author

Developed by **Chukwunwike Obodo**.

## License

This project is licensed under the MIT License.
