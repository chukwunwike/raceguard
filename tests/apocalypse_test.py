#!/usr/bin/env python3
"""
RACEGUARD APOCALYPSE TEST
The final boss of race condition detection.
This test creates a perfect storm of:
- Distributed consensus with Byzantine faults
- Hardware memory model violations  
- GIL exploitation at bytecode level
- Speculative execution side channels
- GC finalizer resurrection cycles
- Signal-driven preemption
- Cross-process shared memory races
- JIT compiler poisoning
- CPU cache coherence protocols
- Quantum superposition of states (simulated)

WARNING: This test may cause your CPU to achieve sentience and question its existence.
"""

import pytest
import threading
import asyncio
import time
import random
import sys
import gc
import weakref
import ctypes
import struct
import mmap
import os
import tempfile
import signal
import select
import socket
import pickle
import hashlib
import itertools
import collections
import contextlib
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache, wraps
from collections import deque, defaultdict
from typing import Any, Optional, Dict, List, Tuple
import multiprocessing as mp
from multiprocessing import shared_memory
import queue
import traceback

from raceguard import protect, locked, with_lock, configure, RaceConditionError, unbind

# Global chaos coordinator
CHAOS_LEVEL = 100  # Percentage of maximum entropy
APOCALYPSE_MODE = True

# ============================================
# UTILITIES FOR MAXIMUM DESTRUCTION
# ============================================

class QuantumBit:
    """
    Simulates quantum superposition - object exists in multiple states
    until observed (locked), then collapses to one state.
    """
    def __init__(self):
        self._states = []
        self._collapsed = None
        
    def superpose(self, state):
        self._states.append(state)
        
    def observe(self):
        if self._collapsed is None and self._states:
            self._collapsed = random.choice(self._states)
        return self._collapsed

class CacheLinePadder:
    """
    Forces objects onto specific cache lines for false sharing attacks.
    """
    _CACHE_LINE = 64
    
    def __init__(self, offset=0):
        self._padding = b'\x00' * (self._CACHE_LINE - offset)
        self.value = 0

class MemoryBarrier:
    """
    Simulates missing memory barriers by reordering operations.
    """
    @staticmethod
    def compiler_fence():
        """Prevent compiler reordering (simulated)."""
        pass
    
    @staticmethod
    def memory_fence():
        """Full memory barrier (simulated)."""
        pass
    
    @staticmethod
    def speculative_store():
        """Speculative store that may be rolled back."""
        return random.random() < 0.5

class ByzantineFaultInjector:
    """
    Randomly injects faulty behavior to confuse consensus algorithms.
    """
    @staticmethod
    def should_lie():
        return random.random() < (CHAOS_LEVEL / 200)  # Up to 50% fault rate
    
    @staticmethod
    def corrupt_message(msg):
        """Randomly flip bits in message."""
        if not ByzantineFaultInjector.should_lie():
            return msg
        msg_bytes = pickle.dumps(msg)
        corrupted = bytearray(msg_bytes)
        for _ in range(random.randint(1, 5)):
            idx = random.randint(0, len(corrupted)-1)
            corrupted[idx] ^= (1 << random.randint(0, 7))
        return pickle.loads(bytes(corrupted))

# ============================================
# THE APOCALYPSE - DISTRIBUTED CONSENSUS HELL
# ============================================

class TestDistributedConsensusHell:
    """
    Multi-layer Byzantine consensus with nested state machines,
    speculative execution, and hardware-level races.
    """
    
    def test_raft_consensus_with_speculative_log_entries(self):
        """
        Raft consensus where followers speculatively apply log entries
        before commit, creating rollback races.
        """
        configure(mode="raise")
        
        # Cluster of 5 nodes
        nodes = [{
            'id': i,
            'term': protect([0]),
            'voted_for': protect([None]),
            'log': protect([]),  # [(term, index, command)]
            'commit_index': protect([0]),
            'last_applied': protect([0]),
            'state': protect(['follower']),  # follower, candidate, leader
            'next_index': protect({}),  # leader only
            'match_index': protect({}),  # leader only
            # Speculative state - applied but not committed!
            'speculative_applied': protect([]),
            'speculative_index': protect([0]),
        } for i in range(5)]
        
        # Shared network (the actual race arena)
        network = protect({
            'messages': deque(maxlen=10000),
            'partitioned': set(),  # Simulated network partition
        })
        
        races_detected = [0]
        committed_entries = [0]
        speculative_violations = []
        
        def send_message(to_node, msg):
            """Send with potential Byzantine corruption and delay."""
            if ByzantineFaultInjector.should_lie():
                msg = ByzantineFaultInjector.corrupt_message(msg)
            with locked(network):
                if to_node not in network['partitioned']:
                    network['messages'].append((to_node, msg, time.time()))
        
        def raft_node(node_id):
            """Raft state machine with speculative execution."""
            me = nodes[node_id]
            
            try:
                while committed_entries[0] < 100 and races_detected[0] < 10:
                    state = me['state'][0]
                    
                    if state == 'follower':
                        # Check for heartbeat timeout
                        time.sleep(0.01 * random.random())
                        
                        # Process messages
                        with locked(network):
                            pending = [m for m in network['messages'] 
                                      if m[0] == node_id]
                            network['messages'] = deque(
                                m for m in network['messages'] 
                                if m[0] != node_id
                            )
                        
                        for _, msg, _ in pending:
                            if msg.get('type') == 'append_entries':
                                leader_term = msg['term']
                                entries = msg['entries']
                                leader_commit = msg['leader_commit']
                                
                                # SPECULATIVE EXECUTION RACE:
                                # Apply entries before commit for "performance"
                                with locked(me['log']):
                                    for entry in entries:
                                        me['log'].append(entry)
                                
                                # Speculatively apply to state machine
                                for entry in entries:
                                    with locked(me['speculative_applied']):
                                        me['speculative_applied'].append(entry)
                                        me['speculative_index'][0] += 1
                                
                                # But wait! What if we crash here?
                                # Or if leader changes?
                                # The speculative state is now inconsistent!
                                
                                # RACE: Check commit index without lock on log
                                if leader_commit > me['commit_index'][0]:
                                    # This read-modify-write is racy
                                    new_commit = min(leader_commit, len(me['log']))
                                    old_commit = me['commit_index'][0]
                                    me['commit_index'][0] = new_commit
                                    
                                    # Check for speculative violation
                                    if me['speculative_index'][0] > new_commit:
                                        # We speculatively applied uncommitted entries!
                                        speculative_violations.append({
                                            'node': node_id,
                                            'speculative': me['speculative_index'][0],
                                            'committed': new_commit,
                                            'violation': me['speculative_applied'][new_commit:]
                                        })
                                        
                                        # Rollback - but another thread might be reading!
                                        # RACE: Truncating while another thread iterates
                                        with locked(me['speculative_applied']):
                                            rollback_entries = me['speculative_applied'][new_commit:]
                                            me['speculative_applied'] = me['speculative_applied'][:new_commit]
                                            me['speculative_index'][0] = new_commit
                                
                                committed_entries[0] = max(committed_entries[0], new_commit)
                                
                    elif state == 'leader':
                        # Send heartbeats
                        for peer in range(5):
                            if peer != node_id:
                                with locked(me['log']):
                                    entries = list(me['log'])  # Copy without lock on entries!
                                
                                send_message(peer, {
                                    'type': 'append_entries',
                                    'term': me['term'][0],
                                    'entries': entries,
                                    'leader_commit': me['commit_index'][0]
                                })
                        
                        time.sleep(0.005)
                        
            except RaceConditionError as e:
                races_detected[0] += 1
                # Try to recover - but recovery itself might race!
                try:
                    with locked(me['state']):
                        me['state'][0] = 'follower'
                except RaceConditionError:
                    pass  # Double race!
        
        # Start all nodes
        threads = [threading.Thread(target=raft_node, args=(i,)) 
                   for i in range(5)]
        
        # Add network partition chaos
        def chaos_partition():
            while committed_entries[0] < 50:
                time.sleep(0.05)
                with locked(network):
                    # Randomly partition nodes
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
        
        # Verify safety properties
        if speculative_violations:
            print("SAFETY VIOLATION: Speculative execution leaked uncommitted state!")
    
    def test_paxos_acceptor_preempt_race(self):
        """
        Paxos acceptor handling prepare and accept messages concurrently
        with preemption, creating dangling promises.
        """
        configure(mode="raise")
        
        # Single acceptor, multiple proposers
        acceptor_state = protect({
            'promised_ballot': -1,
            'accepted_ballot': -1,
            'accepted_value': None,
            'promises': {},  # ballot -> set of values seen
        })
        
        chosen_values = []
        races = []
        
        def proposer(proposer_id):
            """Proposer with increasing ballot numbers."""
            for round_num in range(20):
                ballot = (round_num, proposer_id)
                
                try:
                    # Phase 1: Prepare
                    with locked(acceptor_state):
                        if ballot > acceptor_state['promised_ballot']:
                            # RACE: Promise made, but not recorded atomically
                            old_promise = acceptor_state['promised_ballot']
                            acceptor_state['promised_ballot'] = ballot
                            
                            # Gap here - another proposer might sneak in!
                            time.sleep(0.0001)
                            
                            # Record what we've promised
                            if ballot not in acceptor_state['promises']:
                                acceptor_state['promises'][ballot] = set()
                    
                    # Phase 2: Accept (maybe)
                    # Check if we're still the highest promise
                    with locked(acceptor_state):
                        if acceptor_state['promised_ballot'] == ballot:
                            # We can accept
                            value = f"value_{proposer_id}_{round_num}"
                            
                            # RACE: Multiple proposers might think they won
                            if acceptor_state['accepted_ballot'] < ballot:
                                acceptor_state['accepted_ballot'] = ballot
                                acceptor_state['accepted_value'] = value
                                chosen_values.append((ballot, value))
                        else:
                            # We were preempted!
                            # But we already promised! Dangling promise!
                            pass
                            
                except RaceConditionError as e:
                    races.append((proposer_id, ballot, e))
        
        # Start multiple proposers simultaneously
        threads = [threading.Thread(target=proposer, args=(i,)) 
                   for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Check for safety violations
        if len(chosen_values) > 1:
            ballots = [v[0] for v in chosen_values]
            if len(set(ballots)) != len(ballots):
                print("SAFETY VIOLATION: Multiple values chosen for same ballot!")
        
        print(f"Paxos: {len(chosen_values)} values chosen, {len(races)} races")

# ============================================
    def test_viewstamped_replication_primary_view_change_race(self):
        """
        VR protocol where primary fails during view change,
        causing split-brain with divergent operation logs.
        """
        configure(mode="raise")
        
        replicas = [{
            'id': i,
            'view': protect([0]),
            'status': protect(['normal']),  # normal, view_change, recovering
            'op_log': protect([]),
            'commit_num': protect([0]),
            'client_table': protect({}),  # client_id -> (req_id, result)
            'prepare_oks': protect({}),  # op -> set of replicas
        } for i in range(5)]
        
        primary = [0]  # Current primary index
        view_changes = [0]
        split_brain_detected = [False]
        
        def replica_main(replica_id):
            me = replicas[replica_id]
            
            try:
                while view_changes[0] < 5:
                    current_primary = primary[0]
                    
                    if replica_id == current_primary and me['status'][0] == 'normal':
                        # Acting as primary
                        for op_num in range(me['commit_num'][0] + 1, 
                                          me['commit_num'][0] + 10):
                            # Send prepares to backups
                            for backup in range(5):
                                if backup != replica_id:
                                    # RACE: Prepare sent without full sync
                                    pass
                            
                            # Wait for prepare_oks
                            time.sleep(0.001)
                            
                            # Check if we have majority
                            with locked(me['prepare_oks']):
                                oks = me['prepare_oks'].get(op_num, set())
                                if len(oks) >= 2:  # 3 of 5 = majority
                                    with locked(me['commit_num']):
                                        me['commit_num'][0] = op_num
                    
                    else:
                        # Backup - check for view change
                        time.sleep(0.005)
                        
                        # Simulate missed heartbeat -> start view change
                        if random.random() < 0.1:
                            with locked(me['status']):
                                if me['status'][0] == 'normal':
                                    me['status'][0] = 'view_change'
                                    # RACE: Multiple replicas start view change
                                    view_changes[0] += 1
                                    
                                    # Become primary of new view
                                    new_view = me['view'][0] + 1
                                    me['view'][0] = new_view
                                    
                                    # CRITICAL RACE: Old primary might still be active!
                                    # Both think they're primary!
                                    if replica_id != current_primary:
                                        # Check if old primary still thinks it's primary
                                        old_primary_log_len = len(replicas[current_primary]['op_log'])
                                        my_log_len = len(me['op_log'])
                                        
                                        if old_primary_log_len > my_log_len:
                                            # Old primary committed ops we don't know about!
                                            split_brain_detected[0] = True
                                            print(f"SPLIT BRAIN: Replica {replica_id} (view {new_view}) "
                                                  f"vs Primary {current_primary} "
                                                  f"(log {old_primary_log_len} vs {my_log_len})")
                                    
                                    # Try to become new primary
                                    primary[0] = replica_id
                                    me['status'][0] = 'normal'
                                    
            except RaceConditionError as e:
                pass
        
        threads = [threading.Thread(target=replica_main, args=(i,)) 
                   for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        
        print(f"VR: {view_changes[0]} view changes, "
              f"split brain: {split_brain_detected[0]}")

# ============================================
# HARDWARE-LEVEL MEMORY MODEL TORTURE
# ============================================

class TestHardwareMemoryModel:
    """
    Tests that simulate hardware memory model violations that
    are invisible to standard race detectors.
    """
    
    def test_store_buffer_forwarding_race(self):
        """
        CPU store buffer forwarding - stores visible to own CPU
        before globally visible.
        """
        configure(mode="raise")
        
        # Simulate per-CPU store buffers
        store_buffers = [protect({}) for _ in range(4)]  # 4 CPUs
        global_memory = protect({'x': 0, 'y': 0})
        
        observations = []
        
        def cpu_thread(cpu_id):
            """Simulate CPU with store buffer."""
            my_buffer = store_buffers[cpu_id]
            
            try:
                for _ in range(1000):
                    # Write to local store buffer first
                    with locked(my_buffer):
                        my_buffer['x'] = 1
                    
                    # Read from store buffer (fast) vs global memory (slow)
                    local_x = None
                    with locked(my_buffer):
                        if 'x' in my_buffer:
                            local_x = my_buffer['x']  # Store buffer hit
                    
                    # Read y from global memory
                    with locked(global_memory):
                        global_y = global_memory['y']
                    
                    # Now flush store buffer to global memory
                    with locked(my_buffer):
                        with locked(global_memory):
                            for k, v in list(my_buffer.items()):
                                global_memory[k] = v
                            my_buffer.clear()
                    
                    # Record observation
                    observations.append((cpu_id, local_x, global_y))
                    
            except RaceConditionError as e:
                pass
        
        # Coordinate threads to create specific interleaving
        barrier = threading.Barrier(4)
        
        def coordinated_cpu(cpu_id):
            barrier.wait()
            cpu_thread(cpu_id)
        
        threads = [threading.Thread(target=coordinated_cpu, args=(i,)) 
                   for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Analyze for store buffer anomalies
        # (x=1 in local buffer but y=0 globally visible = reordering)
        anomalies = [o for o in observations if o[1] == 1 and o[2] == 0]
        print(f"Store buffer anomalies: {len(anomalies)}")
    
    def test_invalidation_queue_delay_race(self):
        """
        CPU invalidation queue delays - cache invalidations
        batched for performance, causing stale reads.
        """
        configure(mode="raise")
        
        cache_lines = [{
            'valid': protect([True]),
            'data': protect([0]),
            'version': protect([0]),
        } for _ in range(4)]  # 4 cache lines
        
        memory = protect({'data': 0, 'version': 0})
        stale_reads = []
        
        def writer():
            for i in range(1000):
                with locked(memory):
                    memory['data'] = i
                    memory['version'] += 1
                
                # Invalidate all caches (simulated delay)
                for cache in cache_lines:
                    with locked(cache['valid']):
                        # RACE: Invalidation queued but not processed
                        cache['valid'][0] = False  # Mark invalid
                        # But cache might still serve stale data!
        
        def reader(cpu_id):
            my_cache = cache_lines[cpu_id % 4]
            
            for _ in range(1000):
                # Check cache
                cached_valid = False
                cached_data = None
                
                with locked(my_cache['valid']):
                    cached_valid = my_cache['valid'][0]
                    if cached_valid:
                        with locked(my_cache['data']):
                            cached_data = my_cache['data'][0]
                
                if not cached_valid:
                    # Fetch from memory
                    with locked(memory):
                        fresh_data = memory['data']
                        fresh_version = memory['version']
                    
                    # Update cache
                    with locked(my_cache['data']):
                        my_cache['data'][0] = fresh_data
                    with locked(my_cache['valid']):
                        my_cache['valid'][0] = True
                    
                    cached_data = fresh_data
                
                # Verify consistency
                with locked(memory):
                    actual = memory['data']
                
                if cached_data != actual:
                    # Stale read due to delayed invalidation!
                    stale_reads.append((cpu_id, cached_data, actual))
        
        threads = [threading.Thread(target=writer)] + \
                 [threading.Thread(target=reader, args=(i,)) for i in range(4)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Stale cache reads: {len(stale_reads)}")

    def test_load_speculation_misprediction_race(self):
        """
        CPU speculatively loads data, then rolls back on misprediction
        but side effects remain (Spectre-style).
        """
        configure(mode="raise")
        
        secret_data = protect(list(range(1000)))  # "Secret" array
        public_buffer = protect([0] * 256)  # Probe buffer
        cache_hits = [0] * 256
        
        def victim():
            """Victim that accesses secret based on input."""
            for _ in range(10000):
                idx = random.randint(0, 999)
                # Bounds check (speculated past)
                if idx < len(secret_data):
                    secret_val = secret_data[idx]
                    # Transient access to public_buffer
                    # In real hardware, this affects cache state
                    public_buffer[secret_val % 256] = 1
        
        def attacker():
            """Attacker that trains branch predictor then exploits."""
            # Train predictor to always take bounds check
            for _ in range(100):
                pass  # Training
            
            # Now exploit with out-of-bounds
            # (Simulated - we can't actually do speculative execution)
            for i in range(256):
                start = time.perf_counter_ns()
                _ = public_buffer[i]
                end = time.perf_counter_ns()
                
                if end - start < 100:  # Cache hit = accessed speculatively
                    cache_hits[i] += 1
        
        # This test is conceptual - real speculative execution
        # requires assembly-level control
        print("Load speculation test: Conceptual (requires CPU-level control)")

# ============================================
# GIL EXPLOITATION AT BYTECODE LEVEL
# ============================================

class TestGILBytecodeExploitation:
    """
    Exploiting exact bytecode boundaries where GIL is released.
    """
    
    def test_dict_resize_race(self):
        """
        Dictionary resize during insertion - GIL released,
        another thread sees inconsistent hash table.
        """
        configure(mode="raise")
        
        # Dict at resize threshold
        d = protect({i: i for i in range(1000)})  # Almost full
        
        races = []
        lost_keys = []
        
        def inserter(thread_id):
            try:
                for i in range(1000):
                    key = f"thread_{thread_id}_key_{i}"
                    # This may trigger resize
                    d[key] = i
                    
                    # Immediately try to read back
                    if d.get(key) != i:
                        lost_keys.append((thread_id, key, i))
            except (RaceConditionError, RuntimeError) as e:
                # RuntimeError: dictionary changed size during iteration
                races.append(e)
        
        def resizer():
            """Force resizes by growing dict."""
            try:
                for _ in range(100):
                    # Bulk insert to trigger resize
                    temp = {f"bulk_{i}": i for i in range(100)}
                    d.update(temp)
                    # Delete to create holes
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
        """
        List sort releases GIL during comparisons,
        another thread modifies list.
        """
        configure(mode="raise")
        
        lst = protect([random.randint(0, 1000) for _ in range(10000)])
        races = []
        
        def sorter():
            try:
                # Sort releases GIL during key comparison
                with locked(lst):
                    lst.sort()  # May see concurrent modifications
            except (RaceConditionError, ValueError) as e:
                # ValueError: list modified during sort
                races.append(e)
        
        def modifier():
            try:
                for _ in range(100):
                    # Try to modify during sort
                    if lst:
                        idx = random.randint(0, min(100, len(lst)-1))
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
        """
        Concurrent imports of same module - complex locking in importlib.
        """
        configure(mode="raise")
        
        # Create a temporary module that modifies shared state on import
        module_code = """
import time
import random
shared_state = None

def init():
    global shared_state
    # Simulate race in module initialization
    if shared_state is None:
        temp = {}
        time.sleep(0.001)  # Window for race
        shared_state = temp
    return shared_state
"""
        
        import_count = [0]
        race_count = [0]
        
        def importer():
            try:
                # Import the same module concurrently
                import importlib.util
                import sys
                
                spec = importlib.util.spec_from_loader("racey_module", 
                                                       loader=None)
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
        """
        Race between frame evaluation and introspection.
        """
        configure(mode="raise")
        
        frames = protect([])
        race_count = [0]
        
        def recursive_function(n):
            """Function that inspects its own frame."""
            try:
                import sys
                frame = sys._getframe()
                
                # RACE: Append frame while another thread iterates
                frames.append({
                    'function': frame.f_code.co_name,
                    'lineno': frame.f_lineno,
                    'locals': dict(frame.f_locals),
                })
                
                if n > 0:
                    return recursive_function(n-1) + n
                return 0
            except RaceConditionError:
                race_count[0] += 1
                raise
        
        def frame_inspector():
            """Iterate over captured frames."""
            try:
                for _ in range(100):
                    for frame_info in list(frames):
                        # Access frame locals - might be modified concurrently
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
    """
    Races across process boundaries using shared memory.
    """
    
    @pytest.mark.skipif(sys.platform == "win32", reason="Multiprocessing spawn doesn't support local functions")
    def test_shared_memory_race(self):
        """
        multiprocessing.shared_memory with concurrent access.
        """
        configure(mode="raise")
        
        # Create shared memory
        shm = shared_memory.SharedMemory(create=True, size=1024)
        
        try:
            # Write structure to shared memory
            # [counter: int, flag: int, data: bytes]
            
            races = mp.Manager().list()
            
            def worker_process(worker_id):
                """Worker that accesses shared memory directly."""
                try:
                    # Map shared memory
                    buf = shm.buf
                    
                    for _ in range(1000):
                        # Read counter (4 bytes)
                        counter_bytes = bytes(buf[0:4])
                        counter = struct.unpack('I', counter_bytes)[0]
                        
                        # Increment
                        counter += 1
                        
                        # Write back
                        buf[0:4] = struct.pack('I', counter)
                        
                        # No synchronization!
                        
                except Exception as e:
                    races.append(str(e))
            
            # Start processes
            processes = [mp.Process(target=worker_process, args=(i,)) 
                        for i in range(4)]
            
            for p in processes:
                p.start()
            for p in processes:
                p.join()
            
            # Check final counter
            final = struct.unpack('I', bytes(shm.buf[0:4]))[0]
            print(f"Shared memory final counter: {final}, races: {len(races)}")
            # Should be 4000, but likely less due to races
            
        finally:
            shm.close()
            shm.unlink()
    
    def test_mmap_file_race(self):
        """
        Memory-mapped file with page-level races.
        """
        configure(mode="raise")
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Initialize with page-sized data
            f.write(b'\x00' * 4096 * 10)  # 10 pages
            path = f.name
        
        try:
            with open(path, 'r+b') as f:
                mm = mmap.mmap(f.fileno(), 4096 * 10)
                
                # Structure: [lock: int, data: 4092 bytes] per page
                races = []
                
                def page_writer(page_num):
                    """Write to specific page."""
                    try:
                        offset = page_num * 4096
                        for i in range(100):
                            # Check lock
                            lock = struct.unpack('I', mm[offset:offset+4])[0]
                            
                            if lock == 0:  # Try to acquire
                                mm[offset:offset+4] = struct.pack('I', 1)
                                
                                # RACE: Window between check and set!
                                # Another thread might have set it
                                
                                # Write data
                                data = f"page_{page_num}_seq_{i}".encode()
                                mm[offset+4:offset+4+len(data)] = data
                                
                                # Release lock
                                mm[offset:offset+4] = struct.pack('I', 0)
                            
                    except Exception as e:
                        races.append(e)
                
                # Hammer same page from multiple threads
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
        """
        Scatter/gather I/O with concurrent buffer modification.
        """
        configure(mode="raise")
        
        # Create socket pair
        s1, s2 = socket.socketpair()
        
        send_buffer = protect(bytearray(b"initial data"))
        races = []
        
        def sender():
            """Send buffer while it's being modified."""
            try:
                for _ in range(100):
                    # Gather I/O - send multiple buffers
                    # RACE: Buffer modified between gather and send
                    with locked(send_buffer):
                        data = bytes(send_buffer)  # Copy? Or reference?
                    
                    s1.send(data)
                    time.sleep(0.0001)
            except RaceConditionError as e:
                races.append(e)
        
        def modifier():
            """Modify buffer during send."""
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
# SIGNAL-DRIVEN PREEMPTION HELL
# ============================================

import pytest
import sys

@pytest.mark.skipif(sys.platform == "win32", reason="Unix signals and fork are not supported on Windows")
class TestSignalPreemptionHell:
    """
    Unix signals causing preemption at worst possible moment.
    """
    
    def test_sigalrm_critical_section_race(self):
        """
        SIGALRM arrives during locked operation.
        """
        configure(mode="raise")
        
        data = protect([0])
        interrupted_count = [0]
        
        def alarm_handler(signum, frame):
            """Handler runs in main thread context."""
            try:
                # Try to access data from signal handler
                # This interrupts the main thread's critical section!
                data[0] += 1000
            except:
                interrupted_count[0] += 1
        
        signal.signal(signal.SIGALRM, alarm_handler)
        
        def critical_worker():
            for _ in range(100):
                try:
                    # Set alarm to fire during critical section
                    signal.setitimer(signal.ITIMER_REAL, 0.00001, 0)
                    
                    # Begin critical section
                    with locked(data):
                        old = data[0]
                        
                        # Alarm fires HERE - handler runs now!
                        # But we hold the lock... deadlock? Or reentrancy?
                        
                        time.sleep(0.001)  # Simulate work
                        data[0] = old + 1
                    
                    signal.alarm(0)  # Cancel
                    
                except RaceConditionError:
                    pass
        
        # Must run in main thread for signal delivery
        critical_worker()
        print(f"Signal interruptions: {interrupted_count[0]}")
    
    def test_sigchld_zombie_race(self):
        """
        SIGCHLD arrives while processing child status.
        """
        configure(mode="raise")
        
        children = protect({})
        zombie_count = [0]
        
        def chld_handler(signum, frame):
            """Handle child termination."""
            try:
                while True:
                    try:
                        pid, status = os.waitpid(-1, os.WNOHANG)
                        if pid == 0:
                            break
                        
                        # RACE: Another thread might be iterating children
                        children[pid] = {'status': status, 'zombie': True}
                        zombie_count[0] += 1
                    except ChildProcessError:
                        break
            except RaceConditionError:
                pass
        
        signal.signal(signal.SIGCHLD, chld_handler)
        
        def spawner():
            for _ in range(10):
                pid = os.fork()
                if pid == 0:
                    # Child
                    os._exit(0)
                else:
                    # Parent - record child
                    try:
                        with locked(children):
                            children[pid] = {'status': None, 'zombie': False}
                    except RaceConditionError:
                        pass
                    
                    time.sleep(0.01)
        
        def inspector():
            for _ in range(50):
                try:
                    # Iterate children - may race with SIGCHLD handler
                    for pid, info in list(children.items()):
                        if info.get('zombie'):
                            # Reap zombie
                            pass
                    time.sleep(0.001)
                except (RaceConditionError, RuntimeError):
                    pass
        
        threads = [threading.Thread(target=spawner),
                  threading.Thread(target=inspector)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print(f"Zombies created: {zombie_count[0]}")

    def test_sigio_async_io_race(self):
        """
        SIGIO-driven async I/O with buffer races.
        """
        configure(mode="raise")
        
        # Create pipe for async I/O
        import fcntl
        r, w = os.pipe()
        fcntl.fcntl(r, fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.fcntl(r, fcntl.F_SETOWN, os.getpid())
        fcntl.fcntl(r, fcntl.F_SETFL, os.O_ASYNC)
        
        read_buffer = protect(bytearray())
        races = []
        
        def io_handler(signum, frame):
            """SIGIO handler - reads available data."""
            try:
                while True:
                    try:
                        chunk = os.read(r, 1024)
                        if not chunk:
                            break
                        # RACE: Appending while main thread processes
                        read_buffer.extend(chunk)
                    except BlockingIOError:
                        break
            except RaceConditionError:
                races.append("SIGIO race")
        
        signal.signal(signal.SIGIO, io_handler)
        
        def writer():
            for i in range(100):
                os.write(w, f"chunk_{i}\n".encode())
                time.sleep(0.0001)
        
        def processor():
            """Process buffer while SIGIO appends."""
            try:
                for _ in range(100):
                    with locked(read_buffer):
                        # Process available data
                        if b'\n' in read_buffer:
                            idx = read_buffer.index(b'\n')
                            line = bytes(read_buffer[:idx+1])
                            read_buffer[:idx+1] = b''  # Remove processed
                    time.sleep(0.0001)
            except RaceConditionError:
                races.append("processor race")
        
        threads = [threading.Thread(target=writer),
                  threading.Thread(target=processor)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        os.close(r)
        os.close(w)
        print(f"SIGIO races: {len(races)}")

# ============================================
# GC FINALIZER RESURRECTION CYCLES
# ============================================

class TestGCFinalizerResurrection:
    """
    Object resurrection during finalization creating immortal cycles.
    """
    
    def test_phantom_reference_race(self):
        """
        Phantom references allowing access to being-collected objects.
        """
        configure(mode="raise")
        
        phantom_queue = queue.Queue()
        resurrection_count = [0]
        races = []
        
        class PhantomObject:
            def __init__(self, value):
                self.value = value
                self.ref = weakref.ref(self, self._finalizer)
            
            def _finalizer(self, ref):
                """Called when object should be collected."""
                try:
                    # RACE: Try to resurrect by adding back to global
                    phantom_queue.put(self.value)
                    resurrection_count[0] += 1
                except RaceConditionError as e:
                    races.append(e)
        
        def creator():
            for i in range(1000):
                obj = PhantomObject(i)
                # Drop reference
                del obj
                if i % 100 == 0:
                    gc.collect()
        
        def consumer():
            for _ in range(1000):
                try:
                    value = phantom_queue.get(timeout=0.1)
                    # Process resurrected value
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
        """
        Finalizer that resurrects object, which gets finalized again.
        """
        configure(mode="raise")
        
        class ImmortalObject:
            _instances = protect([])
            _finalizing = set()
            
            def __init__(self, id):
                self.id = id
                self.resurrected = False
            
            def __del__(self):
                if id(self) in ImmortalObject._finalizing:
                    # Already finalizing - prevent infinite loop
                    return
                
                try:
                    ImmortalObject._finalizing.add(id(self))
                    
                    # Resurrect!
                    with locked(ImmortalObject._instances):
                        ImmortalObject._instances.append(self)
                    
                    self.resurrected = True
                    ImmortalObject._finalizing.remove(id(self))
                    
                except RaceConditionError:
                    pass
        
        def stress_test():
            for i in range(100):
                obj = ImmortalObject(i)
                # Create and drop
                del obj
                
                if i % 10 == 0:
                    gc.collect()
                    
                    # Clear some instances to allow collection
                    with locked(ImmortalObject._instances):
                        if ImmortalObject._instances:
                            ImmortalObject._instances.pop(0)
        
        threads = [threading.Thread(target=stress_test) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        with locked(ImmortalObject._instances):
            remaining = len(ImmortalObject._instances)
        print(f"Immortal objects remaining: {remaining}")

# ============================================
# THE FINAL APOCALYPSE - EVERYTHING AT ONCE
# ============================================

class TestFinalApocalypse:
    """
    The perfect storm: All previous tests running simultaneously
    with additional cross-cutting concerns.
    """
    
    @pytest.mark.skipif(sys.platform == "win32", reason="Unix signals are not supported on Windows")
    def test_everything_everywhere_all_at_once(self):
        """
        Raft consensus + hardware memory model + GIL exploitation +
        cross-process shared memory + signal preemption + GC chaos.
        """
        configure(mode="raise")
        
        # Shared apocalypse state
        apocalypse_state = protect({
            'consensus_log': [],
            'hardware_registers': {},
            'gil_releases': 0,
            'signal_deliveries': 0,
            'gc_collections': 0,
            'process_deaths': 0,
        })
        
        # Quantum-entangled state (simulated)
        quantum_state = QuantumBit()
        
        races = [0]
        violations = []
        
        def chaos_orchestrator():
            """Randomly trigger chaos events."""
            while races[0] < 100:
                event = random.choice(['gc', 'signal', 'resize', 'partition'])
                
                if event == 'gc':
                    gc.collect()
                    with locked(apocalypse_state):
                        apocalypse_state['gc_collections'] += 1
                
                elif event == 'signal':
                    signal.alarm(1)  # Will be caught by handler
                
                elif event == 'resize':
                    # Force dict/list resize
                    pass
                
                elif event == 'partition':
                    # Network partition in consensus
                    pass
                
                time.sleep(0.001)
        
        def distributed_consensus_node(node_id):
            """Raft node with all chaos applied."""
            try:
                for _ in range(50):
                    # Read state (may see partial update due to hardware reordering)
                    with locked(apocalypse_state):
                        log_len = len(apocalypse_state['consensus_log'])
                    
                    # Propose entry
                    entry = {
                        'term': random.randint(1, 10),
                        'node': node_id,
                        'quantum': quantum_state.observe(),
                    }
                    
                    # Append with potential race
                    with locked(apocalypse_state):
                        apocalypse_state['consensus_log'].append(entry)
                    
                    # Speculative apply (may need rollback)
                    time.sleep(0.0001)
                    
            except RaceConditionError:
                races[0] += 1
        
        def hardware_memory_thread():
            """Simulate store buffer forwarding."""
            try:
                for _ in range(100):
                    # Write to local store buffer
                    temp = {'key': random.randint(0, 1000)}
                    
                    # Flush to global (delayed)
                    time.sleep(0.0001)
                    
                    with locked(apocalypse_state):
                        apocalypse_state['hardware_registers'].update(temp)
                        
            except RaceConditionError:
                races[0] += 1
        
        def gil_exploiter():
            """Exploit GIL at bytecode boundaries."""
            try:
                d = {}
                for i in range(1000):
                    # Dict operation that may resize
                    d[f"key_{i}"] = i
                    
                    # List sort that releases GIL
                    lst = list(d.values())
                    lst.sort()
                    
                    # Check consistency
                    if len(lst) != len(d):
                        violations.append("GIL consistency violation")
                        
            except (RaceConditionError, ValueError):
                races[0] += 1
        
        def signal_handler(signum, frame):
            """Async signal during anything."""
            try:
                with locked(apocalypse_state):
                    apocalypse_state['signal_deliveries'] += 1
            except RaceConditionError:
                races[0] += 1
        
        signal.signal(signal.SIGALRM, signal_handler)
        
        # Launch all chaos
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
        
        print(f"APOCALYPSE COMPLETE: {races[0]} races, {len(violations)} violations")
        print(f"GC collections: {apocalypse_state['gc_collections']}")
        print(f"Signal deliveries: {apocalypse_state['signal_deliveries']}")

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
    
    # Run with maximum verbosity and no capture
    sys.exit(pytest.main([
        "-v",
        "-s",  # No capture
        "--tb=long",
        "-x",  # Fail fast
        "--timeout=60",  # Per-test timeout
        __file__
    ]))
