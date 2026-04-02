# raceguard

**[View Live Showcase & Docs ↗](https://chukwunwike.github.io/raceguard/)**

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

## Detection Boundaries & Limitations

While `raceguard` is a powerful tool for hunting in-memory thread races, it is important to understand its boundaries:

1.  **Python-Level Only**: It tracks access through the Python object model. It **cannot** detect data races happening inside compiled C-extensions (like OpenSSL in the `ssl` module) because those bypass Python's `__getattribute__` system.
2.  **In-Process Only**: It detects races between threads/tasks in the **same memory space**. It does not track races across different OS processes (e.g., `multiprocessing` or database state).
3.  **No OS State Tracking**: It does not track race conditions involving OS-level primitives like PIDs, File Descriptors, or File System entries (TOCTOU).
4.  **Heuristic Window**: By default, it relies on a timing window (10ms). While `configure(strict=True)` improves this, very rare interleavings might still require multiple runs to surface.
5.  **Object Identity**: Python provides no way to hook the `is` operator or `id()`. If you need to check the identity of the underlying data, use `raceguard.unbind(obj)`.

## Author

Developed by **Chukwunwike Obodo**.

## License

This project is licensed under the MIT License.
