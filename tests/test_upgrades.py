import pytest
import asyncio
import threading
import time

from raceguard import (
    protect,
    configure,
    clear_warnings,
    RaceConditionError,
    locked,
    with_lock,
    Value,
)

@pytest.fixture(autouse=True)
def reset_config():
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000, strict=False)
    clear_warnings()
    yield
    configure(enabled=True, race_window=0.010, mode="raise", max_warnings=1000, strict=False)

def test_value_wrapper_basic():
    val = protect(Value(0))
    val.set(1)
    assert val.get() == 1
    assert val.value == 1
    # Test str and repr
    assert str(val) == "1"
    assert "Value(1)" in repr(val)

def test_value_wrapper_race():
    val = protect(Value(0))
    errors = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait()
            val.value += 1
        except RaceConditionError as e:
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    configure(race_window=0.5)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors, "Race should have been caught on Value"

def test_strict_mode_temporally_distant():
    """Strict mode should catch races that are further apart in time than race_window."""
    configure(strict=True, race_window=0.001)  # tiny window
    val = protect(Value("init"))
    errors = []

    def writer1():
        val.value = "written1"

    def writer2():
        try:
            val.value = "written2"
        except RaceConditionError as e:
            errors.append(e)

    # Note: Sequential execution from different threads but NO locked() sync.
    # Without strict mode, the 50ms gap would mean NO race detected.
    # With strict mode, any lockless write from a different actor is a race.
    t1 = threading.Thread(target=writer1)
    t1.start(); t1.join()

    time.sleep(0.05)

    t2 = threading.Thread(target=writer2)
    t2.start(); t2.join()

    assert len(errors) == 1
    assert "Race condition detected" in str(errors[0])

def test_asyncio_support():
    """Asyncio support should distinguish between different tasks on the same thread."""
    val = protect(Value(0))
    errors = []
    
    async def worker_1():
        try:
            # write
            val.value = 1
        except RaceConditionError as e:
            errors.append(e)

    async def worker_2():
        try:
            # write, this should race if we yield so they are interleaved within race_window
            val.value = 2
        except RaceConditionError as e:
            errors.append(e)

    async def main():
        # strict mode or high window to ensure it catches
        configure(race_window=0.5)
        # Even though they are on the SAME thread (event loop thread),
        # asyncio.current_task() differs! Thus it's a race.
        await asyncio.gather(worker_1(), worker_2())

    asyncio.run(main())
    
    # worker_2 (or 1 depending on execution order) will flag a race
    assert len(errors) == 1
    assert "Race condition detected" in str(errors[0])
