"""
EXPLOIT PROOF: Semantic Atomicity Race (Multi-Object Invariant)
===============================================================
A semantic race occurs when an application-level invariant spans
multiple independently-protected objects. Each individual access
is valid, but the *cross-object state* becomes inconsistent because
operations are not atomic across boundaries.

Real-world examples:
  - Bank transfers: debit account A, credit account B. A reader
    between the two steps sees money vanish (or duplicate).
  - Inventory systems: decrement stock, increment shipment count.
    A mid-step read shows a mismatch.

    Thread-1 (transfer):  A.balance -= 10   (sum = 1990)
                          ↕ context switch
    Thread-2 (auditor):   total = A + B     → sees 1990, not 2000!
                          ↕
    Thread-1 (transfer):  B.balance += 10   (sum = 2000 again)

STATUS:
  - Without AtomicGroup: Raceguard does NOT catch this (documented limitation).
  - With AtomicGroup:    Raceguard DETECTS and PREVENTS the semantic race.
"""
import threading
import time
import pytest
from raceguard import (
    protect, configure, clear_warnings,
    RaceConditionError, locked, AtomicGroup,
)


class Account:
    def __init__(self, balance):
        self.balance = balance


@pytest.fixture(autouse=True)
def setup_semantic():
    configure(enabled=True, race_window=0.5, mode="raise", strict=True)
    clear_warnings()
    yield
    configure(enabled=True, race_window=0.010, mode="raise", strict=False)
    clear_warnings()


class TestSemanticRaceLimitation:
    """
    Documents the limitation: independently protected objects
    have no cross-object invariant enforcement.
    """

    def test_ungrouped_invariant_violation_undetected(self):
        """
        Without AtomicGroup, Raceguard sees each access to A and B
        as individually valid. The logical invariant (A + B == 2000)
        can break silently between the two writes.
        """
        acc_a = protect(Account(1000))
        acc_b = protect(Account(1000))

        stop_event = threading.Event()
        invariant_broken = threading.Event()

        def transfer_worker():
            while not stop_event.is_set():
                try:
                    acc_a.balance -= 10
                    time.sleep(0.0001)  # Context switch window
                    acc_b.balance += 10

                    acc_b.balance -= 10
                    time.sleep(0.0001)
                    acc_a.balance += 10
                except RaceConditionError:
                    pass  # Individual races may fire, but not the semantic one

        def auditor_worker():
            while not stop_event.is_set():
                try:
                    total = acc_a.balance + acc_b.balance
                    if total != 2000:
                        invariant_broken.set()
                        stop_event.set()
                        return
                except RaceConditionError:
                    pass

        t1 = threading.Thread(target=transfer_worker)
        t2 = threading.Thread(target=auditor_worker)
        t1.start()
        t2.start()

        time.sleep(1.0)
        stop_event.set()
        t1.join()
        t2.join()

        # This test documents the limitation — it may or may not break
        # depending on scheduling. Either outcome is acceptable.


class TestSemanticRaceDetectedWithAtomicGroup:
    """
    Proves that AtomicGroup catches semantic races across
    multiple objects that share a logical invariant.
    """

    def test_touching_group_member_while_locked_caught(self):
        """
        THE FIX: When objects are grouped with AtomicGroup,
        accessing a member while another thread holds the group
        lock raises a SEMANTIC RaceConditionError.
        """
        acc_a = protect(Account(1000))
        acc_b = protect(Account(1000))
        group = AtomicGroup(acc_a, acc_b)

        errors = []
        barrier = threading.Barrier(2)

        def safe_transfer():
            """Holds the group lock during the full transfer."""
            try:
                barrier.wait()
                with locked(group):
                    acc_a.balance -= 100
                    time.sleep(0.1)  # Hold the lock
                    acc_b.balance += 100
            except RaceConditionError as e:
                errors.append(("transfer", str(e)))

        def unsafe_auditor():
            """Reads a group member WITHOUT holding the group lock."""
            try:
                barrier.wait()
                time.sleep(0.05)  # Wait for transfer to grab the lock
                _ = acc_a.balance  # Should trigger SEMANTIC race
            except RaceConditionError as e:
                errors.append(("auditor", str(e)))

        t1 = threading.Thread(target=safe_transfer)
        t2 = threading.Thread(target=unsafe_auditor)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # PROOF: Raceguard caught the semantic race
        assert len(errors) > 0, (
            "AtomicGroup should have caught the auditor reading "
            "a group member while the group was locked!"
        )
        assert any("SEMANTIC" in msg for _, msg in errors), (
            f"Expected a SEMANTIC race error, got: {errors}"
        )

    def test_safe_transfer_with_sequential_locking(self):
        """
        SOLUTION: The transfer runs atomically under locked(group).
        The auditor reads only AFTER the transfer completes.
        Because both sides use locked(group), the underlying locks
        serialize access and the invariant is always preserved.
        
        This is the correct usage pattern — AtomicGroup ensures you
        CAN'T observe a half-completed transfer.
        """
        acc_a = protect(Account(1000))
        acc_b = protect(Account(1000))
        group = AtomicGroup(acc_a, acc_b)

        observed_totals = []
        transfer_done = threading.Event()

        def safe_transfer():
            with locked(group):
                acc_a.balance -= 250
                time.sleep(0.05)  # Simulate work
                acc_b.balance += 250
            transfer_done.set()

        def safe_auditor():
            transfer_done.wait()  # Wait for transfer to fully complete
            time.sleep(0.6)       # Wait beyond race window
            with locked(group):
                total = acc_a.balance + acc_b.balance
                observed_totals.append(total)

        t1 = threading.Thread(target=safe_transfer)
        t2 = threading.Thread(target=safe_auditor)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # The auditor ran after the transfer completed atomically,
        # so the invariant always holds: 750 + 1250 = 2000
        assert observed_totals == [2000], (
            f"Invariant violated! Observed totals: {observed_totals}"
        )
