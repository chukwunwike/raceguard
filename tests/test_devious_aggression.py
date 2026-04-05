import pytest
import threading
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from collections import deque

from raceguard import protect, configure, clear_warnings, RaceConditionError, locked, with_lock

@pytest.fixture(autouse=True)
def reset_config_devious():
    configure(enabled=True, race_window=0.01, mode="raise", max_warnings=5000)
    clear_warnings()
    yield
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000)
    clear_warnings()

class TestDeadlockAssassination:
    
    def test_circular_lock_evasion(self):
        """Attempts to induce deadlock by locking proxies in inverse orders."""
        a = protect([])
        b = protect([])
        c = protect([])
        d = protect([])
        success = [False] * 4
        barrier = threading.Barrier(4)

        def t1_job():
            barrier.wait()
            with locked(a, b, c, d):
                success[0] = True
        
        def t2_job():
            barrier.wait()
            with locked(d, c, b, a):
                success[1] = True
                
        def t3_job():
            barrier.wait()
            with locked(b, d, a, c):
                success[2] = True
                
        def t4_job():
            barrier.wait()
            with locked(c, a, d, b):
                success[3] = True

        threads = [
            threading.Thread(target=t1_job),
            threading.Thread(target=t2_job),
            threading.Thread(target=t3_job),
            threading.Thread(target=t4_job)
        ]
        
        for t in threads: t.start()
        for t in threads: t.join(timeout=2.0)
        
        assert all(success), "Deadlock detected! Threads did not finish successfully."

    def test_recursive_reentrant_locking(self):
        """Recursively lock the same proxy deeply to ensure no re-entrancy bugs."""
        a = protect([0])
        success = False
        
        def recursive_locker(depth):
            if depth == 0:
                a[0] += 1
                return
            with locked(a):
                recursive_locker(depth - 1)
                
        def threaded_recursive_runner():
            recursive_locker(20)
            
        t1 = threading.Thread(target=threaded_recursive_runner)
        t2 = threading.Thread(target=threaded_recursive_runner)
        t1.start()
        t2.start()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)
        
        assert a[0] == 2, "Re-entrant locking failed or caused corruption."

    def test_nested_decorator_reentrancy(self):
        """Recursively lock through decorators to guarantee thread safety without deadlock."""
        a = protect([0])

        @with_lock(a)
        def recurse_add(depth):
            if depth > 0:
                recurse_add(depth - 1)
            else:
                a[0] += 1
                
        threads = [threading.Thread(target=recurse_add, args=(10,)) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=2.0)
        
        assert a[0] == 5

class TestMassiveConcurrencyBarrages:

    def test_unlocked_executor_barrage_raises_race(self):
        """Submit 1000 tasks that mutate a list unprotected to ensure RaceConditionError is raised reliably."""
        configure(race_window=2.0)
        shared = protect([])
        errors = deque()
        
        def unlocked_mutator():
            try:
                shared.append(1)
            except RaceConditionError as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=200) as ext:
            futures = [ext.submit(unlocked_mutator) for _ in range(1000)]
            for f in futures: f.result()
            
        assert len(errors) > 0, "Failed to catch race condition in massive barrage."

    def test_locked_executor_barrage_safe(self):
        """Submit 1000 tasks that mutate a list PROTECTED to ensure no races occur."""
        shared = protect([])
        errors = deque()
        
        def locked_mutator():
            try:
                with locked(shared):
                    shared.append(1)
            except RaceConditionError as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=200) as ext:
            futures = [ext.submit(locked_mutator) for _ in range(1000)]
            for f in futures: f.result()
            
        assert len(errors) == 0, f"False positive race detected: {errors[0]}"
        assert len(shared) == 1000

    def test_massive_dict_comprehension_barrage(self):
        """Overlapping inserts and pops on a shared dictionary via threads."""
        configure(mode="warn", max_warnings=5000, race_window=2.0)
        shared = protect({})
        
        def dict_assault(start, end):
            for i in range(start, end):
                shared[f"key_{i}"] = i
                if i % 2 == 0:
                    shared.pop(f"key_{i}", None)

        threads = []
        for i in range(0, 500, 10):
            t = threading.Thread(target=dict_assault, args=(i, i+10))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        w = clear_warnings()
        assert len(w) > 0, "Warn mode failed to capture dictionary races in heavy barrage."
        
class TestDeepRecursionAndNestedProxies:
    
    def test_nested_proxy_matryoshka(self):
        """Protecting a list that contains a protected dict that contains a protected set."""
        shared = protect([protect({"inner": protect({1, 2, 3})})])
        errors = deque()
        barrier = threading.Barrier(3)
        
        def deeply_nested_assault(val):
            try:
                barrier.wait()
                shared[0]["inner"].add(val)
            except RaceConditionError as e:
                errors.append(e)
                
        threads = [threading.Thread(target=deeply_nested_assault, args=(val,)) for val in [4, 5, 6]]
        for t in threads: t.start()
        for t in threads: t.join()
        
        assert len(errors) > 0, "Failed to detect race on nested proxy."
        
    def test_double_wrapped_proxy(self):
        """Test a proxy wrapped inside another proxy directly."""
        inner = protect([0])
        outer = protect(inner)
        errors = deque()
        barrier = threading.Barrier(2)
        
        def outer_assault():
            try:
                barrier.wait()
                outer.append(1)
            except RaceConditionError as e:
                errors.append(e)
                
        t1 = threading.Thread(target=outer_assault)
        t2 = threading.Thread(target=outer_assault)
        t1.start(); t2.start()
        t1.join(); t2.join()
        
        assert len(errors) > 0

class TestGILDroppingSabotage:
    
    def test_context_switch_during_read_modify_write(self):
        """Forcing a context switch (sleep 0) mid-operation to simulate aggressive GIL preemption."""
        configure(race_window=0.5)
        shared = protect([0])
        errors = deque()
        
        def preemptive_worker():
            try:
                # Read, sleep 0 to drop GIL, write
                val = shared[0]
                time.sleep(0)  
                shared[0] = val + 1
            except RaceConditionError as e:
                errors.append(e)
                
        threads = [threading.Thread(target=preemptive_worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Read-modify-write without locks is a race condition.
        # But wait, shared[0] read and shared[0]= write are separate operations.
        # It's an application level race, but raceguard detects the overlapping unprotected access to the list!
        assert len(errors) > 0

    def test_iterator_gil_drop_disruption(self):
        """Using a protected list iterator while yielding control back, combined with concurrent mutations."""
        configure(race_window=0.5)
        # Note: Raceguard tracks operations on the list, iterating creates an iterator. 
        # Modifying a list during iteration raises RuntimeError in native python, but let's test the race.
        shared = protect([1, 2, 3, 4, 5])
        errors = deque()
        
        def iterator_worker():
            try:
                for x in shared:
                    time.sleep(0.01)
            except (RuntimeError, RaceConditionError) as e:
                errors.append(e)
                
        def mutator():
            try:
                time.sleep(0.02)
                shared.append(6)
            except RaceConditionError as e:
                errors.append(e)
                
        t1 = threading.Thread(target=iterator_worker)
        t2 = threading.Thread(target=mutator)
        t1.start(); t2.start()
        t1.join(); t2.join()
        
        assert len(errors) > 0, "Did not catch iteration/mutation race."

class TestResourceExhaustionAndLogging:

    def test_maximum_warnings_limit_truncation(self):
        """Assaulting the warn buffer beyond its limit to test truncation logic."""
        configure(mode="warn", max_warnings=100, race_window=2.0)
        shared = protect([0])
        
        def spam_warnings():
            for _ in range(500):
                # Force many accesses from different threads rapidly
                shared.append(1)

        with ThreadPoolExecutor(max_workers=50) as ext:
            futures = [ext.submit(spam_warnings) for _ in range(50)]
            for f in futures: f.result()
            
        w = clear_warnings()
        assert len(w) == 100, f"Expected exactly 100 warnings due to limit, got {len(w)}"
        
    def test_dynamic_configuration_toggling_blitz(self):
        """Rapidly toggle configuration between raise/warn/log while threads are assaulting."""
        configure(mode="warn", max_warnings=10000, race_window=2.0)
        shared = protect([])
        errors = deque()
        keep_running = True
        
        def config_switcher():
            modes = ["log", "warn", "raise"]
            idx = 0
            while keep_running:
                configure(mode=modes[idx % 3])
                idx += 1
                time.sleep(0.01)
                
        def assaulter():
            while keep_running:
                try:
                    shared.append(1)
                except RaceConditionError as e:
                    errors.append(e)
                time.sleep(0.005)
                
        switcher = threading.Thread(target=config_switcher)
        assaulters = [threading.Thread(target=assaulter) for _ in range(10)]
        
        switcher.start()
        for t in assaulters: t.start()
        
        time.sleep(0.5)
        keep_running = False
        
        switcher.join()
        for t in assaulters: t.join()
        
        # Depending on when it hit 'raise' mode, it should have captured some RaceConditionErrors.
        # But we don't strictly assert len > 0 if timing was unlucky, though 0.5s is plenty.
        assert len(errors) > 0 or len(clear_warnings()) > 0
        
    def test_extreme_tight_race_window(self):
        """Testing functionality with an extremely tight microsecond race window."""
        configure(race_window=0.0001, mode="raise") # 0.1ms window
        shared = protect([0])
        errors = deque()
        barrier = threading.Barrier(2)
        
        def tight_worker():
            try:
                barrier.wait()
                shared.append(1)
            except RaceConditionError as e:
                errors.append(e)
                
        t1 = threading.Thread(target=tight_worker)
        t2 = threading.Thread(target=tight_worker)
        t1.start(); t2.start()
        t1.join(); t2.join()
        
        assert len(errors) > 0

    def test_del_block_concurrent_mutation(self):
        """Testing tricky __del__ destructors triggering races in bg threads."""
        configure(race_window=0.5, mode="warn", max_warnings=1000)
        shared = protect([])
        
        class NastyDestructor:
            def __del__(self):
                shared.append("deleted")
                
        def alloc_and_free():
            obj = NastyDestructor()
            del obj
            
        t1 = threading.Thread(target=alloc_and_free)
        t2 = threading.Thread(target=alloc_and_free)
        t1.start(); t2.start()
        t1.join(); t2.join()
        
        # It's possible for python GC to run these non-deterministically.
        # If they ran close enough, warnings > 0. Since GC is immediate for standard CPython `del obj`, 
        # these WILL race!
        w = clear_warnings()
        assert len(w) > 0

    def test_finally_block_explosion(self):
        """Mutating in standard flow and mutating in a finally block simultaneously."""
        configure(race_window=0.5)
        shared = protect([])
        errors = deque()
        barrier = threading.Barrier(2)
        
        def finally_worker():
            try:
                barrier.wait()
                raise ValueError("Oops")
            except Exception:
                pass
            finally:
                try:
                    shared.append(1)
                except RaceConditionError as e:
                    errors.append(e)
                    
        t1 = threading.Thread(target=finally_worker)
        t2 = threading.Thread(target=finally_worker)
        t1.start(); t2.start()
        t1.join(); t2.join()
        
        assert len(errors) > 0
