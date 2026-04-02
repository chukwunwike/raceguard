import pytest
import threading
import queue
import time
from raceguard import protect, locked, RaceConditionError, reset, unbind

def test_rlock_reentrancy():
    shared = protect([])
    # If it was a standard Lock, this would deadlock
    with locked(shared):
        with locked(shared):
            shared.append(1)
    assert shared == [1]

def test_nested_mutables():
    # Outer dict protected, inner list natively nested
    shared = protect({"users": ["Alice", "Bob"]})
    errors = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait()
            # This read+append modifies the deep list without an explicit locked() call!
            shared["users"].append("Charlie")
        except RaceConditionError as e:
            errors.append(e)

    # Since the race window is small, doing it on 2 threads guarantees it
    from raceguard import configure
    configure(race_window=0.5)
    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors, "Race condition on nested list was not caught!"

def test_iterator_proxy():
    shared = protect([1, 2, 3])
    errors = []

    def reader():
        for item in shared:
            # Sleep in middle of iteration
            time.sleep(0.05)

    def writer():
        try:
            time.sleep(0.02) # Write while reader is mid-iteration
            shared.append(4)
        except RaceConditionError as e:
            errors.append(e)

    import raceguard
    raceguard.configure(race_window=0.1)
    t1 = threading.Thread(target=reader)
    t2 = threading.Thread(target=writer)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors, "Race condition during slow iteration was not caught!"

def test_explicit_reset_for_strict_mode():
    import raceguard
    raceguard.configure(strict=True)
    shared = protect({"v": 0})
    
    q = queue.Queue()

    def stage1():
        shared["v"] = 1
        q.put("done")

    def stage2():
        try:
            q.get(timeout=1.0)
        except queue.Empty:
            return
        # They synchronized via the Queue.
        # But raceguard doesn't know. To avoid strict mode false positive, call reset!
        reset(shared)
        shared["v"] = 2

    t1 = threading.Thread(target=stage1)
    t2 = threading.Thread(target=stage2)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # Explicitly reset before main thread access to avoid strict mode race
    reset(shared)
    assert shared["v"] == 2

def test_unbind():
    original = [1, 2, 3]
    proxy = protect(original)
    
    # proxy is not original, but unbind gets it back
    assert proxy is not original
    assert unbind(proxy) is original
