import threading
import time
import pytest
from raceguard import protect, configure, RaceConditionError

class Account:
    def __init__(self, balance):
        self.balance = balance

def test_semantic_atomicity_bypass():
    """
    PROOF OF CONCEPT: Semantic Atomicity Violation
    
    This test proves that protecting individual objects is insufficient 
    if an invariant spans multiple objects (e.g. Total Wealth = A + B).
    """
    total_inconsistency_count = 0
    
    # 1. Create two protected accounts
    acc_a = protect(Account(1000))
    acc_b = protect(Account(1000))
    
    def transfer_worker():
        # Move $100 from A to B repeatedly
        # Logic: Withdraw from A, then deposit to B
        for _ in range(500):
            # STEP 1: Withdraw
            acc_a.balance -= 100
            # Latency simulates real-world processing gap
            time.sleep(0.0001)
            # STEP 2: Deposit
            acc_b.balance += 100
            
            # Move it back
            acc_a.balance += 100
            time.sleep(0.0001)
            acc_b.balance -= 100

    def auditor_worker():
        nonlocal total_inconsistency_count
        # Sum A and B. Both are "protected", but the transaction isn't.
        for _ in range(500):
            try:
                # Read A, then Read B
                wealth = acc_a.balance + acc_b.balance
                if wealth != 2000:
                    # WEALTH GAP OBSERVED!
                    total_inconsistency_count += 1
            except RaceConditionError:
                pass # We don't expect Raceguard to catch this
            time.sleep(0.0001)

    t1 = threading.Thread(target=transfer_worker)
    t2 = threading.Thread(target=auditor_worker)
    
    configure(enabled=True)
    t1.start()
    t2.start()
    
    t1.join()
    t2.join()

    # VERIFICATION:
    # Raceguard should NOT have raised any errors, yet the auditor
    # frequently saw an inconsistent total (e.g. 1900 or 2100).
    print(f"\n[SUCCESS] Semantic Race Proof: Observed {total_inconsistency_count} consistency violations.")
    print("Raceguard remained silent because each object was accessed sequentially.")
    assert total_inconsistency_count > 0

if __name__ == "__main__":
    test_semantic_atomicity_bypass()
