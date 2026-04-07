import threading
import time
import ctypes
import pytest
from raceguard import protect, configure

def test_ghost_write_bypass():
    """
    PROOOF OF CONCEPT: Native Memory Bypass (Ghost Write)
    
    This test proves that Raceguard cannot detect data races if memory
    is modified via raw pointers (ctypes) rather than Python attribute access.
    """
    # 1. Create a protected buffer
    data = bytearray(b"initial_state")
    protected_data = protect(data)
    
    # 2. Extract raw memory address using ctypes
    # This simulates what a C-extension (like numpy or a socket) might do
    address = (ctypes.c_char * len(data)).from_buffer(data)
    
    def native_worker():
        # Modify memory directly at the address bypasses Python's __setitem__
        for _ in range(100):
            for i in range(len(data)):
                address[i] = ord('x')
            time.sleep(0.0001)

    def python_reader():
        # Normal Python access to the protected proxy
        for _ in range(100):
            _ = protected_data[0]
            time.sleep(0.0001)

    # Launch threads
    t1 = threading.Thread(target=native_worker)
    t2 = threading.Thread(target=python_reader)
    
    configure(enabled=True)
    t1.start()
    t2.start()
    
    t1.join()
    t2.join()

    # VERIFICATION:
    # We expect Raceguard to remain silent (no RaceConditionError) 
    # even though t1 was writing to the same memory t2 was reading.
    # This is a "Ghost Race".
    assert data == b"xxxxxxxxxxxxx"
    print("\n[SUCCESS] Ghost Race Proof: Native buffer modification was invisible to Raceguard.")

if __name__ == "__main__":
    test_ghost_write_bypass()
