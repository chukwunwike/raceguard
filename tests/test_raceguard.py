"""Comprehensive test suite for raceguard.

Covers all public APIs, edge cases, modes, dunders, and threading scenarios.
"""

import pytest
import time
import threading
import logging

from raceguard import (
    protect,
    configure,
    get_config,
    clear_warnings,
    RaceConditionError,
    RaceConditionWarning,
    locked,
    with_lock,
    warnings,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_config():
    """Ensure every test starts with a clean, default configuration."""
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000)
    clear_warnings()
    yield
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000)
    clear_warnings()


# ---------------------------------------------------------------------------
# 1. Basics & Configuration
# ---------------------------------------------------------------------------

class TestProtectingObjects:

    def test_protecting_a_list_wraps_it_in_a_proxy(self):
        obj = protect([1, 2, 3])
        assert obj == [1, 2, 3]
        assert len(obj) == 3

    def test_protecting_a_dict_wraps_it_in_a_proxy(self):
        obj = protect({"a": 1})
        assert obj == {"a": 1}
        assert obj["a"] == 1

    def test_protecting_a_set_wraps_it_in_a_proxy(self):
        obj = protect({1, 2, 3})
        assert 2 in obj
        assert len(obj) == 3

    def test_protecting_a_bytearray_wraps_it_in_a_proxy(self):
        obj = protect(bytearray(b"hello"))
        assert len(obj) == 5

    def test_protecting_a_custom_object_wraps_it_in_a_proxy(self):
        class Bag:
            def __init__(self):
                self.items = []
        bag = Bag()
        obj = protect(bag)
        obj.items.append("x")
        assert bag.items == ["x"]

    def test_protecting_immutable_primitives_raises_error(self):
        for prim in [5, 3.14, "hello", (1, 2), True, b"bytes", frozenset({1})]:
            with pytest.raises(ValueError, match="immutable"):
                protect(prim)

    def test_protecting_same_object_twice_returns_same_proxy(self):
        lst = [1, 2]
        p1 = protect(lst)
        p2 = protect(p1)
        assert p1 is p2

    def test_disabled_mode_returns_raw_object_without_wrapping(self):
        configure(enabled=False)
        lst = [1, 2]
        result = protect(lst)
        assert result is lst
        assert type(result) is list

    def test_get_config_returns_current_settings(self):
        configure(race_window=0.05, mode="warn")
        cfg = get_config()
        assert cfg["race_window"] == 0.05
        assert cfg["mode"] == "warn"

    def test_invalid_detection_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            configure(mode="explode")


# ---------------------------------------------------------------------------
# 2. Single-thread (no races)
# ---------------------------------------------------------------------------

class TestSingleThreadSafety:

    def test_list_operations_in_one_thread_never_race(self):
        shared = protect([])
        for i in range(100):
            shared.append(i)
        assert len(shared) == 100

    def test_dict_operations_in_one_thread_never_race(self):
        shared = protect({})
        for i in range(100):
            shared[f"key_{i}"] = i
        assert len(shared) == 100
        assert shared["key_50"] == 50

    def test_set_operations_in_one_thread_never_race(self):
        shared = protect(set())
        for i in range(50):
            shared.add(i)
        assert len(shared) == 50

    def test_inplace_add_in_one_thread_never_races(self):
        shared = protect([1, 2])
        shared += [3, 4]
        assert shared == [1, 2, 3, 4]

    def test_inplace_multiply_in_one_thread_never_races(self):
        shared = protect([1])
        shared *= 3
        assert shared == [1, 1, 1]


# ---------------------------------------------------------------------------
# 3. Race detection (raise mode)
# ---------------------------------------------------------------------------

class TestConcurrentRaceDetection:

    def test_two_threads_writing_simultaneously_raises_race(self):
        """Two threads writing simultaneously without locks -> race."""
        configure(race_window=0.5)
        shared = protect([])
        errors = []
        barrier = threading.Barrier(2)

        def writer(val):
            try:
                barrier.wait()
                shared.append(val)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,), name="W-1")
        t2 = threading.Thread(target=writer, args=(2,), name="W-2")
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) > 0
        assert all(isinstance(e, RaceConditionError) for e in errors)

    def test_reader_and_writer_simultaneously_raises_race(self):
        """A reader and writer accessing simultaneously -> race."""
        configure(race_window=0.5)
        shared = protect({"val": 0})
        errors = []
        barrier = threading.Barrier(2)

        def reader():
            try:
                barrier.wait()
                _ = shared["val"]
            except RaceConditionError as e:
                errors.append(e)

        def writer():
            try:
                barrier.wait()
                shared["val"] = 1
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=reader, name="Reader")
        t2 = threading.Thread(target=writer, name="Writer")
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) > 0

    def test_two_threads_reading_simultaneously_is_safe(self):
        """Two threads reading simultaneously -> no race (reads are safe)."""
        configure(race_window=0.5)
        shared = protect({"val": 42})
        errors = []
        barrier = threading.Barrier(2)

        def reader():
            try:
                barrier.wait()
                _ = shared["val"]
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=reader, name="R-1")
        t2 = threading.Thread(target=reader, name="R-2")
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) == 0

    def test_error_message_includes_file_path_and_line(self):
        """Error message must include file path and line number."""
        configure(race_window=0.5)
        shared = protect([])
        errors = []
        barrier = threading.Barrier(2)

        def writer(val):
            try:
                barrier.wait()
                shared.append(val)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,), name="Loc-1")
        t2 = threading.Thread(target=writer, args=(2,), name="Loc-2")
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) > 0
        msg = str(errors[0])
        assert "Location" in msg
        assert "test_raceguard.py" in msg


# ---------------------------------------------------------------------------
# 4. Warn mode
# ---------------------------------------------------------------------------

class TestWarnModeDetection:

    def test_warn_mode_collects_races_without_raising(self):
        """In warn mode, races are collected but NOT raised."""
        configure(race_window=0.5, mode="warn")
        shared = protect([])
        barrier = threading.Barrier(2)
        errors = []

        def writer(val):
            try:
                barrier.wait()
                shared.append(val)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,), name="W-1")
        t2 = threading.Thread(target=writer, args=(2,), name="W-2")
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Should NOT have raised
        assert len(errors) == 0
        # Should have collected warnings
        w = clear_warnings()
        assert len(w) > 0
        assert all(isinstance(x, RaceConditionWarning) for x in w)

    def test_clear_warnings_returns_all_and_empties_list(self):
        """clear_warnings() should return all and leave the list empty."""
        configure(race_window=0.5, mode="warn")
        shared = protect([])
        barrier = threading.Barrier(2)

        def writer(val):
            barrier.wait()
            shared.append(val)

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        batch1 = clear_warnings()
        batch2 = clear_warnings()
        assert len(batch1) > 0
        assert len(batch2) == 0

    def test_warning_count_never_exceeds_configured_maximum(self):
        """Warnings should not exceed max_warnings."""
        configure(race_window=0.5, mode="warn", max_warnings=2)
        shared = protect({"n": 0})
        barrier = threading.Barrier(2)

        def hammer():
            barrier.wait()
            for _ in range(10):
                shared["n"] += 1

        t1 = threading.Thread(target=hammer)
        t2 = threading.Thread(target=hammer)
        t1.start(); t2.start()
        t1.join(); t2.join()

        w = clear_warnings()
        assert len(w) <= 2


# ---------------------------------------------------------------------------
# 5. Log mode
# ---------------------------------------------------------------------------

class TestLogModeDetection:

    def test_log_mode_logs_races_without_raising_or_collecting(self):
        """In log mode, races are logged but NOT raised or collected."""
        configure(race_window=0.5, mode="log")
        shared = protect([])
        barrier = threading.Barrier(2)
        errors = []

        def writer(val):
            try:
                barrier.wait()
                shared.append(val)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,), name="L-1")
        t2 = threading.Thread(target=writer, args=(2,), name="L-2")
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) == 0
        assert len(clear_warnings()) == 0


# ---------------------------------------------------------------------------
# 6. Synchronization helpers
# ---------------------------------------------------------------------------

class TestLockSynchronization:

    def test_locked_context_manager_prevents_race(self):
        """Using locked() prevents race conditions."""
        configure(race_window=0.5)
        shared = protect([])
        errors = []
        barrier = threading.Barrier(2)

        def writer(val):
            try:
                barrier.wait()
                with locked(shared):
                    shared.append(val)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) == 0
        assert sorted(shared) == [1, 2]

    def test_with_lock_decorator_prevents_race(self):
        """Using @with_lock prevents race conditions."""
        configure(race_window=0.5)
        shared = protect([])
        errors = []

        @with_lock(shared)
        def safe_append(val):
            shared.append(val)

        barrier = threading.Barrier(2)

        def worker(val):
            try:
                barrier.wait()
                safe_append(val)
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(errors) == 0
        assert sorted(shared) == [1, 2]

    def test_locked_acquires_multiple_proxies_in_consistent_order(self):
        """locked() supports multiple proxies, acquiring in consistent order."""
        configure(race_window=0.5)
        a = protect([])
        b = protect({})

        with locked(a, b):
            a.append(1)
            b["x"] = 1

        assert a == [1]
        assert b == {"x": 1}

    def test_access_after_locked_section_is_considered_safe(self):
        """If previous access was locked, next unlocked access is safe."""
        configure(race_window=0.5)
        shared = protect([])

        def writer():
            with locked(shared):
                shared.append("done")

        def reader():
            time.sleep(0.05)
            assert "done" in shared

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start(); t2.start()
        t1.join(); t2.join()


# ---------------------------------------------------------------------------
# 7. Dunder methods
# ---------------------------------------------------------------------------

class TestDunderMethodProxying:

    def test_str_and_repr_delegate_to_wrapped_object(self):
        obj = protect([1, 2, 3])
        assert "[1, 2, 3]" in str(obj)
        assert "Protected list" in repr(obj)

    def test_format_delegates_to_wrapped_object(self):
        obj = protect([1, 2])
        result = f"{obj}"
        assert "1" in result

    def test_in_operator_checks_wrapped_container(self):
        obj = protect([10, 20, 30])
        assert 20 in obj
        assert 99 not in obj

    def test_iteration_yields_wrapped_container_items(self):
        obj = protect([1, 2, 3])
        assert list(obj) == [1, 2, 3]

    def test_reversed_iterates_wrapped_container_backwards(self):
        obj = protect([1, 2, 3])
        assert list(reversed(obj)) == [3, 2, 1]

    def test_bool_reflects_wrapped_container_truthiness(self):
        assert bool(protect([1])) is True
        assert bool(protect([])) is False

    def test_indexing_get_set_delete_delegates_to_wrapped(self):
        obj = protect({"a": 1, "b": 2})
        assert obj["a"] == 1
        obj["c"] = 3
        assert obj["c"] == 3
        del obj["a"]
        assert "a" not in obj

    def test_equality_and_inequality_compare_wrapped_values(self):
        a = protect([1, 2])
        b = protect([1, 2])
        c = protect([3, 4])
        assert a == b
        assert a != c
        assert a == [1, 2]  # compare with raw

    def test_ordering_comparisons_delegate_to_wrapped_values(self):
        a = protect([1])
        b = protect([2])
        assert a < b
        assert a <= b
        assert b > a
        assert b >= a
        assert a <= [1]
        assert a >= [1]

    def test_addition_returns_new_list_from_wrapped(self):
        a = protect([1, 2])
        result = a + [3, 4]
        assert result == [1, 2, 3, 4]

    def test_multiplication_repeats_wrapped_list(self):
        a = protect([0])
        result = a * 3
        assert result == [0, 0, 0]

    def test_right_multiply_repeats_wrapped_list(self):
        a = protect([0])
        result = 3 * a
        assert result == [0, 0, 0]

    def test_hash_works_for_hashable_wrapped_objects(self):
        class Hashable:
            def __hash__(self):
                return 42
        obj = protect(Hashable())
        assert hash(obj) == 42

    def test_isinstance_checks_wrapped_object_type(self):
        obj = protect([1, 2])
        assert isinstance(obj, list)

    def test_inplace_or_updates_wrapped_set(self):
        s = protect({1, 2})
        s |= {3, 4}
        assert s == {1, 2, 3, 4}

    def test_inplace_and_intersects_wrapped_set(self):
        s = protect({1, 2, 3})
        s &= {2, 3, 4}
        assert s == {2, 3}


# ---------------------------------------------------------------------------
# 8. Lock property
# ---------------------------------------------------------------------------

class TestInternalLockAccess:

    def test_proxy_lock_is_a_threading_lock_instance(self):
        obj = protect([])
        lk = obj.lock
        assert hasattr(lk, "acquire")
        assert hasattr(lk, "release")
        assert callable(lk.acquire)

    def test_two_proxies_can_share_the_same_lock(self):
        shared_lock = threading.Lock()
        a = protect([], lock=shared_lock)
        b = protect({}, lock=shared_lock)
        assert a.lock is b.lock
        assert a.lock is shared_lock


# ---------------------------------------------------------------------------
# 9. Context Manager of protected object
# ---------------------------------------------------------------------------

class TestContextManagerProtocol:
    def test_with_statement_acquires_proxy_lock_automatically(self):
        class MyCtx:
            def __init__(self):
                self.val = 0
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        shared = protect(MyCtx())
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                with shared:
                    shared.val += 1
            except RaceConditionError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Because `with shared:` acquires the proxy's lock, it should prevent race conditions
        assert len(errors) == 0
        assert shared.val == 2
