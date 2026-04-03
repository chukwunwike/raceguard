import threading
import asyncio
import time
import random
import sys
import gc
import weakref
import struct
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import deque
import mmap
import os
import tempfile

sys.path.insert(0, "src")

from raceguard import protect, locked, with_lock, configure, RaceConditionError, unbind

# ============================================
# DISTRIBUTED STATE MACHINE RACES
# ============================================

class TestDistributedStateMachines:
    """
    State machines where the race is distributed across multiple objects
    and only manifests in specific state transitions.
    """
    
    def test_byzantine_generals_consensus_race(self):
        """
        Distributed consensus with traitorous threads.
        Race only appears when >f+1 threads disagree on state.
        """
        configure(mode="raise")
        
        # Simulate 7 generals, need 5 for consensus
        n_generals = 7
        f_faulty = 2
        
        # Each general has their own view
        generals = [protect({
            "id": i,
            "round": 0,
            "value": None,
            "votes": {},
            "decided": False
        }) for i in range(n_generals)]
        
        # Shared message bus (the actual race target)
        message_bus = protect(deque(maxlen=1000))
        consensus_reached = [0]
        race_detected = [False]
        
        def byzantine_general(gid, is_faulty):
            try:
                for round_num in range(10):
                    # Propose value
                    proposal = random.choice(["attack", "retreat"]) if is_faulty else "attack"
                    
                    # Broadcast to bus (RACE: unsynchronized broadcast)
                    message_bus.append({
                        "from": gid,
                        "round": round_num,
                        "value": proposal
                    })
                    
                    # Collect votes from bus
                    my_votes = {}
                    for msg in list(message_bus):
                        if msg["round"] == round_num and msg["from"] != gid:
                            my_votes[msg["from"]] = msg["value"]
                    
                    # Decide based on majority
                    if len(my_votes) >= n_generals - f_faulty - 1:
                        values = list(my_votes.values())
                        attack_count = values.count("attack")
                        retreat_count = values.count("retreat")
                        
                        # BUG: Decision made based on potentially stale view
                        # Another thread might be modifying message_bus right now
                        decision = "attack" if attack_count > retreat_count else "retreat"
                        
                        with locked(generals[gid]):
                            generals[gid]["value"] = decision
                            generals[gid]["decided"] = True
                            generals[gid]["round"] = round_num
                        
                        if all(g["decided"] and g["value"] == decision 
                               for g in generals if not g.get("faulty")):
                            consensus_reached[0] += 1
                    
                    time.sleep(0.0001 * random.random())
                    
            except RaceConditionError:
                race_detected[0] = True
        
        threads = []
        for i in range(n_generals):
            t = threading.Thread(target=byzantine_general, 
                               args=(i, i < f_faulty))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Race in message_bus should be detected
        print(f"Consensus reached: {consensus_reached[0]}, Race detected: {race_detected[0]}")
    
    def test_lamport_clock_drift_race(self):
        """
        Logical clocks that appear consistent but have causality violations.
        Race in the happens-before relationship.
        """
        configure(mode="raise")
        
        events = protect([])  # Global event log
        vector_clocks = [protect({i: 0 for i in range(5)}) for _ in range(5)]
        causality_violations = []
        
        def process_event(pid, event_type):
            try:
                # Increment own clock
                my_clock = vector_clocks[pid]
                
                # RACE: Read-modify-write on clock without lock
                current = my_clock.copy()
                current[pid] += 1
                time.sleep(0.00001)  # Window for interleaving
                for k, v in current.items():
                    my_clock[k] = v
                
                # Create event with timestamp
                event = {
                    "pid": pid,
                    "type": event_type,
                    "timestamp": dict(my_clock),  # May be inconsistent!
                    "data": random.randint(0, 1000)
                }
                
                # RACE: Append to event log
                events.append(event)
                
                # Check causality (may see partial writes)
                if len(events) > 1:
                    prev = events[-2]
                    curr = events[-1]
                    
                    # Check if prev happened-before curr
                    prev_ts = prev["timestamp"]
                    curr_ts = curr["timestamp"]
                    
                    # Vector clock comparison
                    happens_before = all(curr_ts.get(k, 0) >= prev_ts.get(k, 0) 
                                        for k in set(prev_ts) | set(curr_ts))
                    concurrent = not happens_before and not all(
                        prev_ts.get(k, 0) >= curr_ts.get(k, 0) 
                        for k in set(prev_ts) | set(curr_ts)
                    )
                    
                    if not happens_before and not concurrent:
                        causality_violations.append((prev, curr))
                        
            except RaceConditionError as e:
                causality_violations.append(("RACE_DETECTED", e))
        
        threads = []
        for pid in range(5):
            for _ in range(20):
                t = threading.Thread(target=process_event, 
                                   args=(pid, f"event_{random.randint(0, 100)}"))
                threads.append(t)
                t.start()
        
        for t in threads:
            t.join()
        
        print(f"Causality violations: {len(causality_violations)}")
    
    def test_two_phase_commit_orphan_race(self):
        """
        2PC coordinator crashes, leaving participants in uncertain state.
        Race between recovery and new transaction.
        """
        configure(mode="raise")
        
        coordinator = protect({
            "status": "INIT",  # INIT, PREPARE, COMMIT, ABORT
            "participants": [0, 1, 2],
            "votes": {},
            "decision": None
        })
        
        participants = [protect({
            "id": i,
            "local_state": "INIT",
            "prepared_value": None,
            "committed": False
        }) for i in range(3)]
        
        race_detected = [False]
        
        def coordinator_thread():
            try:
                # Phase 1: Prepare
                with locked(coordinator):
                    coordinator["status"] = "PREPARE"
                
                # RACE: Coordinator sends prepare but doesn't lock participants
                for pid in coordinator["participants"]:
                    participants[pid]["local_state"] = "PREPARING"
                    participants[pid]["prepared_value"] = f"data_{random.randint(0, 100)}"
                
                # Simulate crash here - coordinator dies
                time.sleep(0.001)
                
                # Recovery: another coordinator takes over
                with locked(coordinator):
                    if coordinator["status"] == "PREPARE":
                        # Check participant votes
                        votes = [participants[p]["local_state"] for p in range(3)]
                        if all(v == "PREPARED" for v in votes):
                            coordinator["decision"] = "COMMIT"
                        else:
                            coordinator["decision"] = "ABORT"
                        
            except RaceConditionError:
                race_detected[0] = True
        
        def participant_thread(pid):
            try:
                # Wait for prepare
                while participants[pid]["local_state"] == "INIT":
                    time.sleep(0.0001)
                
                # Vote prepared
                # RACE: Writing state without coordination
                participants[pid]["local_state"] = "PREPARED"
                
                # Wait for decision
                time.sleep(0.01)
                
                # Apply decision (may be None due to race)
                if coordinator.get("decision") == "COMMIT":
                    participants[pid]["committed"] = True
                    
            except RaceConditionError:
                race_detected[0] = True
        
        threads = [threading.Thread(target=coordinator_thread)]
        for i in range(3):
            threads.append(threading.Thread(target=participant_thread, args=(i,)))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Race detected: {race_detected[0]}")

# ============================================
# SPECULATIVE EXECUTION & MEMORY BARRIERS
# ============================================

class TestSpeculativeExecution:
    """
    Races that exploit CPU speculative execution and memory ordering.
    """
    
    def test_load_store_reordering_detection(self):
        """
        Test if loads and stores can be reordered (simulated).
        Classic Dekker's algorithm failure case.
        """
        configure(mode="raise")
        
        flag_a = protect([0])
        flag_b = protect([0])
        turn = protect([0])
        critical_section_count = [0]
        race_count = [0]
        
        def thread_a():
            for _ in range(1000):
                try:
                    # Enter protocol
                    flag_a[0] = 1
                    turn[0] = 1
                    
                    # Memory barrier simulation
                    while flag_b[0] == 1 and turn[0] == 1:
                        pass  # Spin
                    
                    # Critical section
                    critical_section_count[0] += 1
                    
                    # Exit
                    flag_a[0] = 0
                    
                except RaceConditionError:
                    race_count[0] += 1
        
        def thread_b():
            for _ in range(1000):
                try:
                    flag_b[0] = 1
                    turn[0] = 0
                    
                    while flag_a[0] == 1 and turn[0] == 0:
                        pass
                    
                    critical_section_count[0] += 1
                    
                    flag_b[0] = 0
                    
                except RaceConditionError:
                    race_count[0] += 1
        
        t1 = threading.Thread(target=thread_a)
        t2 = threading.Thread(target=thread_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        print(f"Races detected: {race_count[0]}")
    
    def test_double_checked_locking_failure(self):
        """
        Classic broken double-checked locking pattern.
        Race between initialization check and use.
        """
        configure(mode="raise")
        
        class SingletonResource:
            def __init__(self):
                self.data = list(range(1000))  # Expensive init
                time.sleep(0.001)  # Simulate slow init
        
        resource = protect([None])
        init_count = [0]
        race_detected = [False]
        
        def get_resource():
            try:
                # First check (no lock) - RACE HERE
                if resource[0] is None:
                    # Second check with lock
                    with locked(resource):
                        if resource[0] is None:
                            instance = SingletonResource()
                            init_count[0] += 1
                            resource[0] = instance
                            
                return resource[0]
                
            except RaceConditionError:
                race_detected[0] = True
                return None
        
        threads = [threading.Thread(target=get_resource) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Init count: {init_count[0]}, Race detected: {race_detected[0]}")
    
    def test_tear_read_64bit_simulation(self):
        """
        Simulate reading 64-bit value as two 32-bit halves (tear).
        """
        configure(mode="raise")
        
        high_low = protect([0, 0])
        tears_observed = []
        
        def writer():
            for i in range(10000):
                with locked(high_low):
                    if i % 2 == 0:
                        high_low[0] = 0xFFFFFFFF
                        high_low[1] = 0x00000000
                    else:
                        high_low[0] = 0x00000000
                        high_low[1] = 0xFFFFFFFF
        
        def reader():
            for _ in range(10000):
                high = high_low[0]
                low = high_low[1]
                combined = (high << 32) | low
                
                if combined not in [0xFFFFFFFF00000000, 0x00000000FFFFFFFF]:
                    tears_observed.append(combined)
        
        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        print(f"Tears observed: {len(tears_observed)}")

    def test_cache_line_false_sharing(self):
        """
        Threads modify adjacent memory that shares cache line.
        """
        configure(mode="raise")
        
        cache_line = protect([0] * 16)
        contention_detected = [0]
        
        def worker(slot):
            try:
                for _ in range(100000):
                    cache_line[slot] += 1
            except RaceConditionError:
                contention_detected[0] += 1
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"False sharing contention detected: {contention_detected[0]}")

# ============================================
# GIL EXPLOITATION RACES
# ============================================

class TestGILExploitation:
    """
    Races that specifically exploit Python's GIL behavior.
    """
    
    def test_eval_breaker_race(self):
        """
        Exploit eval breaker (periodic GIL release) for races.
        """
        configure(mode="raise")
        
        counter = protect([0])
        races = []
        
        def tight_loop_worker():
            try:
                for _ in range(1000000):
                    counter[0] += 1
            except RaceConditionError as e:
                races.append(e)
        
        threads = [threading.Thread(target=tight_loop_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Races in tight loop: {len(races)}")
    
    def test_c_extension_boundary_race(self):
        """
        Race across Python/C boundary where GIL is released.
        """
        configure(mode="raise")
        
        data = protect(bytearray(1024))
        errors = []
        
        def modify_bytes():
            try:
                for _ in range(1000):
                    data.extend(b'x')
                    len(data)
                    data[0] = random.randint(0, 255)
            except RaceConditionError as e:
                errors.append(e)
        
        threads = [threading.Thread(target=modify_bytes) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"C-boundary races: {len(errors)}")
    
    def test_generator_yield_race(self):
        """
        Race between generator suspension and other threads.
        """
        configure(mode="raise")
        
        shared = protect(list(range(100)))
        inconsistencies = []
        
        def generator_consumer():
            gen = (x for x in shared)
            results = []
            for item in gen:
                expected = item
                actual = shared[item] if item < len(shared) else None
                if expected != actual:
                    inconsistencies.append((expected, actual))
                results.append(item)
            return results
        
        def modifier():
            for _ in range(100):
                try:
                    with locked(shared):
                        if shared:
                            shared.pop(0)
                except RaceConditionError:
                    pass
                time.sleep(0.0001)
        
        gen_thread = threading.Thread(target=lambda: generator_consumer())
        mod_thread = threading.Thread(target=modifier)
        
        gen_thread.start()
        mod_thread.start()
        gen_thread.join()
        mod_thread.join()
        
        print(f"Generator inconsistencies: {len(inconsistencies)}")

    def test_mmap_shared_memory_race(self):
        """
        Race through memory-mapped file (bypasses Python object model).
        """
        configure(mode="raise")
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'\x00' * 1024)
            mmap_path = f.name
        
        try:
            with open(mmap_path, 'r+b') as f:
                mm = mmap.mmap(f.fileno(), 1024)
                
                counter = protect([0])
                mmap_races = []
                
                def mmap_writer():
                    try:
                        for i in range(1000):
                            mm[0:8] = struct.pack('Q', i)
                            counter[0] = i
                    except RaceConditionError as e:
                        mmap_races.append(e)
                
                def mmap_reader():
                    try:
                        for _ in range(1000):
                            val = struct.unpack('Q', mm[0:8])[0]
                            counter_val = counter[0]
                            
                            if abs(val - counter_val) > 10:
                                mmap_races.append(("INCONSISTENT", val, counter_val))
                    except RaceConditionError as e:
                        mmap_races.append(e)
                
                threads = ([threading.Thread(target=mmap_writer) for _ in range(2)] +
                          [threading.Thread(target=mmap_reader) for _ in range(2)])
                
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                
                mm.close()
                print(f"MMAP races/inconsistencies: {len(mmap_races)}")
                
        finally:
            os.unlink(mmap_path)

# ============================================
# TIMING ATTACK CHANNELS
# ============================================

class TestTimingChannels:
    """
    Races that manifest as timing side channels.
    """
    
    def test_cache_timing_covert_channel(self):
        """
        Use cache timing to detect race winner (covert channel).
        """
        configure(mode="raise")
        
        flag = protect([0])
        timings = [[], []]
        
        def timed_access(thread_id):
            for _ in range(1000):
                start = time.perf_counter_ns()
                
                try:
                    if flag[0] == 0:
                        flag[0] = thread_id + 1
                except RaceConditionError:
                    pass
                
                end = time.perf_counter_ns()
                timings[thread_id].append(end - start)
                
                try:
                    flag[0] = 0
                except RaceConditionError:
                    pass
                time.sleep(0.00001)
        
        t1 = threading.Thread(target=timed_access, args=(0,))
        t2 = threading.Thread(target=timed_access, args=(1,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        avg_0 = sum(timings[0]) / len(timings[0])
        avg_1 = sum(timings[1]) / len(timings[1])
        
        print(f"Thread 0 avg time: {avg_0}ns, Thread 1 avg time: {avg_1}ns")
    
    def test_branch_prediction_race(self):
        """
        Race that exploits branch predictor state.
        """
        configure(mode="raise")
        
        data = protect([0])
        mispredictions = [0, 0]
        
        def branch_worker(thread_id, pattern):
            try:
                for i in range(10000):
                    if i % 100 != 99:
                        pass
                    
                    if data[0] == thread_id:
                        mispredictions[thread_id] += 1
                    
                    if i % 50 == 0:
                        data[0] = 1 - thread_id
                        
            except RaceConditionError:
                pass
        
        t1 = threading.Thread(target=branch_worker, args=(0, "AAAA"))
        t2 = threading.Thread(target=branch_worker, args=(1, "BBBB"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        print(f"Mispredictions: {mispredictions}")

    def test_instruction_reorder_speculation(self):
        """
        Test if instructions can be speculatively reordered.
        """
        configure(mode="raise")
        
        x = protect([0])
        y = protect([0])
        r1 = [0]
        r2 = [0]
        
        def thread1():
            try:
                for _ in range(10000):
                    x[0] = 1
                    r1[0] = y[0]
            except RaceConditionError:
                pass
        
        def thread2():
            try:
                for _ in range(10000):
                    y[0] = 1
                    r2[0] = x[0]
            except RaceConditionError:
                pass
        
        t1 = threading.Thread(target=thread1)
        t2 = threading.Thread(target=thread2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        if r1[0] == 0 and r2[0] == 0:
            print("REORDERING DETECTED: Both threads saw 0!")

# ============================================
# COMPOUND NIGHTMARE SCENARIOS
# ============================================

class TestNightmareScenarios:
    """
    The worst possible combinations of everything above.
    """
    
    def test_recursive_deadlock_with_timeout_race(self):
        """
        Recursion + timeout + multiple locks = nightmare.
        """
        configure(mode="raise")
        
        resources = [protect({"id": i, "data": []}) for i in range(5)]
        deadlocks = []
        timeouts = []
        
        def recursive_lock_acquirer(depth, resource_ids):
            if depth <= 0:
                return
            
            try:
                acquired = []
                for rid in resource_ids:
                    start = time.time()
                    while time.time() - start < 0.001:
                        try:
                            with locked(resources[rid]):
                                acquired.append(rid)
                                resources[rid]["data"].append(threading.current_thread().name)
                                break
                        except:
                            pass
                    else:
                        timeouts.append((depth, rid))
                        acquired.clear()
                        break
                
                if acquired:
                    next_order = list(reversed(resource_ids))
                    recursive_lock_acquirer(depth - 1, next_order)
                    
            except Exception as e:
                deadlocks.append(e)
        
        threads = []
        for i in range(10):
            order = list(range(5))
            random.shuffle(order)
            t = threading.Thread(target=recursive_lock_acquirer, 
                               args=(3, order))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        print(f"Deadlocks: {len(deadlocks)}, Timeouts: {len(timeouts)}")
    
    def test_reference_cycle_gc_race(self):
        """
        Reference cycles causing GC during critical section.
        """
        configure(mode="raise")
        
        class Node:
            def __init__(self, value):
                self.value = value
                self.next = None
                self.prev = None
                self.data = protect([0])
        
        head = protect(Node(0))
        gc_races = []
        
        def list_mutator():
            try:
                current = head
                for _ in range(100):
                    new_node = protect(Node(random.randint(0, 1000)))
                    with locked(current):
                        new_node.next = current
                        current.prev = new_node
                        current = new_node
                    
                    if random.random() < 0.1:
                        gc.collect()
                        
            except RaceConditionError as e:
                gc_races.append(e)
        
        def cycle_breaker():
            try:
                for _ in range(50):
                    time.sleep(0.001)
                    with locked(head):
                        if head.prev:
                            head.prev.next = None
                            head.prev = None
                            gc.collect()
            except RaceConditionError as e:
                gc_races.append(e)
        
        threads = ([threading.Thread(target=list_mutator) for _ in range(3)] +
                  [threading.Thread(target=cycle_breaker) for _ in range(2)])
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"GC races detected: {len(gc_races)}")
    
    def test_metaclass_registry_race(self):
        """
        Race in metaclass __new__ during class creation.
        """
        configure(mode="raise")
        
        registry = protect({})
        race_count = [0]
        
        def create_classes(thread_id):
            for i in range(50):
                try:
                    new_class = type(f"Class_{thread_id}_{i}", (), {
                        "thread": thread_id,
                        "index": i
                    })
                    registry[f"Class_{thread_id}_{i}"] = new_class
                except RaceConditionError:
                    race_count[0] += 1
        
        threads = [threading.Thread(target=create_classes, args=(i,)) 
                   for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Metaclass races: {race_count[0]}")

    # NOTE: test_signal_handler_interrupt_race skipped - uses SIGALRM (Unix only)

# ============================================
# RUNNER
# ============================================

if __name__ == "__main__":
    import pytest
    
    print("=" * 60)
    print("RACEGUARD EXTREME TORTURE TEST")
    print("Testing for races that are nearly impossible to detect")
    print("=" * 60)
    
    sys.exit(pytest.main([
        "-v",
        "--tb=short",
        "-s",  # Show print statements
        __file__
    ]))
