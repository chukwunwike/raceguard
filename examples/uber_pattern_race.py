"""
Pattern: Concurrent Map Access (UberPLDI'22)
Type: Data Race
Description: Multiple goroutines (threads) concurrently read/write to a shared map (dict) 
without proper synchronization. This leads to unpredictable state or runtime crashes.

In Python, dictionaries are relatively thread-safe for single operations, 
but 'raceguard' catches the logical race of un-synchronized interleaved access 
within the time window.
"""

import threading
import time
import sys
import os

# Ensure we can import raceguard from local src
sys.path.append(os.path.abspath("src"))

from raceguard import protect, configure

# Configure to warn so it doesn't crash the script immediately
configure(mode="warn")

def uber_map_race():
    # The 'Map' being shared
    user_sessions = protect({})
    
    print("--- Starting Uber Map Race Pattern (Concurrent Dict Mutation) ---")

    def login_worker(user_id):
        # Simulate business logic
        # RACE: No lock held during dictionary assignment
        user_sessions[user_id] = {
            "last_login": time.time(),
            "status": "active"
        }

    threads = []
    # Spawn many threads racing to update the same dictionary object
    for i in range(50):
        t = threading.Thread(target=login_worker, args=(f"user_{i}",), name=f"Worker-{i}")
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"\nFinal session count: {len(user_sessions)}")
    print("--- Race pattern complete ---")

if __name__ == "__main__":
    uber_map_race()
