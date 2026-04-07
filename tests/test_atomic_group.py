import threading
import time
import pytest
from raceguard import protect, configure, locked, AtomicGroup, RaceConditionError

class DataObj:
    def __init__(self, val=0):
        self.val = val

def test_atomic_group_basic_sync():
    """Verify that AtomicGroup correctly holds multiple locks."""
    a = protect(DataObj(0))
    b = protect(DataObj(0))
    group = AtomicGroup(a, b)
    
    with locked(group):
        a.val = 1
        b.val = 2
        
    assert a.val == 1
    assert b.val == 2

def test_atomic_group_semantic_race():
    """Verify that touching a group member while group is locked by another thread triggers an error."""
    configure(mode="raise", strict=True)
    a = protect(DataObj(0))
    b = protect(DataObj(0))
    group = AtomicGroup(a, b)
    
    error_caught = []
    
    def blocker():
        with locked(group):
            time.sleep(0.3)
            
    def attacker():
        time.sleep(0.1) # Wait for blocker
        try:
            # This should fail because 'group' is locked by 'blocker'
            _ = a.val
        except RaceConditionError as e:
            error_caught.append(e)

    t1 = threading.Thread(target=blocker)
    t2 = threading.Thread(target=attacker)
    
    t1.start()
    t2.start()
    
    t2.join()
    t1.join()
    
    assert len(error_caught) == 1
    assert "SEMANTIC Race condition" in str(error_caught[0])

def test_atomic_group_deadlock_prevention():
    """Verify that groups involving the same objects in different order don't deadlock."""
    configure(mode="raise")
    x = protect(DataObj(0))
    y = protect(DataObj(0))
    
    # Internal sorting in _acquire_all prevents deadlock
    group1 = AtomicGroup(x, y)
    group2 = AtomicGroup(y, x)
    
    failures = []

    def worker(group, obj):
        try:
            for _ in range(50):
                with locked(group):
                    obj.val += 1
                    time.sleep(0.001)
        except Exception as e:
            failures.append(e)

    t1 = threading.Thread(target=worker, args=(group1, x))
    t2 = threading.Thread(target=worker, args=(group2, y))
    
    t1.start()
    t2.start()
    
    t1.join(timeout=5)
    t2.join(timeout=5)
    
    assert not t1.is_alive(), "Threads deadlocked!"
    assert not t2.is_alive(), "Threads deadlocked!"
    # Note: they might trigger semantic races if groups overlap, which is acceptable detection
    # but for a 'deadlock test' we want to see them finish.

def test_atomic_group_overlap_contention():
    """Verify that two groups sharing an object correctly contend."""
    configure(mode="raise")
    shared = protect(DataObj(0))
    a = protect(DataObj(0))
    b = protect(DataObj(0))
    
    # Both groups share 'shared'
    group1 = AtomicGroup(shared, a)
    group2 = AtomicGroup(shared, b) 
    
    error_caught = []
    
    def worker1():
        with locked(group1):
            time.sleep(0.4)

    def worker2():
        time.sleep(0.1)
        try:
            # Touching 'shared' while 'group1' holds its lock should fail
            # because 'shared' was last assigned to 'group2', BUT 
            # actually if we want overlap we need multiple groups.
            # In our current Impl, 'shared' belongs to group2.
            _ = shared.val
        except RaceConditionError as e:
            error_caught.append(e)

    t1 = threading.Thread(target=worker1)
    t2 = threading.Thread(target=worker2)
    
    t1.start()
    t2.start()
    
    t2.join()
    t1.join()
    
    assert len(error_caught) == 1
