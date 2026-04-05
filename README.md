# Raceguard

**Detect real data races in your code before they become production bugs.**

**[View Live Showcase & Docs ↗](https://chukwunwike.github.io/raceguard/)**

Raceguard is a runtime concurrency safety tool that observes your program execution and flags unsafe memory access patterns across threads and async tasks, without requiring compiler support or complex setup.

---

## The Problem

Concurrency bugs are some of the hardest issues to detect and fix.

They are:
*   **Non-deterministic**: Bugs appear randomly and are hard to pin down.
*   **Invisible**: They often hide until high-traffic production environments.
*   **Corrupting**: They cause silent data corruption that is painful to debug.

Most developers only discover race conditions after something breaks. Existing tools are often too complex, slow, or invasive for everyday workflows.

---

## What Raceguard Does

Raceguard watches your shared objects as they are accessed and detects:
*   **Concurrent writes** to the same memory space.
*   **Read/Write conflicts** across threads or async flows.
*   **Unsafe shared state access** without proper synchronization.

It surfaces these issues immediately with clear, actionable output.

---

## Quick Example

### Problematic code

```python
import threading

# A shared list that multiple threads will update
counter = []

def increment():
    for _ in range(1000):
        counter.append(1)

threads = [threading.Thread(target=increment) for _ in range(10)]
for t in threads: t.start()
for t in threads: t.join()
```

### Protected with Raceguard

```python
from raceguard import protect, locked

# Just wrap your shared object
counter = protect([])

def increment():
    for _ in range(1000):
        # Access safely via context manager
        with locked(counter):
            counter.append(1)

# ... rest of the code ...
```

If you forget the `with locked(counter):` block, Raceguard will instantly throw a `RaceConditionError` with a full report.

---

## Why Raceguard Is Different

Raceguard is designed for **real developer workflows**, not just theory.

*   **High Performance**: Uses lazy frame capture, avoiding expensive stack inspection overhead until absolutely necessary.
*   **Flexible Detection**: Native support for `raise`, `warn`, and `log` modes to fit your testing strategy.
*   **Zero Production Overhead**: Set `RACEGUARD_ENABLED=0` to completely bypass the proxy in live environments.
*   **Async-Aware**: Seamlessly tracks races between mixed `asyncio` tasks and standard threads.
*   **Deep Protection**: Automatically proxies nested mutable structures, including full interception of Python's dunder methods and context managers.
*   **Rich Reports**: Tells you exactly which threads accessed the object, at what time, and where to fix it.

---

## How It Works (Simple Mental Model)

Think of Raceguard as a **Synchronization Observer**.

1.  **Wrap**: You wrap a shared object with `protect()`.
2.  **Track**: It records the identity of every thread or task that touches the object.
3.  **Validate**: It checks if a lock is held when the same memory is accessed.
4.  **Report**: If two threads touch the same data too quickly without a lock, it flags the conflict.

---

## Installation

```bash
pip install raceguard
```

---

## Deployment & Usage

Typical usage patterns:

*   **Development** — Run with `configure(mode="raise")` (or `"warn"`, `"log"`) to catch the obvious cases fast with immediate feedback during local testing.
*   **Continuous Integration** — Use `configure(strict=True)` in CI for correctness assertions. Heuristic mode (`race_window`) depends on timing, which varies under CPU load. **Strict mode is the right tool for CI**: it flags any lockless write from a different thread, regardless of elapsed time.
*   **Production** — Set `RACEGUARD_ENABLED=0` for a true zero-cost passthrough of your original objects.

> **Heuristic vs. Strict — the key distinction**: The default `race_window` of 10ms catches overlapping accesses quickly, but in a highly loaded system two logically racy writes could be far apart in wall time and slip through. Strict mode removes this ambiguity entirely — if no lock was used, it's a race.

---

## Usage Patterns

```python
import threading
from raceguard import protect, with_lock, locked

# 1. Protect a shared mutable object
shared_list = protect([])

# 2. Access unsafely (Will throw RaceConditionError if races occur)
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

# 5. Lock multiple proxies atomically (consistent ordering prevents deadlocks)
a = protect([])
b = protect({})
with locked(a, b):
    a.append(1)
    b["x"] = 1
```

### Supported Object Types

Raceguard can wrap any mutable Python object:

```python
protect([])            # list
protect({})            # dict
protect(set())         # set
protect(bytearray())   # bytearray
protect(MyClass())     # any custom object
protect(Value(0))      # scalar via Value wrapper
```

### `protect()` is idempotent

Wrapping an already-protected object returns the **same proxy** — no double-wrapping:

```python
p1 = protect(my_list)
p2 = protect(p1)   # same proxy as p1
assert p1 is p2    # True
```

### Concurrent Reads Are Safe

Two threads reading simultaneously do **not** trigger a race. Only write/write or read/write conflicts are flagged:

```python
shared = protect({"val": 42})

# Both threads reading at the same time — no RaceConditionError
def reader():
    _ = shared["val"]
```

---

## Advanced Features

### Automatic Nested Protection
Raceguard automatically protects child objects. You don't need to manually wrap every nested dictionary or list in your state tree.

```python
from raceguard import protect

# Wrap the parent object once
state = protect({"users": ["Alice", "Bob"]})

# The child list is automatically protected when accessed!
state["users"].append("Charlie")
```

### Iterator Race Detection

Raceguard catches writes that happen while another thread is mid-iteration:

```python
shared = protect([1, 2, 3])

def slow_reader():
    for item in shared:
        time.sleep(0.05)   # still iterating...

def writer():
    time.sleep(0.02)
    shared.append(4)       # RaceConditionError — write during iteration!
```

### Actionable Error Reports
When a race condition occurs, Raceguard tells you exactly what went wrong, including the specific Thread IDs and Async Task names involved.

```text
RaceConditionError: Concurrent access detected on object <list> at 0x...
Thread-1 (ID: 12345) wrote to object at 10:05:01.001
Thread-2 (ID: 67890) accessed object at 10:05:01.003
Location: mymodule.py:42 in worker()
Missing synchronization lock during access.
```

### Asyncio & Threading Support
Raceguard safely tracks state even in hybrid architectures where standard threads and `asyncio` event loops are running simultaneously and modifying the same objects.

### Strict Mode — Catching Temporally Distant Unsynchronized Writes

By default, Raceguard flags accesses within a time window. With `strict=True`, **any lockless write from a different thread is flagged**, even if it happens much later:

```python
from raceguard import protect, configure, Value

configure(strict=True)
shared = protect(Value("initial"))

def thread1():
    shared.value = "written by T1"  # First write

def thread2():
    time.sleep(0.5)                 # Waits well beyond the race window...
    shared.value = "written by T2"  # Still caught! No lock was used.
```

> **Tip**: In strict mode, use `reset(shared)` to manually clear access history when threads coordinate via a non-lock mechanism like a `queue.Queue`.

```python
from raceguard import reset

def stage2():
    result = my_queue.get()   # synchronized via Queue
    reset(shared)             # tell Raceguard this is a fresh access point
    shared.value = result     # safe — no false positive
```

### Cross-Platform Verified
Fully supported and tested across:
*   **Windows**
*   **Linux**
*   **macOS**

---


## Environment Variables

Configure Raceguard without modifying code. Useful for CI/CD pipelines and deployment scripts.

| Variable | Default | Description |
|---|---|---|
| `RACEGUARD_ENABLED` | `1` | Set to `0` to completely disable detection (zero overhead). |
| `RACEGUARD_MODE` | `raise` | Detection mode: `raise`, `warn`, or `log`. |
| `RACEGUARD_STRICT` | `0` | Set to `1` to flag any unsynchronized access regardless of timing. |
| `RACEGUARD_WINDOW` | `0.01` | Time window (seconds) within which concurrent accesses are flagged. |

---

## Full `configure()` Reference

```python
from raceguard import configure

configure(
    enabled=True,        # Toggle detection on/off at runtime
    mode="raise",        # "raise" | "warn" | "log"
    strict=False,        # Bypass timing heuristic, flag all unsynchronized access
    race_window=0.01,    # Seconds — the sensitivity window for detecting races
    max_warnings=1000,   # Cap collected warnings in "warn" mode to prevent flooding
)
```

---

## Protecting Scalar Values

Use `Value()` to protect simple types like `int`, `float`, or `str` that cannot be proxied directly.

`Value` exposes three access patterns — use whichever fits your style:

```python
from raceguard import protect, Value, locked

counter = protect(Value(0))

def worker():
    with locked(counter):
        counter.value += 1   # attribute access
        counter.set(5)       # setter method
        x = counter.get()    # getter method
```

---

## Utility Functions

```python
from raceguard import (
    get_config,       # Returns the current configuration dict
    clear_warnings,   # Returns and clears all collected RaceConditionWarning objects
    warnings,         # Direct access to the list of collected warnings
    reset,            # Resets library state (useful between test runs)
    unbind,           # Unwraps a proxy to retrieve the raw underlying object
)

# Example: Inspect warnings after a test run
from raceguard import configure, clear_warnings

configure(mode="warn")
# ... run concurrent code ...
collected = clear_warnings()
for w in collected:
    print(w)

# Example: Get the raw object for identity checks or serialization
from raceguard import protect, unbind

data = protect({"key": "value"})
raw = unbind(data)  # Returns the original dict
```

---

## Known Limitations & Blindspots

While Raceguard is highly effective for hunting in-memory thread races, there are fundamental "True Blindspots" that can evade the tracking model:

1.  **Direct Internal Access**: Code that bypasses the proxy layer and accesses the wrapped object's internal reference directly will evade detection.
2.  **OS Signal Preemption**: Logic executed within asynchronous signal handlers (e.g., `SIGALRM`) runs in the same thread context. This can cause "invisible" races that appear as legitimate single-threaded access.
3.  **Cross-Process Memory Forks**: OS-level `fork()` clones memory. Raceguard tracks within the memory space of a single process and cannot natively bridge state across process boundaries.
4.  **C-Extension Logic**: The library cannot observe concurrency that occurs purely within compiled C-extensions (like `numpy` internals or `OpenSSL`) if they bypass the CPython attribute accessors.
5.  **ABA-style races**: Raceguard tracks the *last* access per object rather than a full happens-before graph. This means a write-write-read sequence (T1 writes → T2 writes → T1 reads) may not be flagged if the race window has expired between steps, even though T1 is silently reading T2's data. Use `strict=True` to close most of this gap.

We recommend using Raceguard as a **heuristic safety net** rather than an absolute formal verifier for these edge cases.

---

## Dev-Mode Overhead

In **production** (`RACEGUARD_ENABLED=0`), `protect()` acts as a completely transparent kill-switch. It bypasses proxy creation entirely and returns your raw object directly, ensuring absolutely **zero overhead** at runtime.

In **development mode**, every attribute access on a protected object passes through the proxy layer, which performs a thread-identity check and a timestamp comparison. This is intentionally lightweight, but it is not free.

As a rough guide:

| Access frequency | Expected impact |
|---|---|
| Occasional (locks, shared status flags) | Negligible — use freely |
| Moderate (per-request shared state) | Minimal — order of microseconds per access |
| Tight hot loop (millions/sec) | Measurable — consider wrapping only during test runs, not benchmarks |

Lazy frame capture means **stack traces are only resolved when a race is actually detected**, keeping the common (no-race) path as fast as possible. If you are profiling performance of concurrent code, run with `RACEGUARD_ENABLED=0` to eliminate all proxy overhead.

---

## Author

Developed by **Chukwunwike Obodo**.

---

## License

This project is licensed under the MIT License.
