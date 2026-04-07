import threading
import time
import ctypes
from raceguard import protect, configure

def test_ghost_race_native_bypass():
    """
    PROVES: C-API writes bypass Raceguard visibility.
    Raceguard relies on __setattr__ which isn't called by raw memory writes.
    """
    configure(strict=True)  # Should catch everything if visible
    
    # Create a buffer and protect it
    data = bytearray(b"initial_state")
    protected_data = protect(data)
    
    # Get physical address of the buffer
    address = (ctypes.c_char * len(data)).from_buffer(data)
    
    def ghost_writer():
        # Write directly to memory address bypassing Python hooks
        for i in range(len(data)):
            address[i] = ord('X')
            time.sleep(0.001)

    t1 = threading.Thread(target=ghost_writer)
    t1.start()
    
    # Main thread reads via Raceguard
    try:
        for i in range(100):
            # Reading via proxy
            _ = protected_data[0]
            time.sleep(0.001)
        t1.join()
        
        # If we reach here, Raceguard stayed silent despite concurrent access
        print("\n[RESULT] Ghost Race undetected (as expected).")
        assert bytes(protected_data).startswith(b"XXXX")
        
    except Exception as e:
        print(f"\n[RESULT] Unexpected detection: {e}")
        raise

if __name__ == "__main__":
    test_ghost_race_native_bypass()
