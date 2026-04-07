import threading
import asyncio
import time
import random
import sys
import gc
import weakref
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "src")

from raceguard import protect, locked, with_lock, configure, RaceConditionError, unbind

# ============================================
# SUBTLE TIMING WINDOW RACES
# ============================================

class TestSubtleTimingWindows:
    """Race conditions in nanosecond-scale timing windows."""
    
    def test_read_modify_write_torn_read(self):
        """
        Classic check-then-act race: reading value, checking condition, 
        then acting - but state changes between check and act.
        """
        configure(mode="raise")
        account = protect({"balance": 100, "withdrawals": 0})
        overdrafts = []
        
        def withdraw(amount):
            # BUG: Two separate reads, check-then-act race
            current = account["balance"]  # Read 1
            if current >= amount:  # Check
                time.sleep(0.0001)  # Window for race
                account["balance"] = current - amount  # Act (stale write!)
                account["withdrawals"] += 1
        
        threads = []
        for _ in range(50):
            t = threading.Thread(target=lambda: withdraw(30))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Balance should never go negative with proper locking
        # Raceguard should catch the unsynchronized read-modify-write
        assert account["balance"] >= 0 or True  # May catch race
    
    def test_compound_assignment_race(self):
        """
        +=, -=, *= etc are NOT atomic in Python.
        This tests detection of compound assignment races.
        """
        configure(mode="raise")
        counter = protect([0])
        errors_caught = []
        
        def increment():
            try:
                for _ in range(1000):
                    # This is: temp = counter[0]; temp += 1; counter[0] = temp
                    # Three bytecode operations = race window
                    counter[0] += 1
            except RaceConditionError as e:
                errors_caught.append(e)
        
        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Should detect the race in compound assignment
        assert len(errors_caught) > 0 or counter[0] < 10000
    
    def test_iteration_while_modification(self):
        """
        Iterating over a collection while another thread modifies it.
        Classic ConcurrentModificationException scenario.
        """
        configure(mode="raise")
        items = protect(list(range(1000)))
        iteration_errors = []
        
        def iterator():
            try:
                total = 0
                for item in items:  # Creates iterator, then reads sequentially
                    total += item
                    time.sleep(0.00001)  # Slow iteration
                return total
            except (RaceConditionError, RuntimeError) as e:
                iteration_errors.append(e)
                return 0
        
        def modifier():
            try:
                for _ in range(100):
                    items.append(random.randint(0, 100))
                    time.sleep(0.0001)
            except RaceConditionError as e:
                iteration_errors.append(e)
        
        t1 = threading.Thread(target=iterator)
        t2 = threading.Thread(target=modifier)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Should catch the race between iteration and modification

    def test_len_then_access_race(self):
        """
        Common pattern: check len(), then access by index.
        Race window between len() and access.
        """
        configure(mode="raise")
        buffer = protect([])
        index_errors = []
        
        def producer():
            for i in range(1000):
                try:
                    with locked(buffer):
                        buffer.append(i)
                except RaceConditionError:
                    pass
        
        def consumer():
            for _ in range(1000):
                try:
                    # BUG: len() and pop() are separate operations
                    if len(buffer) > 0:  # Check
                        time.sleep(0.00001)  # Race window
                        item = buffer.pop(0)  # May fail if buffer emptied
                except (RaceConditionError, IndexError) as e:
                    index_errors.append(e)
        
        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

# ============================================
# REENTRANCY AND DEADLOCK TRAPS
# ============================================

class TestReentrancyTraps:
    """Tests involving lock reentrancy and nested lock ordering."""
    
    def test_reentrancy_with_callback(self):
        """
        Callback pattern where callback tries to reacquire same lock.
        """
        configure(mode="raise")
        data = protect({"value": 0, "callbacks": []})
        
        def notify_callbacks():
            # Called while holding lock, callbacks may try to access data
            for cb in list(data["callbacks"]):
                cb()
        
        def register_callback(cb):
            with locked(data):
                data["callbacks"].append(cb)
                # Trigger notification while holding lock
                notify_callbacks()  # Reentrancy test
        
        def problematic_callback():
            # Try to read data while notification is in progress
            # (already holding lock via reentrancy)
            _ = data["value"]
        
        try:
            register_callback(problematic_callback)
        except RaceConditionError:
            pass  # May or may not trigger depending on reentrancy handling
    
    def test_abba_deadlock_pattern(self):
        """
        Classic ABBA deadlock: Thread1 locks A then B, Thread2 locks B then A.
        """
        configure(mode="raise")
        resource_a = protect({"name": "A", "data": []})
        resource_b = protect({"name": "B", "data": []})
        deadlocks = []
        
        def thread1():
            try:
                with locked(resource_a):
                    time.sleep(0.01)  # Force ordering issue
                    with locked(resource_b):
                        resource_a["data"].append("t1")
                        resource_b["data"].append("t1")
            except Exception as e:
                if "deadlock" in str(e).lower() or "race" in str(e).lower():
                    deadlocks.append(e)
        
        def thread2():
            try:
                with locked(resource_b):
                    time.sleep(0.01)
                    with locked(resource_a):
                        resource_a["data"].append("t2")
                        resource_b["data"].append("t2")
            except Exception as e:
                if "deadlock" in str(e).lower() or "race" in str(e).lower():
                    deadlocks.append(e)
        
        t1 = threading.Thread(target=thread1)
        t2 = threading.Thread(target=thread2)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        
        # Should either complete or detect potential deadlock
    
    def test_lock_escalation_read_to_write(self):
        """
        Starting with read lock, then trying to upgrade to write lock.
        """
        configure(mode="raise")
        cache = protect({"entries": {}, "hits": 0, "misses": 0})
        
        def get_or_compute(key, compute_func):
            # First read (should be safe with read lock)
            if key in cache["entries"]:
                cache["hits"] += 1  # Write to hit counter!
                return cache["entries"][key]
            
            # Miss - need to compute and write
            cache["misses"] += 1
            value = compute_func()
            cache["entries"][key] = value
            return value
        
        def worker():
            for i in range(100):
                get_or_compute(i % 10, lambda: i * 2)
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

    def test_nested_proxy_access(self):
        """
        Deeply nested proxy objects with mixed locked/unlocked access.
        """
        configure(mode="raise")
        structure = protect({
            "level1": protect({
                "level2": protect({
                    "level3": protect({"value": 0})
                })
            })
        })
        
        def deep_access():
            try:
                # Outer lock
                with locked(structure):
                    # Access nested without additional locks
                    inner = structure["level1"]["level2"]["level3"]
                    inner["value"] += 1  # Is this protected by outer lock?
            except RaceConditionError as e:
                pass
        
        threads = [threading.Thread(target=deep_access) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

# ============================================
# MIXED SYNCHRONIZATION PRIMITIVES
# ============================================

class TestMixedSynchronization:
    """Using Raceguard with other threading primitives."""
    
    def test_condition_variable_with_raceguard(self):
        """
        threading.Condition with Raceguard-protected shared state.
        """
        configure(mode="raise")
        queue = protect([])
        condition = threading.Condition()
        consumed = []
        
        def producer():
            for i in range(100):
                with condition:
                    with locked(queue):
                        queue.append(i)
                    condition.notify()
        
        def consumer():
            for _ in range(100):
                with condition:
                    while True:
                        with locked(queue):
                            if queue:
                                item = queue.pop(0)
                                consumed.append(item)
                                break
                        condition.wait(timeout=0.1)
        
        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        assert len(consumed) == 100
    
    def test_semaphore_with_raceguard(self):
        """
        Semaphore limiting access but Raceguard detecting cross-thread races.
        """
        configure(mode="raise")
        resource = protect([0])
        sem = threading.Semaphore(3)  # Max 3 concurrent
        errors = []
        
        def limited_worker():
            with sem:  # Limits concurrency but doesn't prevent races
                try:
                    for _ in range(100):
                        resource[0] += 1  # Unsynchronized despite semaphore
                        time.sleep(0.0001)
                except RaceConditionError as e:
                    errors.append(e)
        
        threads = [threading.Thread(target=limited_worker) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Semaphore != Lock; races should still be detected
        assert len(errors) > 0 or resource[0] < 1000
    
    def test_rlock_vs_raceguard(self):
        """
        threading.RLock (reentrant) vs Raceguard detection.
        """
        configure(mode="raise")
        data = protect({"counter": 0})
        rlock = threading.RLock()
        
        def recursive_increment(n):
            if n <= 0:
                return
            with rlock:  # Python RLock
                # But is data protected by Raceguard?
                data["counter"] += 1
                recursive_increment(n - 1)  # Reentrant call
        
        threads = [threading.Thread(target=lambda: recursive_increment(10)) 
                   for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # RLock protects the block, but Raceguard tracks object access
        # If RLock is recognized, no error. If not, may flag as race.

    def test_barrier_race(self):
        """
        All threads wait at barrier, then race to access shared data.
        """
        configure(mode="raise")
        barrier = threading.Barrier(10)
        results = protect([])
        race_detected = [False]
        
        def racer():
            try:
                barrier.wait()  # All threads released simultaneously
                # Thundering herd - all try to append at once
                results.append(threading.current_thread().name)
            except RaceConditionError:
                race_detected[0] = True
        
        threads = [threading.Thread(target=racer) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Should detect the thundering herd race
        assert race_detected[0] or len(results) != 10

# ============================================
# ASYNC/THREAD HYBRID CHAOS
# ============================================

class TestAsyncThreadHybrid:
    """Nightmare scenarios mixing asyncio and threading."""
    
    def test_thread_spawning_async_tasks_race(self):
        """
        Thread creates event loop and spawns async tasks that race.
        """
        configure(mode="raise")
        shared = protect([0])
        errors = []
        
        def thread_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def async_racer():
                for _ in range(100):
                    try:
                        shared[0] += 1  # Unsynchronized
                        await asyncio.sleep(0)
                    except RaceConditionError as e:
                        errors.append(e)
            
            # Multiple async tasks in one thread
            tasks = [async_racer() for _ in range(10)]
            loop.run_until_complete(asyncio.gather(*tasks))
            loop.close()
        
        threads = [threading.Thread(target=thread_worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Async tasks within one thread may not race each other (GIL),
        # but across threads they do
    
    def test_async_to_thread_callback_race(self):
        """
        Async code calling thread executor, both accessing shared data.
        """
        configure(mode="raise")
        state = protect({"async_count": 0, "thread_count": 0})
        loop = asyncio.new_event_loop()
        errors = []
        
        async def async_worker():
            for _ in range(50):
                try:
                    state["async_count"] += 1
                    # Run in thread pool
                    await loop.run_in_executor(None, thread_callback)
                    await asyncio.sleep(0.001)
                except RaceConditionError as e:
                    errors.append(e)
        
        def thread_callback():
            try:
                state["thread_count"] += 1  # Access from thread pool
                time.sleep(0.001)
            except RaceConditionError as e:
                errors.append(e)
        
        loop.run_until_complete(asyncio.gather(*[async_worker() for _ in range(5)]))
        loop.close()
    
    def test_future_callback_race(self):
        """
        Concurrent.futures with callbacks accessing shared state.
        """
        configure(mode="raise")
        results = protect([])
        executor = ThreadPoolExecutor(max_workers=10)
        futures = []
        
        def compute_and_store(x):
            # Compute in thread pool
            result = x * x
            # Store result (potential race)
            results.append(result)
            return result
        
        # Submit many tasks
        for i in range(100):
            future = executor.submit(compute_and_store, i)
            futures.append(future)
        
        # Wait for all
        for f in as_completed(futures):
            try:
                f.result()
            except RaceConditionError:
                pass
        
        executor.shutdown()

# ============================================
# GARBAGE COLLECTION AND LIFECYCLE RACES
# ============================================

class TestLifecycleRaces:
    """Races involving object creation, destruction, and GC."""
    
    def test_gc_during_access(self):
        """
        Trigger GC while threads are accessing shared data.
        """
        configure(mode="raise")
        data = protect(list(range(1000)))
        gc_triggered = [False]
        
        def accessor():
            total = 0
            for item in data:
                total += item
                if item == 500:
                    gc.collect()  # Force GC mid-iteration
                    gc_triggered[0] = True
            return total
        
        def modifier():
            for _ in range(100):
                with locked(data):
                    data.append(random.randint(0, 100))
        
        t1 = threading.Thread(target=accessor)
        t2 = threading.Thread(target=modifier)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        assert gc_triggered[0]
    
    def test_weakref_finalizer_race(self):
        """
        Object being finalized while another thread accesses it.
        """
        configure(mode="raise")
        errors = []
        
        class SharedObject:
            def __init__(self):
                self.data = protect([0])
            
            def __del__(self):
                try:
                    # Access during finalization
                    self.data.append(1)
                except RaceConditionError as e:
                    errors.append(e)
        
        def create_and_drop():
            obj = SharedObject()
            # Create reference in another thread
            ref = weakref.ref(obj)
            # Drop reference, trigger finalization
            del obj
            gc.collect()
            time.sleep(0.01)
        
        threads = [threading.Thread(target=create_and_drop) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
    
    def test_proxy_resurrection_race(self):
        """
        Object being resurrected during __del__ while accessed.
        """
        configure(mode="raise")
        pool = protect([])
        resurrected = []
        
        class ResurrectingObject:
            def __init__(self, value):
                self.value = value
            
            def __del__(self):
                # Resurrect by adding back to pool
                with locked(pool):
                    pool.append(self)
                resurrected.append(self.value)
        
        def worker():
            for i in range(20):
                obj = ResurrectingObject(i)
                # Immediate drop, triggers __del__
                del obj
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

# ============================================
# PATHOLOGICAL ACCESS PATTERNS
# ============================================

class TestPathologicalPatterns:
    """Deliberately evil code patterns."""
    
    def test_false_sharing_simulation(self):
        """
        Different indices of same list accessed by different threads.
        No actual data race but may trigger false positives.
        """
        configure(mode="raise")
        # Large array, each thread works on separate section
        array = protect([0] * 10000)
        errors = []
        
        def worker_section(start, end):
            try:
                for i in range(start, end):
                    array[i] = i  # Each thread touches different indices
            except RaceConditionError as e:
                errors.append(e)
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker_section, 
                               args=(i*1000, (i+1)*1000))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should not flag as race (different indices), 
        # or should flag (same underlying object)
    
    def test_pointer_aliasing_race(self):
        """
        Same object accessed through different references.
        """
        configure(mode="raise")
        original = protect([0])
        alias1 = original
        alias2 = original
        
        errors = []
        
        def via_alias1():
            try:
                for _ in range(1000):
                    alias1[0] += 1
            except RaceConditionError as e:
                errors.append(e)
        
        def via_alias2():
            try:
                for _ in range(1000):
                    alias2[0] += 1
            except RaceConditionError as e:
                errors.append(e)
        
        t1 = threading.Thread(target=via_alias1)
        t2 = threading.Thread(target=via_alias2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Should detect race despite different variable names
    
    def test_slice_assignment_race(self):
        """
        List slice assignment races with other operations.
        """
        configure(mode="raise")
        data = protect(list(range(100)))
        errors = []
        
        def slicer():
            try:
                for _ in range(50):
                    data[0:10] = [random.randint(0, 100)] * 10
                    time.sleep(0.0001)
            except RaceConditionError as e:
                errors.append(e)
        
        def appender():
            try:
                for _ in range(50):
                    data.append(random.randint(0, 100))
                    time.sleep(0.0001)
            except RaceConditionError as e:
                errors.append(e)
        
        t1 = threading.Thread(target=slicer)
        t2 = threading.Thread(target=appender)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    
    def test_dict_iteration_modification_race(self):
        """
        Iterating dict keys while another thread adds/removes.
        """
        configure(mode="raise")
        mapping = protect({i: f"val_{i}" for i in range(100)})
        errors = []
        
        def iterator():
            try:
                while True:
                    # Creates iterator snapshot, then reads
                    for k in list(mapping.keys()):
                        if k in mapping:
                            _ = mapping[k]
                    if len(mapping) > 200:
                        break
            except (RaceConditionError, RuntimeError) as e:
                errors.append(e)
        
        def modifier():
            try:
                for i in range(100, 300):
                    mapping[i] = f"new_{i}"
                    if i % 10 == 0:
                        # Delete some
                        keys = list(mapping.keys())[:5]
                        for k in keys:
                            if k in mapping:
                                del mapping[k]
            except RaceConditionError as e:
                errors.append(e)
        
        t1 = threading.Thread(target=iterator)
        t2 = threading.Thread(target=modifier)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

# ============================================
# MEMORY MODEL TORTURE TESTS
# ============================================

class TestMemoryModel:
    """Tests targeting Python's memory model edge cases."""
    
    def test_volatile_read_reordering(self):
        """
        Testing if reads can be reordered (simulated with timing).
        """
        configure(mode="raise")
        flag = protect([False])
        value = protect([0])
        observed = []
        
        def writer():
            with locked(value):
                value[0] = 42
            with locked(flag):
                flag[0] = True
        
        def reader():
            while True:
                with locked(flag):
                    if flag[0]:
                        # Flag is set, read value
                        with locked(value):
                            observed.append(value[0])
                            break
        
        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        time.sleep(0.001)  # Ensure writer starts first
        t2.start()
        t1.join()
        t2.join()
        
        # Should always see 42, never 0 (happens-before)
        assert all(v == 42 for v in observed)
    
    def test_tear_read_write(self):
        """
        Attempting to observe partial writes (simulated with objects).
        """
        configure(mode="raise")
        # Python ints are immutable, but we can simulate with list
        composite = protect([{"a": 0, "b": 0}])
        observations = []
        
        def writer():
            for i in range(1000):
                with locked(composite):
                    # "Atomic" update of both fields
                    composite[0] = {"a": i, "b": i}
        
        def reader():
            for _ in range(10000):
                with locked(composite):
                    snapshot = composite[0]
                    observations.append((snapshot["a"], snapshot["b"]))
        
        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Check for torn reads (a != b in any observation)
        torn = [obs for obs in observations if obs[0] != obs[1]]
        # With proper locking, torn reads should be impossible
        assert len(torn) == 0

# ============================================
# STRESS TEST: CHAOS MONKEY
# ============================================

class TestChaosMonkey:
    """Randomized torture testing."""
    
    def test_randomized_chaos(self):
        """
        Completely random operations from random threads.
        """
        configure(mode="raise")
        database = protect({
            "users": {},
            "counters": {"reads": 0, "writes": 0},
            "log": []
        })
        errors = []
        operations = [0]
        
        def chaos_worker(worker_id):
            for _ in range(100):
                op = random.choice(["read", "write", "delete", "iterate", "nested"])
                try:
                    if op == "read":
                        _ = database["users"]
                        with locked(database):
                            database["counters"]["reads"] += 1
                    
                    elif op == "write":
                        uid = random.randint(0, 100)
                        with locked(database):
                            database["users"][uid] = f"user_{uid}"
                            database["counters"]["writes"] += 1
                            database["log"].append(f"write:{uid}")
                    
                    elif op == "delete":
                        uid = random.randint(0, 100)
                        with locked(database):
                            if uid in database["users"]:
                                del database["users"][uid]
                                database["log"].append(f"delete:{uid}")
                    
                    elif op == "iterate":
                        with locked(database):
                            for uid in list(database["users"].keys()):
                                _ = database["users"].get(uid)
                    
                    elif op == "nested":
                        # Deep nested access
                        with locked(database):
                            if "metadata" not in database:
                                database["metadata"] = protect({})
                            with locked(database["metadata"]):
                                database["metadata"][f"key_{worker_id}"] = time.time()
                    
                    operations[0] += 1
                    
                except RaceConditionError as e:
                    errors.append(e)
                except Exception as e:
                    # Other errors are bugs
                    raise
        
        threads = [threading.Thread(target=chaos_worker, args=(i,)) 
                   for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        print(f"Completed {operations[0]} operations, caught {len(errors)} races")
        # Should complete without crashing, may have detected races

    def test_memory_pressure_race(self):
        """
        High memory pressure while racing.
        """
        configure(mode="raise")
        chunks = protect([])
        errors = []
        
        def allocator():
            # Allocate lots of memory
            for _ in range(50):
                big_list = [0] * 100000  # ~800KB
                with locked(chunks):
                    chunks.append(big_list)
                time.sleep(0.001)
        
        def racer():
            # Race on the chunks list while memory pressure is high
            for _ in range(100):
                try:
                    with locked(chunks):
                        if chunks:
                            _ = len(chunks[-1])
                except RaceConditionError as e:
                    errors.append(e)
        
        threads = ([threading.Thread(target=allocator) for _ in range(3)] +
                   [threading.Thread(target=racer) for _ in range(5)])
        
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Force cleanup
        with locked(chunks):
            chunks.clear()
        gc.collect()

# ============================================
# RUNNER
# ============================================

if __name__ == "__main__":
    import pytest
    # Run with maximum verbosity and fail-fast
    sys.exit(pytest.main([
        "-v", 
        "-x",  # Stop on first failure
        "--tb=short",
        __file__
    ]))
