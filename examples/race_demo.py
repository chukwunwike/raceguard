"""
race_demo.py — A computation-heavy program riddled with race conditions.

Run with raceguard to see every race get caught:
    python race_demo.py

Set RACEGUARD_ENABLED=0 to run without detection (observe silent corruption).
"""

import threading
import time
import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from raceguard import protect, configure, RaceConditionError, locked, with_lock

# ── Configure a generous race window for demos ──
configure(race_window=0.5)


# =========================================================================
#  1. SHARED BANK ACCOUNT — Classic read-modify-write race
# =========================================================================

bank_account = protect({"balance": 1000, "transactions": []})

def deposit(amount, name):
    """RACE: reads balance, sleeps, then writes — another thread can interleave."""
    current = bank_account["balance"]        # read
    time.sleep(random.uniform(0.001, 0.01))  # simulate slow computation
    bank_account["balance"] = current + amount  # write (stale value!)
    bank_account["transactions"].append(f"{name}: +{amount}")

def withdraw(amount, name):
    """RACE: same read-modify-write pattern as deposit."""
    current = bank_account["balance"]
    time.sleep(random.uniform(0.001, 0.01))
    if current >= amount:
        bank_account["balance"] = current - amount
        bank_account["transactions"].append(f"{name}: -{amount}")


# =========================================================================
#  2. SHARED COUNTER — The most common race condition
# =========================================================================

counter = protect({"value": 0})

def increment_counter(n):
    """RACE: += is not atomic. Read + add + write can interleave."""
    for _ in range(n):
        counter["value"] = counter["value"] + 1


# =========================================================================
#  3. SHARED TASK QUEUE — Producer/consumer without synchronization
# =========================================================================

task_queue = protect([])
completed_tasks = protect([])

def producer(task_prefix, count):
    """RACE: multiple producers appending to the same list."""
    for i in range(count):
        task_queue.append(f"{task_prefix}-{i}")
        time.sleep(random.uniform(0.001, 0.005))

def consumer(name):
    """RACE: checking length then popping is a TOCTOU race."""
    while True:
        if len(task_queue) > 0:
            try:
                task = task_queue.pop(0)  # RACE with other consumers
                # simulate work
                time.sleep(random.uniform(0.002, 0.008))
                completed_tasks.append(f"{name} did {task}")
            except IndexError:
                pass  # another consumer grabbed it
        else:
            time.sleep(0.01)
            if len(task_queue) == 0:
                break


# =========================================================================
#  4. SHARED STATISTICS ACCUMULATOR — Multiple writers to a dict
# =========================================================================

stats = protect({
    "sum": 0.0,
    "count": 0,
    "min": float("inf"),
    "max": float("-inf"),
    "values": [],
})

def record_measurement(value):
    """RACE: every field update can interleave with another thread."""
    stats["sum"] += value
    stats["count"] += 1
    if value < stats["min"]:
        stats["min"] = value
    if value > stats["max"]:
        stats["max"] = value
    stats["values"].append(value)


# =========================================================================
#  5. SHARED CONFIG — Read/write race on a settings dict
# =========================================================================

config = protect({
    "mode": "normal",
    "threshold": 50,
    "retries": 3,
    "log_enabled": True,
    "history": [],
})

def config_updater():
    """RACE: rapidly changing config while readers depend on consistent state."""
    for i in range(20):
        config["threshold"] = random.randint(10, 100)
        config["mode"] = random.choice(["normal", "aggressive", "passive"])
        config["retries"] = random.randint(1, 10)
        config["history"].append(f"update-{i}")
        time.sleep(random.uniform(0.002, 0.008))

def config_reader(name):
    """RACE: reading config while another thread is mid-update → torn reads."""
    for _ in range(20):
        mode = config["mode"]
        threshold = config["threshold"]
        retries = config["retries"]
        # A consistent snapshot would have all three from the same "version"
        # but without a lock, we might read mode from update N
        # and threshold from update N+1
        time.sleep(random.uniform(0.002, 0.008))


# =========================================================================
#  6. INVENTORY SYSTEM — Check-then-act race
# =========================================================================

inventory = protect({
    "widget_A": 10,
    "widget_B": 5,
    "widget_C": 20,
    "orders": [],
})

def place_order(item, qty, customer):
    """RACE: checks stock then decrements — classic TOCTOU."""
    if inventory[item] >= qty:
        time.sleep(random.uniform(0.001, 0.005))  # simulate latency
        inventory[item] -= qty  # might go negative due to race!
        inventory["orders"].append(f"{customer}: {qty}x {item}")


# =========================================================================
#  7. MATRIX COMPUTATION — Parallel writes to shared result
# =========================================================================

MATRIX_SIZE = 5
matrix_result = protect([[0] * MATRIX_SIZE for _ in range(MATRIX_SIZE)])

def compute_row(row_idx):
    """RACE: multiple threads writing to different rows of the same matrix."""
    for col in range(MATRIX_SIZE):
        # simulate heavy computation
        value = sum(random.randint(1, 10) for _ in range(100))
        time.sleep(random.uniform(0.001, 0.003))
        matrix_result[row_idx][col] = value  # RACE: shared outer list


# =========================================================================
#  8. LEADERBOARD — Sort + insert race
# =========================================================================

leaderboard = protect([])

def submit_score(player, score):
    """RACE: appending then sorting is not atomic."""
    leaderboard.append({"player": player, "score": score})
    time.sleep(random.uniform(0.001, 0.005))
    leaderboard.sort(key=lambda x: x["score"], reverse=True)


# =========================================================================
#  9. FIBONACCI MEMO CACHE — Concurrent cache poisoning
# =========================================================================

fib_cache = protect({})

def fib_cached(n):
    """RACE: check-then-populate cache without locking."""
    if n in fib_cache:
        return fib_cache[n]
    if n <= 1:
        fib_cache[n] = n
        return n
    result = fib_cached(n - 1) + fib_cached(n - 2)
    fib_cache[n] = result
    return result

def fib_worker(n):
    """Multiple threads computing overlapping fibonacci values."""
    fib_cached(n)


# =========================================================================
# 10. LOG BUFFER — Concurrent append + flush race
# =========================================================================

log_buffer = protect([])
flushed_logs = protect([])

def log_writer(prefix, count):
    """RACE: writers appending while flusher is draining."""
    for i in range(count):
        log_buffer.append(f"[{prefix}] entry-{i} @ {time.monotonic():.4f}")
        time.sleep(random.uniform(0.001, 0.005))

def log_flusher():
    """RACE: reads len, iterates, then clears — all separately."""
    for _ in range(5):
        time.sleep(0.02)
        if len(log_buffer) > 0:
            batch = list(log_buffer)      # RACE: list is changing mid-copy
            flushed_logs.extend(batch)
            log_buffer.clear()            # RACE: new entries added between copy and clear


# =========================================================================
#  RUNNER — Execute all the racy scenarios
# =========================================================================

def run_scenario(name, threads_fn):
    """Run a scenario, catch race errors, and report."""
    print(f"\n{'=' * 60}")
    print(f"  SCENARIO: {name}")
    print(f"{'=' * 60}")

    errors = []
    threads = threads_fn(errors)

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    if errors:
        print(f"  [!] {len(errors)} race condition(s) detected!")
        for i, err in enumerate(errors[:2]):  # show first 2 with full details
            print(f"\n     -- Race #{i+1} --")
            print(f"     {str(err).strip()}")
    else:
        print(f"  [OK] No races detected (may need tighter timing)")
    return errors


def wrap_target(fn, args, errors):
    """Wrapper to catch RaceConditionError in threads."""
    def _run():
        try:
            fn(*args)
        except RaceConditionError as e:
            errors.append(e)
        except Exception as e:
            errors.append(e)
    return _run


def main():
    print("=" * 60)
    print("  RACEGUARD DEMO - 10 Race Condition Scenarios")
    print("  Each scenario has intentional threading bugs.")
    print("=" * 60)

    all_errors = []

    # 1. Bank Account
    errs = run_scenario("Bank Account (read-modify-write)", lambda errors: [
        threading.Thread(target=wrap_target(deposit, (100, "Alice"), errors), name="Depositor-Alice"),
        threading.Thread(target=wrap_target(deposit, (200, "Bob"), errors), name="Depositor-Bob"),
        threading.Thread(target=wrap_target(withdraw, (150, "Charlie"), errors), name="Withdrawer-Charlie"),
        threading.Thread(target=wrap_target(withdraw, (50, "Diana"), errors), name="Withdrawer-Diana"),
    ])
    all_errors.extend(errs)

    # 2. Counter
    errs = run_scenario("Shared Counter (increment race)", lambda errors: [
        threading.Thread(target=wrap_target(increment_counter, (50,), errors), name=f"Counter-{i}")
        for i in range(4)
    ])
    all_errors.extend(errs)

    # 3. Task Queue
    errs = run_scenario("Task Queue (producer/consumer TOCTOU)", lambda errors: [
        threading.Thread(target=wrap_target(producer, ("batch-A", 10), errors), name="Producer-A"),
        threading.Thread(target=wrap_target(producer, ("batch-B", 10), errors), name="Producer-B"),
        threading.Thread(target=wrap_target(consumer, ("Worker-1",), errors), name="Consumer-1"),
        threading.Thread(target=wrap_target(consumer, ("Worker-2",), errors), name="Consumer-2"),
    ])
    all_errors.extend(errs)

    # 4. Statistics
    errs = run_scenario("Statistics Accumulator (multi-field update)", lambda errors: [
        threading.Thread(target=wrap_target(record_measurement, (random.uniform(0, 100),), errors), name=f"Sensor-{i}")
        for i in range(6)
    ])
    all_errors.extend(errs)

    # 5. Config
    errs = run_scenario("Shared Config (torn reads)", lambda errors: [
        threading.Thread(target=wrap_target(config_updater, (), errors), name="ConfigWriter"),
        threading.Thread(target=wrap_target(config_reader, ("ReaderA",), errors), name="ConfigReader-A"),
        threading.Thread(target=wrap_target(config_reader, ("ReaderB",), errors), name="ConfigReader-B"),
    ])
    all_errors.extend(errs)

    # 6. Inventory
    errs = run_scenario("Inventory System (check-then-act)", lambda errors: [
        threading.Thread(target=wrap_target(place_order, ("widget_A", 3, f"Customer-{i}"), errors), name=f"Order-{i}")
        for i in range(5)
    ])
    all_errors.extend(errs)

    # 7. Matrix
    errs = run_scenario("Matrix Computation (parallel row writes)", lambda errors: [
        threading.Thread(target=wrap_target(compute_row, (i,), errors), name=f"RowWorker-{i}")
        for i in range(MATRIX_SIZE)
    ])
    all_errors.extend(errs)

    # 8. Leaderboard
    errs = run_scenario("Leaderboard (append + sort race)", lambda errors: [
        threading.Thread(target=wrap_target(submit_score, (f"Player-{i}", random.randint(100, 9999)), errors), name=f"Scorer-{i}")
        for i in range(6)
    ])
    all_errors.extend(errs)

    # 9. Fibonacci Cache
    errs = run_scenario("Fibonacci Cache (concurrent cache poisoning)", lambda errors: [
        threading.Thread(target=wrap_target(fib_worker, (random.randint(10, 25),), errors), name=f"FibWorker-{i}")
        for i in range(4)
    ])
    all_errors.extend(errs)

    # 10. Log Buffer
    errs = run_scenario("Log Buffer (write + flush race)", lambda errors: [
        threading.Thread(target=wrap_target(log_writer, ("APP", 15), errors), name="LogWriter-APP"),
        threading.Thread(target=wrap_target(log_writer, ("DB", 15), errors), name="LogWriter-DB"),
        threading.Thread(target=wrap_target(log_flusher, (), errors), name="LogFlusher"),
    ])
    all_errors.extend(errs)

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  TOTAL: {len(all_errors)} race conditions caught across 10 scenarios")
    print(f"{'=' * 60}")

    if all_errors:
        print("\n  raceguard caught real threading bugs that would cause")
        print("  silent data corruption in production. Fix them with:")
        print("    * with locked(obj):  -- context manager")
        print("    * @with_lock(obj)    -- decorator")
        print()
    else:
        print("\n  No races caught — try increasing race_window or adding more threads.")


if __name__ == "__main__":
    main()
