"""
Race Benchmark Suite (Integrated with Raceguard)

Goals:
- Validate race detection coverage across basic patterns
- Measure drift and detection consistency
"""

import threading
import multiprocessing
import time
import random
import statistics
from raceguard import protect, configure, warnings, clear_warnings

# Configure raceguard
configure(
    enabled=True,
    mode="warn",
    race_window=0.05,
    strict=False  # Keep it window-based for benchmarks to simulate real loose timing
)

# =========================
# UTILITIES
# =========================

def measure_drift(a, b):
    if isinstance(a, list):
        return sum(abs(x - y) for x, y in zip(a, b))
    return abs(a - b)


def run_multiple(fn, runs=3):  # Reduced runs for efficiency
    results = []
    for _ in range(runs):
        results.append(fn())
    return results


# =========================
# SCENARIO 1: COUNTER RACE
# =========================

def counter_race():
    # PROTECTED
    counter = protect([0])

    def worker():
        for _ in range(1000):
            counter[0] += 1

    threads = [threading.Thread(target=worker, name=f"C-Worker-{i}") for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    return counter[0]


def counter_safe():
    counter = [0]
    lock = threading.Lock()

    def worker():
        for _ in range(1000):
            with lock:
                counter[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    return counter[0]


# =========================
# SCENARIO 2: CACHE RACE
# =========================

def cache_race():
    # PROTECTED
    cache = protect({})

    def compute(x):
        if x in cache:
            return cache[x]

        time.sleep(0.0001)
        result = x * x
        cache[x] = result
        return result

    def worker():
        for _ in range(200):
            compute(random.randint(1, 50))

    threads = [threading.Thread(target=worker, name=f"D-Worker-{i}") for i in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()

    return len(cache)


def cache_safe():
    cache = {}
    lock = threading.Lock()

    def compute(x):
        with lock:
            if x in cache:
                return cache[x]

        time.sleep(0.0001)
        result = x * x

        with lock:
            cache[x] = result
        return result

    def worker():
        for _ in range(200):
            compute(random.randint(1, 50))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()

    return len(cache)


# =========================
# SCENARIO 3: ML DRIFT
# =========================

def ml_race():
    # PROTECTED
    weights = protect([0.1] * 10)

    def worker():
        for _ in range(100):
            for i in range(len(weights)):
                weights[i] += random.uniform(-0.01, 0.01)

    threads = [threading.Thread(target=worker, name=f"M-Worker-{i}") for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    return weights


def ml_safe():
    weights = [0.1] * 10
    lock = threading.Lock()

    def worker():
        for _ in range(100):
            for i in range(len(weights)):
                with lock:
                    weights[i] += random.uniform(-0.01, 0.01)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    return weights


# =========================
# BENCHMARK RUNNER
# =========================

SCENARIOS = [
    ("Counter Race", counter_race, counter_safe, 5000),
    ("Cache Race", cache_race, cache_safe, None),
    ("ML Drift", ml_race, ml_safe, None),
]

def run_scenario(name, race_fn, safe_fn, expected=None):
    print(f"\n=== {name} ===")
    clear_warnings()

    race_results = run_multiple(race_fn)
    safe_results = run_multiple(safe_fn)

    race_warn_count = len(warnings)

    print("Race results:", race_results)
    print("Safe results:", safe_results)

    if expected is not None:
        drift = [abs(r - expected) for r in race_results]
        print("Drift from expected:", drift)
    else:
        drift = [
            measure_drift(race_results[i], safe_results[i])
            for i in range(len(race_results))
        ]
        print("Drift vs safe:", drift)

    print(f"[*] Detection events: {race_warn_count}")

def run_all():
    print("===================================")
    print(" RACE BENCHMARK SUITE")
    print("===================================")

    for scenario in SCENARIOS:
        run_scenario(*scenario)

    all_warnings = warnings
    print("\n=== FINAL RACEGUARD REPORT ===")
    print(f"Total cumulative warnings: {len(all_warnings)}")

    if len(all_warnings) > 0:
        from collections import Counter
        summary = Counter()
        for w in all_warnings:
            summary[f"{w.object_type}.{w.mode} at {w.current_location[2]}"] += 1
        
        for event, count in summary.most_common(10):
            print(f"[{count:4d}x] {event}")


if __name__ == "__main__":
    run_all()
