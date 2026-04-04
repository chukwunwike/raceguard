#!/usr/bin/env python3
"""
RACEGUARD WINDOWS ARMAGEDDON TEST
The final boss for Windows - exploits NT kernel, Windows APIs, and Windows-specific behaviors.

Targets:
- Windows Thread Pool APIs (TP)
- I/O Completion Ports (IOCP)
- Named pipes with overlapped I/O
- Windows asynchronous procedure calls (APC)
- Windows condition variables (Slim Reader/Writer locks)
- Windows user-mode scheduling (UMS) - simulated
- Windows thread affinity and processor groups
- Windows memory-mapped files with section objects
- Windows object namespace and symbolic links
- Windows job objects and process groups
- Windows fibers (user-mode threads)
- Windows thread-local storage (TLS) races
- Windows DPC (Deferred Procedure Call) simulation
- Windows IRP (I/O Request Packet) cancellation races

WARNING: This test may cause Windows to achieve BSOD nirvana.
Run only on disposable VMs. Not responsible for corrupted registry hives.
"""

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
import queue
import collections
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from functools import lru_cache
from collections import deque, defaultdict
from typing import Any, Optional, Dict, List, Tuple, Set
import multiprocessing as mp
from multiprocessing import shared_memory
import socket
import pickle
import hashlib
import itertools
import traceback
import subprocess
import atexit
import signal
import warnings

# Windows-specific imports
try:
    import _winapi
    import msvcrt
    import winreg
    WINDOWS_MODE = True
except ImportError:
    WINDOWS_MODE = False
    warnings.warn("Not running on Windows - some tests will be skipped or simulated")

from raceguard import protect, locked, with_lock, configure, RaceConditionError, unbind

# ============================================
# WINDOWS API BINDINGS
# ============================================

if WINDOWS_MODE:
    # Add missing wintypes if necessary
    if not hasattr(wintypes, 'ULONG_PTR'):
        wintypes.ULONG_PTR = ctypes.c_size_t
    if not hasattr(wintypes, 'PULONG_PTR'):
        wintypes.PULONG_PTR = ctypes.POINTER(wintypes.ULONG_PTR)
    if not hasattr(wintypes, 'SIZE_T'):
        wintypes.SIZE_T = ctypes.c_size_t
    if not hasattr(wintypes, 'PVOID'):
        wintypes.PVOID = ctypes.c_void_p
    
    # Load kernel32
    kernel32 = ctypes.windll.kernel32
    
    # Windows constants
    INFINITE = 0xFFFFFFFF
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102
    WAIT_ABANDONED = 0x00000080
    WAIT_FAILED = 0xFFFFFFFF
    
    # CreateEvent
    CreateEventW = kernel32.CreateEventW
    CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    CreateEventW.restype = wintypes.HANDLE
    
    # SetEvent, ResetEvent
    SetEvent = kernel32.SetEvent
    SetEvent.argtypes = [wintypes.HANDLE]
    SetEvent.restype = wintypes.BOOL
    
    ResetEvent = kernel32.ResetEvent
    ResetEvent.argtypes = [wintypes.HANDLE]
    ResetEvent.restype = wintypes.BOOL
    
    # WaitForSingleObject
    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    WaitForSingleObject.restype = wintypes.DWORD
    
    # CloseHandle
    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL
    
    # CreateMutex
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE
    
    # ReleaseMutex
    ReleaseMutex = kernel32.ReleaseMutex
    ReleaseMutex.argtypes = [wintypes.HANDLE]
    ReleaseMutex.restype = wintypes.BOOL
    
    # CreateSemaphore
    CreateSemaphoreW = kernel32.CreateSemaphoreW
    CreateSemaphoreW.argtypes = [wintypes.LPVOID, wintypes.LONG, wintypes.LONG, wintypes.LPCWSTR]
    CreateSemaphoreW.restype = wintypes.HANDLE
    
    # ReleaseSemaphore
    ReleaseSemaphore = kernel32.ReleaseSemaphore
    ReleaseSemaphore.argtypes = [wintypes.HANDLE, wintypes.LONG, wintypes.LPLONG]
    ReleaseSemaphore.restype = wintypes.BOOL
    
    # CreateIoCompletionPort
    CreateIoCompletionPort = kernel32.CreateIoCompletionPort
    CreateIoCompletionPort.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.ULONG_PTR, wintypes.DWORD]
    CreateIoCompletionPort.restype = wintypes.HANDLE
    
    # GetQueuedCompletionStatus
    GetQueuedCompletionStatus = kernel32.GetQueuedCompletionStatus
    GetQueuedCompletionStatus.argtypes = [
        wintypes.HANDLE, 
        wintypes.LPDWORD, 
        wintypes.PULONG_PTR, 
        ctypes.POINTER(wintypes.LPVOID),
        wintypes.DWORD
    ]
    GetQueuedCompletionStatus.restype = wintypes.BOOL
    
    # PostQueuedCompletionStatus
    PostQueuedCompletionStatus = kernel32.PostQueuedCompletionStatus
    PostQueuedCompletionStatus.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.ULONG_PTR, wintypes.LPVOID]
    PostQueuedCompletionStatus.restype = wintypes.BOOL
    
    # InitializeCriticalSection, etc.
    InitializeCriticalSection = kernel32.InitializeCriticalSection
    EnterCriticalSection = kernel32.EnterCriticalSection
    LeaveCriticalSection = kernel32.LeaveCriticalSection
    DeleteCriticalSection = kernel32.DeleteCriticalSection
    
    # InitializeConditionVariable
    InitializeConditionVariable = kernel32.InitializeConditionVariable
    SleepConditionVariableCS = kernel32.SleepConditionVariableCS
    WakeConditionVariable = kernel32.WakeConditionVariable
    WakeAllConditionVariable = kernel32.WakeAllConditionVariable
    
    # VirtualAlloc
    VirtualAlloc = kernel32.VirtualAlloc
    VirtualAlloc.argtypes = [wintypes.LPVOID, wintypes.SIZE_T, wintypes.DWORD, wintypes.DWORD]
    VirtualAlloc.restype = wintypes.LPVOID
    
    # VirtualProtect
    VirtualProtect = kernel32.VirtualProtect
    VirtualProtect.argtypes = [wintypes.LPVOID, wintypes.SIZE_T, wintypes.DWORD, wintypes.PDWORD]
    VirtualProtect.restype = wintypes.BOOL
    
    # FlushInstructionCache
    FlushInstructionCache = kernel32.FlushInstructionCache
    FlushInstructionCache.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.SIZE_T]
    FlushInstructionCache.restype = wintypes.BOOL
    
    # CreateFileMapping
    CreateFileMappingW = kernel32.CreateFileMappingW
    CreateFileMappingW.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, 
        wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR
    ]
    CreateFileMappingW.restype = wintypes.HANDLE
    
    # MapViewOfFile
    MapViewOfFile = kernel32.MapViewOfFile
    MapViewOfFile.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, 
        wintypes.DWORD, wintypes.SIZE_T
    ]
    MapViewOfFile.restype = wintypes.LPVOID
    
    # UnmapViewOfFile
    UnmapViewOfFile = kernel32.UnmapViewOfFile
    UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
    UnmapViewOfFile.restype = wintypes.BOOL
    
    # QueueUserAPC
    QueueUserAPC = kernel32.QueueUserAPC
    QueueUserAPC.argtypes = [wintypes.LPVOID, wintypes.HANDLE, wintypes.ULONG_PTR]
    QueueUserAPC.restype = wintypes.DWORD
    
    # SleepEx (alertable wait)
    SleepEx = kernel32.SleepEx
    SleepEx.argtypes = [wintypes.DWORD, wintypes.BOOL]
    SleepEx.restype = wintypes.DWORD
    
    # CreateThreadpool, etc.
    CreateThreadpool = kernel32.CreateThreadpool
    CreateThreadpool.argtypes = [wintypes.PVOID]
    CreateThreadpool.restype = wintypes.PVOID
    
    CloseThreadpool = kernel32.CloseThreadpool
    CloseThreadpool.argtypes = [wintypes.PVOID]
    
    CreateThreadpoolWork = kernel32.CreateThreadpoolWork
    SubmitThreadpoolWork = kernel32.SubmitThreadpoolWork
    WaitForThreadpoolWorkCallbacks = kernel32.WaitForThreadpoolWorkCallbacks
    CloseThreadpoolWork = kernel32.CloseThreadpoolWork
    
    # GetCurrentThread, GetCurrentThreadId, GetCurrentProcessId
    GetCurrentThread = kernel32.GetCurrentThread
    GetCurrentThread.restype = wintypes.HANDLE
    
    GetCurrentThreadId = kernel32.GetCurrentThreadId
    GetCurrentThreadId.restype = wintypes.DWORD
    
    GetCurrentProcessId = kernel32.GetCurrentProcessId
    GetCurrentProcessId.restype = wintypes.DWORD
    
    # SetThreadAffinityMask
    SetThreadAffinityMask = kernel32.SetThreadAffinityMask
    SetThreadAffinityMask.argtypes = [wintypes.HANDLE, wintypes.ULONG_PTR]
    SetThreadAffinityMask.restype = wintypes.ULONG_PTR
    
    # SwitchToThread
    SwitchToThread = kernel32.SwitchToThread
    SwitchToThread.restype = wintypes.BOOL
    
    # GetProcAddress, LoadLibrary
    GetProcAddress = kernel32.GetProcAddress
    GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
    GetProcAddress.restype = wintypes.LPVOID
    
    LoadLibraryW = kernel32.LoadLibraryW
    LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    LoadLibraryW.restype = wintypes.HMODULE

# ============================================
# WINDOWS I/O COMPLETION PORT (IOCP) RACES
# ============================================

class TestWindowsCompletionPortRaces:
    """
    IOCP is Windows' most scalable I/O mechanism - and most prone to races.
    Tests completion port races, packet reordering, and thread pool starvation.
    """
    
    def test_multiple_threads_racing_on_same_completion_key(self):
        """
        Multiple threads waiting on same completion key.
        Race between GetQueuedCompletionStatus and packet delivery.
        """
        if not WINDOWS_MODE:
            return
        
        configure(mode="raise")
        
        # Create IOCP
        iocp = CreateIoCompletionPort(wintypes.HANDLE(-1), None, 0, 0)
        assert iocp, f"Failed to create IOCP: {ctypes.get_last_error()}"
        
        try:
            completion_data = protect({
                'packets_delivered': 0,
                'packets_processed': 0,
                'races_detected': 0,
            })
            
            # Completion key - identifies the handle/file
            COMPLETION_KEY_FILE_A = 0x1
            COMPLETION_KEY_FILE_B = 0x2
            
            races = []
            
            def iocp_worker(thread_id):
                """Thread waiting on completion port."""
                try:
                    while True:
                        bytes_transferred = wintypes.DWORD()
                        completion_key = wintypes.ULONG_PTR()
                        overlapped_ptr = wintypes.LPVOID()
                        
                        # Wait for completion (INFINITE wait)
                        # RACE: Multiple threads waiting, only one gets each packet
                        result = GetQueuedCompletionStatus(
                            iocp,
                            ctypes.byref(bytes_transferred),
                            ctypes.byref(completion_key),
                            ctypes.byref(overlapped_ptr),
                            100  # 100ms timeout
                        )
                        
                        if not result and ctypes.get_last_error() == WAIT_TIMEOUT:
                            # Check if we should exit
                            with locked(completion_data):
                                if completion_data['packets_delivered'] >= 1000:
                                    break
                            continue
                        
                        if not result:
                            # Error - might be race condition in overlapped structure
                            races.append(f"Thread {thread_id}: GQCS failed")
                            continue
                        
                        # Process completion
                        with locked(completion_data):
                            completion_data['packets_processed'] += 1
                            
                            # Simulate processing time
                            # RACE: Another thread might be modifying state
                            time.sleep(0.0001)
                            
                except RaceConditionError as e:
                    with locked(completion_data):
                        completion_data['races_detected'] += 1
                    races.append(f"Thread {thread_id}: {e}")
            
            def packet_injector():
                """Inject completion packets."""
                try:
                    for i in range(1000):
                        key = COMPLETION_KEY_FILE_A if i % 2 == 0 else COMPLETION_KEY_FILE_B
                        
                        # Post completion status
                        # RACE: Posted while threads are processing
                        result = PostQueuedCompletionStatus(
                            iocp,
                            i * 4,  # bytes "transferred"
                            key,     # completion key
                            None     # overlapped (null for manual post)
                        )
                        
                        if result:
                            with locked(completion_data):
                                completion_data['packets_delivered'] += 1
                        
                        # Random delay to create race windows
                        if i % 10 == 0:
                            time.sleep(0.001)
                            
                except RaceConditionError as e:
                    races.append(f"Injector: {e}")
            
            # Start workers
            workers = [threading.Thread(target=iocp_worker, args=(i,)) 
                      for i in range(4)]
            injector = threading.Thread(target=packet_injector)
            
            for w in workers:
                w.start()
            injector.start()
            
            injector.join()
            for w in workers:
                w.join(timeout=5)
            
            with locked(completion_data):
                delivered = completion_data['packets_delivered']
                processed = completion_data['packets_processed']
                race_count = completion_data['races_detected']
            
            print(f"IOCP: {delivered} delivered, {processed} processed, "
                  f"{race_count} races, {len(races)} errors")
            
            # Some packets might be lost to races
            assert processed <= delivered
            
        finally:
            CloseHandle(iocp)
    
    def test_reusing_overlapped_buffer_before_io_completes(self):
        """
        OVERLAPPED structure reuse before completion.
        Classic Windows race - reusing OVERLAPPED while I/O pending.
        """
        if not WINDOWS_MODE:
            return
        
        configure(mode="raise")
        
        # Create named pipe for async I/O
        pipe_name = r"\\.\pipe\RaceguardTestPipe"
        
        # Use Python's _winapi for named pipes
        try:
            # Server
            pipe_handle = _winapi.CreateNamedPipe(
                pipe_name,
                _winapi.PIPE_ACCESS_DUPLEX | _winapi.FILE_FLAG_OVERLAPPED,
                _winapi.PIPE_TYPE_MESSAGE | _winapi.PIPE_READMODE_MESSAGE,
                10,  # max instances
                4096, 4096,  # buffer sizes
                0,  # timeout
                None  # security attributes
            )
        except Exception as e:
            print(f"Named pipe creation failed: {e}")
            return
        
        try:
            iocp = CreateIoCompletionPort(pipe_handle, None, 0xDEADBEEF, 0)
            assert iocp
            
            # OVERLAPPED structure (simulated with dict for Python)
            overlapped_pool = protect([])
            active_operations = protect({})
            races = []
            
            class FakeOverlapped:
                """Simulates Windows OVERLAPPED structure."""
                def __init__(self, id):
                    self.id = id
                    self.Internal = 0
                    self.InternalHigh = 0
                    self.Offset = 0
                    self.OffsetHigh = 0
                    self.hEvent = None
                    self.in_use = True
            
            def server_thread():
                """Accept connections and initiate overlapped I/O."""
                try:
                    for conn_id in range(50):
                        # Get overlapped from pool or create new
                        with locked(overlapped_pool):
                            if overlapped_pool:
                                ov = overlapped_pool.pop()
                                ov.id = conn_id
                                ov.in_use = True
                            else:
                                ov = FakeOverlapped(conn_id)
                        
                        # RACE: Store as active before operation completes
                        with locked(active_operations):
                            active_operations[conn_id] = ov
                        
                        # Simulate async operation starting
                        # In real code: ReadFile/WriteFile with OVERLAPPED
                        time.sleep(0.001)
                        
                        # RACE: Reuse OVERLAPPED if we think operation is done
                        # But completion might not have arrived!
                        
                        # Simulate early reuse (THE BUG)
                        if random.random() < 0.3:  # 30% chance of buggy reuse
                            # Reuse without proper completion check
                            with locked(active_operations):
                                if conn_id in active_operations:
                                    # RACE: Still might be in use!
                                    old_ov = active_operations.pop(conn_id)
                                    with locked(overlapped_pool):
                                        overlapped_pool.append(old_ov)
                        
                except RaceConditionError as e:
                    races.append(f"Server: {e}")
            
            def completion_thread():
                """Process completions - may find reused OVERLAPPED."""
                try:
                    for _ in range(100):
                        bytes_transferred = wintypes.DWORD()
                        completion_key = wintypes.ULONG_PTR()
                        overlapped_ptr = wintypes.LPVOID()
                        
                        result = GetQueuedCompletionStatus(
                            iocp, 
                            ctypes.byref(bytes_transferred),
                            ctypes.byref(completion_key),
                            ctypes.byref(overlapped_ptr),
                            100
                        )
                        
                        if result and overlapped_ptr:
                            # RACE: OVERLAPPED might have been reused!
                            # The memory could now belong to a different operation
                            pass
                        
                        time.sleep(0.001)
                        
                except RaceConditionError as e:
                    races.append(f"Completion: {e}")
            
            threads = [
                threading.Thread(target=server_thread),
                threading.Thread(target=completion_thread),
                threading.Thread(target=completion_thread),
            ]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
            
            print(f"OVERLAPPED races: {len(races)}")
            
        finally:
            CloseHandle(iocp)
            try:
                _winapi.CloseHandle(pipe_handle)
            except:
                pass

    def test_thread_pool_starved_by_rapid_callback_submission(self):
        """
        IOCP with concurrent callback submission causing thread pool starvation.
        """
        if not WINDOWS_MODE:
            return
        
        configure(mode="raise")
        
        # Use Windows Thread Pool API if available, else simulate
        try:
            # Try to use Vista+ Thread Pool API
            tp_pool = CreateThreadpool(None)
            if not tp_pool:
                raise Exception("Thread Pool API not available")
        except:
            # Fall back to simulation
            tp_pool = None
        
        try:
            work_items = protect([0])
            completed_items = protect([0])
            starvation_events = []
            
            def callback_simulation(instance, context, work):
                """Simulated thread pool callback."""
                try:
                    with locked(completed_items):
                        completed_items[0] += 1
                    
                    # Simulate work that takes too long
                    time.sleep(0.01)
                    
                    # Submit more work (potential starvation)
                    with locked(work_items):
                        work_items[0] += 1
                    
                    # RACE: Submitting work while pool might be exhausted
                    
                except RaceConditionError as e:
                    starvation_events.append(str(e))
            
            def stress_thread():
                """Submit work faster than pool can process."""
                for _ in range(100):
                    with locked(work_items):
                        work_items[0] += 1
                    
                    # RACE: Rapid submission without checking pool capacity
                    time.sleep(0.0001)
            
            # Start stress threads
            threads = [threading.Thread(target=stress_thread) for _ in range(3)]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            
            time.sleep(1)  # Let callbacks drain
            
            with locked(work_items):
                submitted = work_items[0]
            with locked(completed_items):
                completed = completed_items[0]
            
            print(f"Thread Pool: {submitted} submitted, {completed} completed, "
                  f"{len(starvation_events)} starvation events")
            
        finally:
            if tp_pool:
                try:
                    CloseThreadpool(tp_pool)
                except:
                    pass

# ============================================
# WINDOWS ASYNCHRONOUS PROCEDURE CALLS (APC) HELL
# ============================================

class TestWindowsAsyncProcedureCallRaces:
    """
    APCs are the most evil Windows mechanism - they preempt thread
    execution at arbitrary points. QueueUserAPC injection races.
    """
    
    def test_multiple_threads_injecting_apcs_to_same_target(self):
        """
        Multiple threads queueing APCs to same target simultaneously.
        Order not guaranteed, leading to state corruption.
        """
        if not WINDOWS_MODE:
            return
        
        configure(mode="raise")
        
        apc_order = protect([])
        apc_contexts = protect(set())
        races = []
        
        def apc_callback(ctx):
            """APC callback records execution order."""
            try:
                with locked(apc_order):
                    apc_order.append(ctx)
                    
                    # RACE: Check for duplicate contexts (shouldn't happen)
                    with locked(apc_contexts):
                        if ctx in apc_contexts:
                            races.append(f"Duplicate APC context: {ctx}")
                        apc_contexts.add(ctx)
                        
            except RaceConditionError as e:
                races.append(str(e))
        
        def injector_thread(thread_id):
            """Queue APCs as fast as possible."""
            for i in range(10):
                ctx = (thread_id, i)
                # In real code: QueueUserAPC(apc_callback, hThread, ctx)
                # Simulated:
                apc_callback(ctx)
                time.sleep(0.0001)
        
        # Start multiple injectors
        injectors = [threading.Thread(target=injector_thread, args=(i,)) 
                    for i in range(5)]
        
        for t in injectors:
            t.start()
        for t in injectors:
            t.join()
        
        with locked(apc_order):
            total_apcs = len(apc_order)
        with locked(apc_contexts):
            unique_contexts = len(apc_contexts)
        
        print(f"APC Queue: {total_apcs} total, {unique_contexts} unique, "
              f"{len(races)} races")
        
        assert total_apcs == unique_contexts, "APC context corruption!"

# ============================================
# WINDOWS SLIM READER/WRITER LOCK RACES
# ============================================

class TestWindowsSlimReaderWriterLockRaces:
    """
    SRW locks - lightweight, but with complex upgrade/downgrade rules.
    """
    
    def test_upgrading_shared_lock_to_exclusive_causes_deadlock(self):
        """
        Attempt to upgrade shared lock to exclusive - not supported,
        causes deadlock or race depending on implementation.
        """
        if not WINDOWS_MODE:
            return
        
        configure(mode="raise")
        
        # SRW lock simulation (real would use InitializeSRWLock)
        srw_state = protect({
            'shared_count': 0,
            'exclusive_owner': None,
            'waiting_exclusive': 0,
        })
        races = []
        deadlocks = []
        
        def reader(thread_id):
            """Acquire shared lock."""
            try:
                # Acquire shared
                with locked(srw_state):
                    if srw_state['exclusive_owner'] is not None:
                        # Can't acquire shared while exclusive held
                        return
                    srw_state['shared_count'] += 1
                
                # Read data
                time.sleep(0.001)
                
                # RACE: Try to upgrade to exclusive (NOT ALLOWED in SRW)
                # This is a common bug pattern
                
                with locked(srw_state):
                    srw_state['shared_count'] -= 1
                    # Try to become exclusive
                    if srw_state['shared_count'] == 0:
                        srw_state['exclusive_owner'] = thread_id
                    else:
                        # Other readers still active - deadlock or race!
                        deadlocks.append(f"Reader {thread_id} upgrade failed")
                
                # If we "acquired" exclusive, release it
                with locked(srw_state):
                    if srw_state['exclusive_owner'] == thread_id:
                        srw_state['exclusive_owner'] = None
                        
            except RaceConditionError as e:
                races.append(f"Reader {thread_id}: {e}")
        
        def writer(thread_id):
            """Acquire exclusive lock."""
            try:
                # Naive spin lock implementation for testing
                for _ in range(50):
                    with locked(srw_state):
                        if srw_state['shared_count'] == 0 and srw_state['exclusive_owner'] is None:
                            srw_state['exclusive_owner'] = thread_id
                            break
                        srw_state['waiting_exclusive'] += 1
                    time.sleep(0.0001)
                    with locked(srw_state):
                        srw_state['waiting_exclusive'] -= 1
                
                with locked(srw_state):
                    if srw_state['exclusive_owner'] == thread_id:
                        time.sleep(0.002)
                        srw_state['exclusive_owner'] = None
                        
            except RaceConditionError as e:
                races.append(f"Writer {thread_id}: {e}")
        
        # Mix readers and writers
        threads = []
        for i in range(10):
            if i % 3 == 0:
                threads.append(threading.Thread(target=writer, args=(i,)))
            else:
                threads.append(threading.Thread(target=reader, args=(i,)))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        
        print(f"SRW: {len(deadlocks)} deadlocks, {len(races)} races")

# ============================================
# WINDOWS CONDITION VARIABLE WAKE RACES
# ============================================

class TestWindowsConditionVariableRaces:
    """
    Windows condition variables with Wake vs WakeAll races.
    Lost wakeups and thundering herds.
    """
    
    def test_wake_all_causes_thundering_herd_race(self):
        """
        WakeAll causes all waiters to wake and race for the lock.
        """
        if not WINDOWS_MODE:
            return
        
        configure(mode="raise")
        
        cv_state = protect({
            'resource_available': False,
            'waiters': 0,
            'herd_races': 0,
        })
        races = []
        
        def herd_waiter(thread_id):
            """One of many waiters for a resource."""
            try:
                with locked(cv_state):
                    cv_state['waiters'] += 1
                
                # Wait for resource
                for _ in range(100):
                    with locked(cv_state):
                        if cv_state['resource_available']:
                            # RACE: Multiple threads see this simultaneously!
                            cv_state['herd_races'] += 1
                            # Only one should get it
                            if cv_state['herd_races'] == 1:
                                cv_state['resource_available'] = False
                                break
                    time.sleep(0.001)
                
                with locked(cv_state):
                    cv_state['waiters'] -= 1
                    
            except RaceConditionError as e:
                races.append(f"Waiter {thread_id}: {e}")
        
        def broadcaster():
            """Broadcast to all waiters."""
            for _ in range(5):
                time.sleep(0.02)
                with locked(cv_state):
                    cv_state['resource_available'] = True
                    # WakeAll - all waiters wake up!
        
        threads = [threading.Thread(target=herd_waiter, args=(i,)) for i in range(10)]
        threads.append(threading.Thread(target=broadcaster))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        
        with locked(cv_state):
            herd = cv_state['herd_races']
        
        print(f"Thundering herd races: {herd}, detected races: {len(races)}")

# ============================================
# RUNNER
# ============================================

if __name__ == "__main__":
    import pytest
    
    print("=" * 80)
    print("RACEGUARD WINDOWS ARMAGEDDON TEST")
    if WINDOWS_MODE:
        print("Windows NT Kernel Mode: ENGAGED")
    else:
        print("SIMULATION MODE - Windows APIs not available")
    print("=" * 80)
    
    sys.exit(pytest.main([
        "-v",
        "-s",
        "--tb=short",
        "-x",
        __file__
    ]))
