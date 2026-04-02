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

class TestBasics:

    def test_protect_list(self):
        obj = protect([1, 2, 3])
        assert obj == [1, 2, 3]
        assert len(obj) == 3

    def test_protect_dict(self):
        obj = protect({"a": 1})
        assert obj == {"a": 1}
        assert obj["a"] == 1

    def test_protect_set(self):
        obj = protect({1, 2, 3})
        assert 2 in obj
        assert len(obj) == 3

    def test_protect_bytearray(self):
        obj = protect(bytearray(b"hello"))
        assert len(obj) == 5

    def test_protect_custom_object(self):
        class Bag:
            def __init__(self):
                self.items = []
        bag = Bag()
        obj = protect(bag)
        obj.items.append("x")
        assert bag.items == ["x"]

    def test_primitives_raise(self):
        for prim in [5, 3.14, "hello", (1, 2), True, b"bytes", frozenset({1})]:
            with pytest.raises(ValueError, match="immutable"):
                protect(prim)

    def test_double_protect_returns_same(self):
        lst = [1, 2]
        p1 = protect(lst)
        p2 = protect(p1)
        assert p1 is p2

    def test_disabled_returns_raw(self):
        configure(enabled=False)
        lst = [1, 2]
        result = protect(lst)
        assert result is lst
        assert type(result) is list

    def test_get_config(self):
        configure(race_window=0.05, mode="warn")
        cfg = get_config()
        assert cfg["race_window"] == 0.05
        assert cfg["mode"] == "warn"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            configure(mode="explode")


# ---------------------------------------------------------------------------
# 2. Single-thread (no races)
# ---------------------------------------------------------------------------

class TestSingleThread:

    def test_sequential_list_ops(self):
        shared = protect([])
        for i in range(100):
            shared.append(i)
        assert len(shared) == 100

    def test_sequential_dict_ops(self):
        shared = protect({})
        for i in range(100):
            shared[f"key_{i}"] = i
        assert len(shared) == 100
        assert shared["key_50"] == 50

    def test_sequential_set_ops(self):
        shared = protect(set())
        for i in range(50):
            shared.add(i)
        assert len(shared) == 50

    def test_iadd(self):
        shared = protect([1, 2])
        shared += [3, 4]
        assert shared == [1, 2, 3, 4]

    def test_imul(self):
        shared = protect([1])
        shared *= 3
        assert shared == [1, 1, 1]


# ---------------------------------------------------------------------------
# 3. Race detection (raise mode)
# ---------------------------------------------------------------------------

class TestRaceDetection:

    def test_two_writers_race(self):
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

    def test_reader_writer_race(self):
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

    def test_concurrent_reads_safe(self):
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

    def test_error_message_has_location(self):
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

class TestWarnMode:

    def test_warn_mode_no_raise(self):
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

    def test_clear_warnings_returns_and_clears(self):
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

    def test_max_warnings_cap(self):
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

class TestLogMode:

    def test_log_mode_no_raise_no_collect(self):
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

class TestSynchronization:

    def test_locked_context_manager(self):
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

    def test_with_lock_decorator(self):
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

    def test_locked_multi_proxy(self):
        """locked() supports multiple proxies, acquiring in consistent order."""
        configure(race_window=0.5)
        a = protect([])
        b = protect({})

        with locked(a, b):
            a.append(1)
            b["x"] = 1

        assert a == [1]
        assert b == {"x": 1}

    def test_previous_locked_access_safe(self):
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

class TestDunders:

    def test_str_repr(self):
        obj = protect([1, 2, 3])
        assert "[1, 2, 3]" in str(obj)
        assert "Protected list" in repr(obj)

    def test_format(self):
        obj = protect([1, 2])
        result = f"{obj}"
        assert "1" in result

    def test_contains(self):
        obj = protect([10, 20, 30])
        assert 20 in obj
        assert 99 not in obj

    def test_iter(self):
        obj = protect([1, 2, 3])
        assert list(obj) == [1, 2, 3]

    def test_reversed(self):
        obj = protect([1, 2, 3])
        assert list(reversed(obj)) == [3, 2, 1]

    def test_bool(self):
        assert bool(protect([1])) is True
        assert bool(protect([])) is False

    def test_getitem_setitem_delitem(self):
        obj = protect({"a": 1, "b": 2})
        assert obj["a"] == 1
        obj["c"] = 3
        assert obj["c"] == 3
        del obj["a"]
        assert "a" not in obj

    def test_eq_ne(self):
        a = protect([1, 2])
        b = protect([1, 2])
        c = protect([3, 4])
        assert a == b
        assert a != c
        assert a == [1, 2]  # compare with raw

    def test_lt_le_gt_ge(self):
        a = protect([1])
        b = protect([2])
        assert a < b
        assert a <= b
        assert b > a
        assert b >= a
        assert a <= [1]
        assert a >= [1]

    def test_add(self):
        a = protect([1, 2])
        result = a + [3, 4]
        assert result == [1, 2, 3, 4]

    def test_mul(self):
        a = protect([0])
        result = a * 3
        assert result == [0, 0, 0]

    def test_rmul(self):
        a = protect([0])
        result = 3 * a
        assert result == [0, 0, 0]

    def test_hash_for_hashable(self):
        class Hashable:
            def __hash__(self):
                return 42
        obj = protect(Hashable())
        assert hash(obj) == 42

    def test_isinstance_emulation(self):
        obj = protect([1, 2])
        assert isinstance(obj, list)

    def test_ior_for_sets(self):
        s = protect({1, 2})
        s |= {3, 4}
        assert s == {1, 2, 3, 4}

    def test_iand_for_sets(self):
        s = protect({1, 2, 3})
        s &= {2, 3, 4}
        assert s == {2, 3}


# ---------------------------------------------------------------------------
# 8. Lock property
# ---------------------------------------------------------------------------

class TestLockProperty:

    def test_lock_is_threading_lock(self):
        obj = protect([])
        lk = obj.lock
        assert hasattr(lk, "acquire")
        assert hasattr(lk, "release")
        assert callable(lk.acquire)

    def test_shared_lock(self):
        shared_lock = threading.Lock()
        a = protect([], lock=shared_lock)
        b = protect({}, lock=shared_lock)
        assert a.lock is b.lock
        assert a.lock is shared_lock
