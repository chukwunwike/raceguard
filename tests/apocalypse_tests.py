#!/usr/bin/env python3
"""
RACEGUARD APOCALYPSE TEST
The final boss of race condition detection.

Adapted for Windows (removed Unix-only APIs: fcntl, SIGALRM, fork, SIGIO).
"""

import threading
import asyncio
import time
import random
import sys
import gc
import weakref
import struct
import mmap
import os
import tempfile
import pickle
import hashlib
import collections
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from collections import deque, defaultdict
from typing import Any, Optional, Dict, List, Tuple
import queue
import traceback
import multiprocessing as mp

sys.path.insert(0, "src")

from raceguard import protect, locked, with_lock, configure, RaceConditionError, unbind

# Global chaos coordinator
CHAOS_LEVEL = 100
APOCALYPSE_MODE = True

# ============================================
# UTILITIES FOR MAXIMUM DESTRUCTION
# ============================================

class QuantumBit:
    """Simulates quantum superposition."""
    def __init__(self):
        self._states = []
        self._collapsed = None

    def superpose(self, state):
        self._states.append(state)

    def observe(self):
        if self._collapsed is None and self._states:
            self._collapsed = random.choice(self._states)
        return self._collapsed


class ByzantineFaultInjector:
    """Randomly injects faulty behavior."""
    @staticmethod
    def should_lie():
        return random.random() < (CHAOS_LEVEL / 200)

    @staticmethod
    def corrupt_message(msg):
        if not ByzantineFaultInjector.should_lie():
            return msg
        try:
            msg_bytes = pickle.dumps(msg)
            corrupted = bytearray(msg_bytes)
            for _ in range(random.randint(1, 5)):
                idx = random.randint(0, len(corrupted) - 1)
                corrupted[idx] ^= (1 << random.randint(0, 7))
            return pickle.loads(bytes(corrupted))
        except Exception:
            return msg  # If corruption fails, return original


# ============================================
# THE APOCALYPSE - DISTRIBUTED CONSENSUS HELL
# ============================================

class TestDistributedConsensusHell:
    
    def test_raft_consensus_with_speculative_log_entries(self):
        """
        Raft consensus where followers speculatively apply log entries
        before commit, creating rollback races.
        """
        configure(mode="raise")
        
        nodes = [{
            'id': i,
            'term': protect([0]),
            'voted_for': protect([None]),
            'log': protect([]),
            'commit_index': protect([0]),
            'last_applied': protect([0]),
            'state': protect(['follower']),
            'next_index': protect({}),
            'match_index': protect({}),
            'speculative_applied': protect([]),
            'speculative_index': protect([0]),
        } for i in range(5)]
        
        network = protect({
            'messages': deque(maxlen=10000),
            'partitioned': set(),
        })
        
        races_detected = [0]
        committed_entries = [0]
        speculative_violations = []
        
        def send_message(to_node, msg):
            if ByzantineFaultInjector.should_lie():
                msg = ByzantineFaultInjector.corrupt_message(msg)
            with locked(network):
                if to_node not in network['partitioned']:
                    network['messages'].append((to_node, msg, time.time()))
        
        def raft_node(node_id):
            me = nodes[node_id]
            
            try:
                while committed_entries[0] < 100 and races_detected[0] < 10:
                    state = me['state'][0]
                    
                    if state == 'follower':
                        time.sleep(0.01 * random.random())
                        
                        with locked(network):
                            pending = [m for m in network['messages'] if m[0] == node_id]
                            network['messages'] = deque(
                                m for m in network['messages'] if m[0] != node_id
                            )
                        
                        for _, msg, _ in pending:
                            if isinstance(msg, dict) and msg.get('type') == 'append_entries':
                                entries = msg.get('entries', [])
                                leader_commit = msg.get('leader_commit', 0)
                                
                                with locked(me['log']):
                                    for entry in entries:
                                        me['log'].append(entry)
                                
                                for entry in entries:
                                    with locked(me['speculative_applied']):
                                        me['speculative_applied'].append(entry)
                                        me['speculative_index'][0] += 1
                                
                                if leader_commit > me['commit_index'][0]:
                                    new_commit = min(leader_commit, len(me['log']))
                                    me['commit_index'][0] = new_commit
                                    
                                    if me['speculative_index'][0] > new_commit:
                                        speculative_violations.append({
                                            'node': node_id,
                                            'speculative': me['speculative_index'][0],
                                            'committed': new_commit,
                                        })
                                        
                                        with locked(me['speculative_applied']):
                                            me['speculative_applied'][:] = me['speculative_applied'][:new_commit]
                                            me['speculative_index'][0] = new_commit
                                
                                committed_entries[0] = max(committed_entries[0], new_commit)
                                
                    elif state == 'leader':
                        for peer in range(5):
                            if peer != node_id:
                                with locked(me['log']):
                                    entries = list(me['log'])
                                
                                send_message(peer, {
                                    'type': 'append_entries',
                                    'term': me['term'][0],
                                    'entries': entries,
                                    'leader_commit': me['commit_index'][0]
                                })
                        
                        time.sleep(0.005)
                        
            except RaceConditionError:
                races_detected[0] += 1
                try:
                    with locked(me['state']):
                        me['state'][0] = 'follower'
                except RaceConditionError:
                    pass
        
        threads = [threading.Thread(target=raft_node, args=(i,)) for i in range(5)]
        
        def chaos_partition():
            while committed_entries[0] < 50 and races_detected[0] < 10:
                time.sleep(0.05)
                with locked(network):
                    if random.random() < 0.3:
                        network['partitioned'] = set(random.sample(range(5), 2))
                    else:
                        network['partitioned'] = set()
        
        threads.append(threading.Thread(target=chaos_partition))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        
        print(f"Raft: {committed_entries[0]} committed, {races_detected[0]} races, "
              f"{len(speculative_violations)} speculative violations")
    
    def test_paxos_acceptor_preempt_race(self):
        """Paxos acceptor with concurrent prepare/accept creating dangling promises."""
        configure(mode="raise")
        
        acceptor_state = protect({
            'promised_ballot': (-1, -1),
            'accepted_ballot': (-1, -1),
            'accepted_value': None,
            'promises': {},
        })
        
        chosen_values = []
        races = []
        
        def proposer(proposer_id):
            for round_num in range(20):
                ballot = (round_num, proposer_id)
                
                try:
                    with locked(acceptor_state):
                        if ballot > acceptor_state['promised_ballot']:
                            acceptor_state['promised_ballot'] = ballot
                            time.sleep(0.0001)
                            if ballot not in acceptor_state['promises']:
                                acceptor_state['promises'][ballot] = set()
                    
                    with locked(acceptor_state):
                        if acceptor_state['promised_ballot'] == ballot:
                            value = f"value_{proposer_id}_{round_num}"
                            if acceptor_state['accepted_ballot'] < ballot:
                                acceptor_state['accepted_ballot'] = ballot
                                acceptor_state['accepted_value'] = value
                                chosen_values.append((ballot, value))
                            
                except RaceConditionError as e:
                    races.append((proposer_id, ballot, e))
        
        threads = [threading.Thread(target=proposer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Paxos: {len(chosen_values)} values chosen, {len(races)} races")

    def test_viewstamped_replication_primary_view_change_race(self):
        """VR protocol where primary fails during view change."""
        configure(mode="raise")
        
        replicas = [{
            'id': i,
            'view': protect([0]),
            'status': protect(['normal']),
            'op_log': protect([]),
            'commit_num': protect([0]),
            'prepare_oks': protect({}),
        } for i in range(5)]
        
        primary = [0]
        view_changes = [0]
        split_brain_detected = [False]
        
        def replica_main(replica_id):
            me = replicas[replica_id]
            
            try:
                while view_changes[0] < 5:
                    current_primary = primary[0]
                    
                    if replica_id == current_primary and me['status'][0] == 'normal':
                        for op_num in range(me['commit_num'][0] + 1,
                                            me['commit_num'][0] + 10):
                            time.sleep(0.001)
                            with locked(me['prepare_oks']):
                                oks = me['prepare_oks'].get(op_num, set())
                                if len(oks) >= 2:
                                    with locked(me['commit_num']):
                                        me['commit_num'][0] = op_num
                    else:
                        time.sleep(0.005)
                        
                        if random.random() < 0.1:
                            with locked(me['status']):
                                if me['status'][0] == 'normal':
                                    me['status'][0] = 'view_change'
                                    view_changes[0] += 1
                                    
                                    new_view = me['view'][0] + 1
                                    me['view'][0] = new_view
                                    
                                    if replica_id != current_primary:
                                        old_primary_log_len = len(replicas[current_primary]['op_log'])
                                        my_log_len = len(me['op_log'])
                                        
                                        if old_primary_log_len > my_log_len:
                                            split_brain_detected[0] = True
                                    
                                    primary[0] = replica_id
                                    me['status'][0] = 'normal'
                                    
            except RaceConditionError:
                pass
        
        threads = [threading.Thread(target=replica_main, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        
        print(f"VR: {view_changes[0]} view changes, split brain: {split_brain_detected[0]}")


# ============================================
# HARDWARE-LEVEL MEMORY MODEL TORTURE
# ============================================

class TestHardwareMemoryModel:
    
    def test_store_buffer_forwarding_race(self):
        """CPU store buffer forwarding simulation."""
        configure(mode="raise")
        
        store_buffers = [protect({}) for _ in range(4)]
        global_memory = protect({'x': 0, 'y': 0})
        observations = []
        
        def cpu_thread(cpu_id):
            my_buffer = store_buffers[cpu_id]
            
            try:
                for _ in range(1000):
                    with locked(my_buffer):
                        my_buffer['x'] = 1
                    
                    local_x = None
                    with locked(my_buffer):
                        if 'x' in my_buffer:
                            local_x = my_buffer['x']
                    
                    with locked(global_memory):
                        global_y = global_memory['y']
                    
                    with locked(my_buffer):
                        with locked(global_memory):
                            for k, v in list(my_buffer.items()):
                                global_memory[k] = v
                            my_buffer.clear()
                    
                    observations.append((cpu_id, local_x, global_y))
                    
            except RaceConditionError:
                pass
        
        barrier = threading.Barrier(4)
        
        def coordinated_cpu(cpu_id):
            barrier.wait()
            cpu_thread(cpu_id)
        
        threads = [threading.Thread(target=coordinated_cpu, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        anomalies = [o for o in observations if o[1] == 1 and o[2] == 0]
        print(f"Store buffer anomalies: {len(anomalies)}")
    
    def test_invalidation_queue_delay_race(self):
        """CPU cache invalidation queue delays causing stale reads."""
        configure(mode="raise")
        
        cache_lines = [{
            'valid': protect([True]),
            'data': protect([0]),
            'version': protect([0]),
        } for _ in range(4)]
        
        memory = protect({'data': 0, 'version': 0})
        stale_reads = []
        
        def writer():
            for i in range(1000):
                with locked(memory):
                    memory['data'] = i
                    memory['version'] += 1
                
                for cache in cache_lines:
                    with locked(cache['valid']):
                        cache['valid'][0] = False
        
        def reader(cpu_id):
            my_cache = cache_lines[cpu_id % 4]
            
            for _ in range(1000):
                cached_valid = False
                cached_data = None
                
                with locked(my_cache['valid']):
                    cached_valid = my_cache['valid'][0]
                    if cached_valid:
                        with locked(my_cache['data']):
                            cached_data = my_cache['data'][0]
                
                if not cached_valid:
                    with locked(memory):
                        fresh_data = memory['data']
                    
                    with locked(my_cache['data']):
                        my_cache['data'][0] = fresh_data
                    with locked(my_cache['valid']):
                        my_cache['valid'][0] = True
                    
                    cached_data = fresh_data
                
                with locked(memory):
                    actual = memory['data']
                
                if cached_data is not None and cached_data != actual:
                    stale_reads.append((cpu_id, cached_data, actual))
        
        threads = [threading.Thread(target=writer)] + \
                  [threading.Thread(target=reader, args=(i,)) for i in range(4)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Stale cache reads: {len(stale_reads)}")

    def test_load_speculation_misprediction_race(self):
        """CPU speculative load simulation (Spectre-style)."""
        configure(mode="raise")
        
        secret_data = protect(list(range(1000)))
        public_buffer = protect([0] * 256)
        
        def victim():
            for _ in range(10000):
                idx = random.randint(0, 999)
                if idx < len(secret_data):
                    secret_val = secret_data[idx]
                    public_buffer[secret_val % 256] = 1
        
        def attacker():
            for i in range(256):
                start = time.perf_counter_ns()
                _ = public_buffer[i]
                end = time.perf_counter_ns()
        
        t1 = threading.Thread(target=victim)
        t2 = threading.Thread(target=attacker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        print("Load speculation test: Conceptual (requires CPU-level control)")


# ============================================
# GIL EXPLOITATION AT BYTECODE LEVEL
# ============================================

class TestGILBytecodeExploitation:
    
    def test_dict_resize_race(self):
        """Dictionary resize during insertion with GIL release."""
        configure(mode="raise")
        
        d = protect({i: i for i in range(1000)})
        races = []
        lost_keys = []
        
        def inserter(thread_id):
            try:
                for i in range(1000):
                    key = f"thread_{thread_id}_key_{i}"
                    d[key] = i
                    if d.get(key) != i:
                        lost_keys.append((thread_id, key, i))
            except (RaceConditionError, RuntimeError) as e:
                races.append(e)
        
        def resizer():
            try:
                for _ in range(100):
                    temp = {f"bulk_{i}": i for i in range(100)}
                    d.update(temp)
                    for k in list(d.keys())[:50]:
                        if k in d:
                            del d[k]
            except RaceConditionError as e:
                races.append(e)
        
        threads = ([threading.Thread(target=inserter, args=(i,)) for i in range(4)] +
                   [threading.Thread(target=resizer)])
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Dict resize races: {len(races)}, Lost keys: {len(lost_keys)}")
    
    def test_list_sort_race(self):
        """List sort releases GIL during comparisons."""
        configure(mode="raise")
        
        lst = protect([random.randint(0, 1000) for _ in range(10000)])
        races = []
        
        def sorter():
            try:
                with locked(lst):
                    lst.sort()
            except (RaceConditionError, ValueError) as e:
                races.append(e)
        
        def modifier():
            try:
                for _ in range(100):
                    if lst:
                        idx = random.randint(0, min(100, len(lst) - 1))
                        lst[idx] = random.randint(0, 1000)
                    time.sleep(0.00001)
            except RaceConditionError:
                pass
        
        threads = ([threading.Thread(target=sorter) for _ in range(2)] +
                   [threading.Thread(target=modifier) for _ in range(2)])
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"List sort races: {len(races)}")
    
    def test_import_race(self):
        """Concurrent imports of same module."""
        configure(mode="raise")
        
        module_code = """
import time
import random
shared_state = None

def init():
    global shared_state
    if shared_state is None:
        temp = {}
        time.sleep(0.001)
        shared_state = temp
    return shared_state
"""
        
        import_count = [0]
        race_count = [0]
        
        def importer():
            try:
                import importlib.util
                
                spec = importlib.util.spec_from_loader("racey_module", loader=None)
                module = importlib.util.module_from_spec(spec)
                exec(module_code, module.__dict__)
                sys.modules["racey_module"] = module
                
                result = module.init()
                import_count[0] += 1
            except RaceConditionError:
                race_count[0] += 1
        
        threads = [threading.Thread(target=importer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Import races: {race_count[0]}")

    def test_frame_evaluation_race(self):
        """Race between frame evaluation and introspection."""
        configure(mode="raise")
        
        frames = protect([])
        race_count = [0]
        
        def recursive_function(n):
            try:
                frame = sys._getframe()
                
                frames.append({
                    'function': frame.f_code.co_name,
                    'lineno': frame.f_lineno,
                    'locals': dict(frame.f_locals),
                })
                
                if n > 0:
                    return recursive_function(n - 1) + n
                return 0
            except RaceConditionError:
                race_count[0] += 1
                return 0
        
        def frame_inspector():
            try:
                for _ in range(100):
                    for frame_info in list(frames):
                        _ = frame_info.get('locals', {})
                    time.sleep(0.0001)
            except (RaceConditionError, RuntimeError):
                race_count[0] += 1
        
        threads = ([threading.Thread(target=lambda: recursive_function(50))
                    for _ in range(3)] +
                   [threading.Thread(target=frame_inspector) for _ in range(2)])
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Frame evaluation races: {race_count[0]}")


# ============================================
# CROSS-PROCESS SHARED MEMORY CHAOS
# ============================================

class TestCrossProcessChaos:
    
    def test_shared_memory_race(self):
        """multiprocessing.shared_memory with concurrent access."""
        configure(mode="raise")
        
        try:
            from multiprocessing import shared_memory
        except ImportError:
            print("shared_memory not available, skipping")
            return
        
        shm = shared_memory.SharedMemory(create=True, size=1024)
        
        try:
            # Zero init
            shm.buf[0:4] = struct.pack('I', 0)
            
            races = []
            
            def worker(shm_name, worker_id):
                existing_shm = shared_memory.SharedMemory(name=shm_name)
                try:
                    buf = existing_shm.buf
                    for _ in range(1000):
                        counter_bytes = bytes(buf[0:4])
                        counter = struct.unpack('I', counter_bytes)[0]
                        counter += 1
                        buf[0:4] = struct.pack('I', counter)
                except Exception as e:
                    races.append(str(e))
                finally:
                    existing_shm.close()
            
            threads = [threading.Thread(target=worker, args=(shm.name, i))
                       for i in range(4)]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            final = struct.unpack('I', bytes(shm.buf[0:4]))[0]
            expected = 4000
            print(f"Shared memory: final={final} (expected {expected}), "
                  f"lost increments={expected - final}")
            
        finally:
            shm.close()
            shm.unlink()
    
    def test_mmap_file_race(self):
        """Memory-mapped file with page-level races."""
        configure(mode="raise")
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'\x00' * 4096 * 10)
            path = f.name
        
        try:
            with open(path, 'r+b') as f:
                mm = mmap.mmap(f.fileno(), 4096 * 10)
                
                races = []
                
                def page_writer(page_num):
                    try:
                        offset = page_num * 4096
                        for i in range(100):
                            lock = struct.unpack('I', mm[offset:offset + 4])[0]
                            
                            if lock == 0:
                                mm[offset:offset + 4] = struct.pack('I', 1)
                                data = f"page_{page_num}_seq_{i}".encode()
                                mm[offset + 4:offset + 4 + len(data)] = data
                                mm[offset:offset + 4] = struct.pack('I', 0)
                            
                    except Exception as e:
                        races.append(e)
                
                threads = [threading.Thread(target=page_writer, args=(i % 3,))
                           for i in range(12)]
                
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                
                mm.close()
                print(f"MMAP page races: {len(races)}")
                
        finally:
            os.unlink(path)

    def test_socket_sendmsg_race(self):
        """Scatter/gather I/O with concurrent buffer modification."""
        configure(mode="raise")
        
        import socket
        s1, s2 = socket.socketpair()
        
        send_buffer = protect(bytearray(b"initial data"))
        races = []
        
        def sender():
            try:
                for _ in range(100):
                    with locked(send_buffer):
                        data = bytes(send_buffer)
                    s1.send(data)
                    time.sleep(0.0001)
            except RaceConditionError as e:
                races.append(e)
            except OSError:
                pass
        
        def modifier():
            try:
                for i in range(100):
                    with locked(send_buffer):
                        send_buffer.extend(b"extra")
                        if len(send_buffer) > 1000:
                            send_buffer[:] = b"reset"
                    time.sleep(0.00005)
            except RaceConditionError as e:
                races.append(e)
        
        threads = [threading.Thread(target=sender),
                   threading.Thread(target=modifier)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        s1.close()
        s2.close()
        print(f"Socket sendmsg races: {len(races)}")


# ============================================
# GC FINALIZER RESURRECTION CYCLES
# ============================================

class TestGCFinalizerResurrection:
    
    def test_phantom_reference_race(self):
        """Phantom references allowing access to being-collected objects."""
        configure(mode="raise")
        
        phantom_queue = queue.Queue()
        resurrection_count = [0]
        races = []
        
        class PhantomObject:
            def __init__(self, value):
                self.value = value
                self._ref = weakref.ref(self, lambda ref: phantom_queue.put(value))
        
        def creator():
            for i in range(1000):
                obj = PhantomObject(i)
                del obj
                if i % 100 == 0:
                    gc.collect()
        
        def consumer():
            for _ in range(1000):
                try:
                    value = phantom_queue.get(timeout=0.01)
                    resurrection_count[0] += 1
                    _ = value * 2
                except queue.Empty:
                    pass
        
        threads = [threading.Thread(target=creator),
                   threading.Thread(target=consumer)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Phantom resurrections: {resurrection_count[0]}, races: {len(races)}")
    
    def test_finalizer_reentrancy_death(self):
        """Finalizer that resurrects object, which gets finalized again."""
        configure(mode="raise")
        
        class ImmortalObject:
            _instances = protect([])
            _finalizing = set()
            
            def __init__(self, id_val):
                self.id = id_val
                self.resurrected = False
            
            def __del__(self):
                if id(self) in ImmortalObject._finalizing:
                    return
                
                try:
                    ImmortalObject._finalizing.add(id(self))
                    with locked(ImmortalObject._instances):
                        ImmortalObject._instances.append(self)
                    self.resurrected = True
                    ImmortalObject._finalizing.discard(id(self))
                except (RaceConditionError, Exception):
                    ImmortalObject._finalizing.discard(id(self))
        
        def stress_test():
            for i in range(100):
                obj = ImmortalObject(i)
                del obj
                
                if i % 10 == 0:
                    gc.collect()
                    try:
                        with locked(ImmortalObject._instances):
                            if ImmortalObject._instances:
                                ImmortalObject._instances.pop(0)
                    except RaceConditionError:
                        pass
        
        threads = [threading.Thread(target=stress_test) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        try:
            with locked(ImmortalObject._instances):
                remaining = len(ImmortalObject._instances)
        except RaceConditionError:
            remaining = -1
        print(f"Immortal objects remaining: {remaining}")


# ============================================
# THE FINAL APOCALYPSE - EVERYTHING AT ONCE
# ============================================

class TestFinalApocalypse:
    
    def test_everything_everywhere_all_at_once(self):
        """
        Raft consensus + hardware memory model + GIL exploitation +
        cross-process shared memory + GC chaos.
        All at the same time.
        """
        configure(mode="raise")
        
        apocalypse_state = protect({
            'consensus_log': [],
            'hardware_registers': {},
            'gil_releases': 0,
            'gc_collections': 0,
        })
        
        quantum_state = QuantumBit()
        quantum_state.superpose("alive")
        quantum_state.superpose("dead")
        
        races = [0]
        violations = []
        
        def chaos_orchestrator():
            while races[0] < 100:
                event = random.choice(['gc', 'resize', 'partition'])
                
                if event == 'gc':
                    gc.collect()
                    try:
                        with locked(apocalypse_state):
                            apocalypse_state['gc_collections'] += 1
                    except RaceConditionError:
                        races[0] += 1
                
                time.sleep(0.001)
        
        def distributed_consensus_node(node_id):
            try:
                for _ in range(50):
                    with locked(apocalypse_state):
                        log_len = len(apocalypse_state['consensus_log'])
                    
                    entry = {
                        'term': random.randint(1, 10),
                        'node': node_id,
                        'quantum': quantum_state.observe(),
                    }
                    
                    with locked(apocalypse_state):
                        apocalypse_state['consensus_log'].append(entry)
                    
                    time.sleep(0.0001)
                    
            except RaceConditionError:
                races[0] += 1
        
        def hardware_memory_thread():
            try:
                for _ in range(100):
                    temp = {'key': random.randint(0, 1000)}
                    time.sleep(0.0001)
                    
                    with locked(apocalypse_state):
                        apocalypse_state['hardware_registers'].update(temp)
                        
            except RaceConditionError:
                races[0] += 1
        
        def gil_exploiter():
            try:
                d = {}
                for i in range(1000):
                    d[f"key_{i}"] = i
                    lst = list(d.values())
                    lst.sort()
                    
                    if len(lst) != len(d):
                        violations.append("GIL consistency violation")
                        
            except (RaceConditionError, ValueError):
                races[0] += 1
        
        threads = (
            [threading.Thread(target=chaos_orchestrator)] +
            [threading.Thread(target=distributed_consensus_node, args=(i,))
             for i in range(3)] +
            [threading.Thread(target=hardware_memory_thread) for _ in range(2)] +
            [threading.Thread(target=gil_exploiter) for _ in range(2)]
        )
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        
        try:
            gc_count = apocalypse_state['gc_collections']
        except RaceConditionError:
            gc_count = "N/A"
        
        print(f"APOCALYPSE COMPLETE: {races[0]} races, {len(violations)} violations")
        print(f"GC collections: {gc_count}")


# ============================================
# RUNNER
# ============================================

if __name__ == "__main__":
    import pytest
    
    print("=" * 80)
    print("RACEGUARD APOCALYPSE TEST")
    print("Maximum Entropy Mode Activated")
    print("=" * 80)
    print(f"Chaos Level: {CHAOS_LEVEL}%")
    print(f"Apocalypse Mode: {APOCALYPSE_MODE}")
    print("=" * 80)
    
    sys.exit(pytest.main([
        "-v",
        "-s",
        "--tb=short",
        __file__
    ]))
