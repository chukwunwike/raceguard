import threading
import time
from raceguard import protect, configure

class Account:
    def __init__(self, balance):
        self.balance = balance

def test_semantic_atomicity_race():
    """
    PROVES: Raceguard doesn't catch races across multiple objects.
    Logic requires A and B to stay in sync, but Raceguard only sees A and B individually.
    """
    configure(strict=True)
    
    # Create two protected accounts
    acc_a = protect(Account(1000))
    acc_b = protect(Account(1000))
    
    # Invariant: Sum should always be 2000
    stop_event = threading.Event()
    race_detected_by_logic = False
    
    def transfer_worker():
        while not stop_event.is_set():
            # Transfer 10 from A to B
            # This is NOT atomic across the two objects
            acc_a.balance -= 10
            time.sleep(0.0001)  # Context switch window
            acc_b.balance += 10
            
            # Transfer 10 from B to A
            acc_b.balance -= 10
            time.sleep(0.0001)
            acc_a.balance += 10

    def auditor_worker():
        nonlocal race_detected_by_logic
        while not stop_event.is_set():
            total = acc_a.balance + acc_b.balance
            if total != 2000:
                race_detected_by_logic = True
                print(f"\n[LOG] Logical Invariant Violated! Total: {total}")
                stop_event.set()

    t1 = threading.Thread(target=transfer_worker)
    t2 = threading.Thread(target=auditor_worker)
    
    t1.start()
    t2.start()
    
    # Wait for work or timeout
    start_time = time.time()
    while time.time() - start_time < 2:
        if stop_event.is_set():
            break
        time.sleep(0.1)
    
    stop_event.set()
    t1.join()
    t2.join()
    
    if race_detected_by_logic:
        print("\n[RESULT] Semantic Race undetected by Raceguard hooks (as expected).")
        print("Reason: Each balance access was valid, but the multi-object state was inconsistent.")
    else:
        print("\n[RESULT] No race detected (failed to trigger logic collision).")

if __name__ == "__main__":
    test_semantic_atomicity_race()
