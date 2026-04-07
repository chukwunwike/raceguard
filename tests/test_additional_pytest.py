import pytest
import threading
import time

from raceguard import protect, configure, clear_warnings, RaceConditionError, locked

# Setup and teardown for clean configurations
@pytest.fixture(autouse=True)
def reset_config():
    configure(enabled=True, race_window=0.05, mode="raise", max_warnings=1000)
    clear_warnings()
    yield
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000)
    clear_warnings()

class TestAdditionalEdges:

    def test_exception_in_locked_block_releases_lock(self):
        """Verifies that an exception raised inside `with locked(shared):` releases the lock."""
        shared = protect([])
        class IntentionalError(Exception):
            pass

        try:
            with locked(shared):
                shared.append("inside")
                raise IntentionalError("Boom")
        except IntentionalError:
            pass

        # If the lock wasn't released, this will deadlock
        shared.append("outside")
        assert "inside" in shared
        assert "outside" in shared
        assert len(shared) == 2

    def test_protected_dict_pop_race(self):
        """Ensures that dictionary pop() triggers a RaceConditionError when executing concurrently."""
        configure(race_window=0.5)
        shared = protect({"key": 42})
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                # `pop` is a mutating method on dict
                shared.pop("key", None)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # At least one of the threads should hit a RaceConditionError
        time.sleep(0.6) # wait for race window
        assert set(shared.keys()) == set()
        assert len(errors) > 0

    def test_protected_set_difference_update_race(self):
        """Ensures that difference_update() on a protected set triggers a RaceConditionError."""
        configure(race_window=0.5)
        shared = protect({1, 2, 3})
        errors = []
        barrier = threading.Barrier(2)

        def worker(val):
            try:
                barrier.wait()
                shared.difference_update({val})
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) > 0

    def test_multithreaded_bytearray_race(self):
        """Ensures that mutating a bytearray concurrently triggers a race."""
        configure(race_window=0.5)
        shared = protect(bytearray(b"init"))
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                shared.extend(b"_add")
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) > 0

    def test_invalid_attribute_access(self):
        """Ensures that reading an invalid attribute from a proxy triggers an AttributeError."""
        shared = protect([1, 2, 3])
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = shared.invalid_method
