"""
Pattern: Loop Variable Capture (UberPLDI'22)
Type: Data Race / Logic Race
Description: A loop variable is captured by reference in a closure (lambda/function) 
that is executed concurrently. All concurrent tasks end up seeing the final value 
of the loop variable instead of the value at their creation time.

While often a logic bug, 'raceguard' catches the un-synchronized access 
to the shared resource indexed by that racing variable.
"""

import threading
import time
import sys
import os

# Ensure we can import raceguard from local src
sys.path.append(os.path.abspath("src"))

from raceguard import protect, configure

configure(mode="warn")

def uber_loop_capture_race():
    # Shared resource being indexed/accessed
    data_buffer = protect([0] * 20)
    
    print("--- Starting Uber Loop Capture Race Pattern ---")

    threads = []
    for i in range(10):
        # RACE: The lambda captures 'i' by reference.
        # By the time the thread runs, 'i' might have progressed.
        # Concurrent threads will access the SAME index in data_buffer.
        def worker():
            # Simulate some delay so the loop finishes
            time.sleep(0.01)
            index = i % len(data_buffer)
            data_buffer[index] += 1
            
        t = threading.Thread(target=worker, name=f"Loop-Worker-{i}")
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"\nBuffer state: {data_buffer}")
    print("--- Race pattern complete ---")

if __name__ == "__main__":
    uber_loop_capture_race()
