import pytest
import threading
import multiprocessing
import signal
import os
import time
from collections import deque

from raceguard import protect, configure, clear_warnings, RaceConditionError

@pytest.fixture(autouse=True)
def reset_config_extreme():
    configure(enabled=True, race_window=1.0, mode="raise", max_warnings=1000)
    clear_warnings()
    yield
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000)
    clear_warnings()


def _child_process_worker(proxied_shared):
    try:
        proxied_shared.append("from child")
    except Exception:
        pass

class TestExtremeAIBlindspots:

    @pytest.mark.skipif(os.name == 'nt', reason="Signals (like alarm) are Unix-specific and not fully supported on Windows")
    def test_synchronous_signal_handler_interruption(self):
        """EXPLOIT: The OS interrupts the exact same OS thread mid-operation without changing threading.get_ident().
        Raceguard falsely assumes consecutive accesses from the identical thread ID are safe sequential operations."""
        shared = protect([0])
        errors = deque()

        # The signal handler runs on the main thread, interrupting it
        def interrupt_handler(signum, frame):
            try:
                # Modifying the proxy exactly when the main thread has just evaluated its values
                shared[0] += 1
            except RaceConditionError as e:
                errors.append(e)

        # Set up a timer to interrupt in 10ms
        signal.signal(signal.SIGALRM, interrupt_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.01)

        try:
            # Drop into a tight busy loop reading/writing the proxy, waiting for the signal to hit
            for _ in range(50000):
                val = shared[0]
                # During this window, the OS sends the SIGALRM and calls interrupt_handler!
                shared[0] = val + 1
        except RaceConditionError as e:
            errors.append(e)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)

        # Since it's the same exact Thread ID, raceguard thinks it is the same sequential actor!
        assert len(errors) == 0, "Wait, raceguard hooked into OS signals? Found a RaceConditionError!"

    @pytest.mark.skipif(os.name == 'nt', reason="Multiprocessing spawn on Windows cannot pickle proxies.")
    def test_multiprocessing_fork_memory_clone(self):
        """EXPLOIT: Forking the process duplicates tracking memory, locks, and history. They diverge."""
        shared = protect([0])
                
        # We start a separate process (must use multiprocessing to force isolated boundaries)
        p = multiprocessing.Process(target=_child_process_worker, args=(shared,))
        p.start()
        
        # Parent mutates
        shared.append("from parent")
        
        p.join()
        
        # Multiprocessing naturally fails to share standard Python objects unless backed by 
        # multiprocessing.Manager. Therefore, `shared` in the main thread only sees "from parent".
        # This completely breaks raceguard's illusion since concurrency spans processes natively, not threads!
        assert len(shared) == 2, "Expected 2 items (`0`, `from parent`)"
        assert "from child" not in shared

    def test_metaclass_dunder_overrides(self):
        """EXPLOIT: Mutating the class of the raw object or dynamically injecting hooks to bypass known types."""
        # _MUTATING_METHODS is hardcoded to specific standard library types
        class CustomDict(dict):
            pass

        shared = protect(CustomDict({"x": 1}))
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                # Dynamically set a mutating field completely circumventing built-in knowledge
                shared.update({"x": 2})
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # `_MUTATING_METHODS` tracks `dict` but might fail if CustomDict inherits from it but alters signatures!
        # If `raceguard`'s type checking fails to realize `CustomDict` inherits `dict` mutations, this bypasses it.
        # Wait! It uses `type` mapping or recursive `issubclass` matching?
        # Actually, `raceguard` uses `isinstance`, so it caught it!
        assert len(errors) > 0, "Raceguard failed to map dynamically inferred subclasses."
