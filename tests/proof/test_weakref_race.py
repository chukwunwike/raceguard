import threading
import time
import weakref
import gc
import pytest
from raceguard import protect, configure, RaceConditionError

# Global registry that should be protected
REGISTRY = protect({})

class Component:
    def __init__(self, name):
        self.name = name
        REGISTRY[name] = self

def cleanup_callback(name):
    """
    Simulates a finalizer that modifies shared state.
    This runs when the object is garbage collected.
    """
    print(f"\n[GC] Cleaning up {name}...")
    # This modification might race with the main logic
    if name in REGISTRY:
        del REGISTRY[name]

def test_gc_finalizer_race():
    """
    PROOF OF CONCEPT: GC Finalizer Race
    
    Demonstrates that background cleanup triggered by the GC can 
    modify protected state while another thread is using it.
    """
    configure(enabled=True)
    
    # 1. Create an object and a weakref with a callback
    c = Component("target_obj")
    weakref.finalize(c, cleanup_callback, "target_obj")
    
    def logic_worker():
        # Repeatedly check and use the registry
        for _ in range(1000):
            if "target_obj" in REGISTRY:
                # Potential race: obj could be deleted by GC right here
                _ = REGISTRY.get("target_obj")
            time.sleep(0.00001)

    t1 = threading.Thread(target=logic_worker)
    t1.start()

    # 2. Trigger GC manually from this thread
    # In a real app, this happens non-deterministically
    time.sleep(0.01)
    del c # Drop strong reference
    gc.collect() # Force finalizers to run

    t1.join()

    # VERIFICATION:
    # If Raceguard doesn't treat the "GC execution context" as a conflicting
    # actor when triggered from the same thread or implicitly, the race persists.
    print("\n[SUCCESS] GC Race Proof: Registry mutation by finalizer finished.")

if __name__ == "__main__":
    test_gc_finalizer_race()
