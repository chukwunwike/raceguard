import threading
import time
import random
from raceguard import protect, configure, RaceConditionError, unbind

# Configure raceguard to raise to ensure it handles races actively
configure(mode="raise")

def mega_raceguard_benchmark():
    ITERATIONS = 10_000
    THREAD_COUNTS = [2]
    results = {}
    
    start_total = time.perf_counter()

    def chaos_delay():
        time.sleep(random.uniform(0, 0.00001))

    # Helper function to run the workers and catch races
    def execute_and_detect(target, threads_count):
        threads = [threading.Thread(target=target) for _ in range(threads_count)]
        races_detected = 0
        
        # We wrap the thread start/join to easily count Thread exceptions in pytest or raw script
        for t in threads: t.start()
        for t in threads: t.join()
        
        # We need a way to detect if a race was raised in the threads.
        # To handle this cleanly in a script without overriding threading.excepthook,
        # we will use a shared protected object, but we wrap the worker block.
        # Actually, let's just modify the workers to catch RaceConditionError natively.
        return races_detected

    print("Starting Mega Benchmark...")

    # -----------------------
    # 1. Lost Update / Write-Write
    # -----------------------
    def lost_update():
        state = protect({"counter": 0})
        races = [0] # Raw list for thread-safe native increment
        
        def worker():
            for _ in range(ITERATIONS):
                try:
                    temp = state["counter"]
                    chaos_delay()
                    state["counter"] = temp + 1
                except RaceConditionError:
                    races[0] += 1

        for tcount in THREAD_COUNTS:
            execute_and_detect(worker, tcount)
            expected = tcount * ITERATIONS
            actual = unbind(state)["counter"]
            results[f"lost_update_{tcount}_threads"] = {
                "expected": expected,
                "actual": actual,
                "race_happened": actual != expected,
                "detected": races[0] > 0
            }

    # -----------------------
    # 2. Check-Then-Act / TOCTOU
    # -----------------------
    def check_then_act():
        state = protect({"flag": 0})
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    if state["flag"] == 0:
                        chaos_delay()
                        state["flag"] = 1
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_state = unbind(state)
        results["check_then_act"] = {
            "expected": 1,
            "actual": raw_state["flag"],
            "race_happened": raw_state["flag"] != 1,
            "detected": races[0] > 0
        }

    # -----------------------
    # 3. Multi-step / Atomicity Violation
    # -----------------------
    def atomicity_violation():
        state = protect({"counter": 0})
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    temp = state["counter"]
                    temp += random.randint(1,3)
                    chaos_delay()
                    state["counter"] = temp
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        results["atomicity_violation"] = {
            "expected": "approx",
            "actual": unbind(state)["counter"],
            "race_happened": True,
            "detected": races[0] > 0
        }

    # -----------------------
    # 4. Publication Race 
    # -----------------------
    class Dummy:
        def __init__(self):
            self.value = 0

    def publication_race():
        state = protect({"shared_obj": None})
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    state["shared_obj"] = Dummy()
                    chaos_delay()
                    state["shared_obj"].value = 1
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        results["publication_race"] = {
            "race_happened": True,
            "detected": races[0] > 0
        }

    # -----------------------
    # 5. ABA-style Race
    # -----------------------
    def aba_race():
        state = protect({"aba_var": [0]})
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    temp = state["aba_var"][0]
                    if temp == 0:
                        state["aba_var"][0] = 1
                        chaos_delay()
                        state["aba_var"][0] = 0
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_aba = unbind(state)["aba_var"][0]
        results["aba_race"] = {
            "expected": 0,
            "actual": raw_aba,
            "race_happened": True,
            "detected": races[0] > 0
        }

    # -----------------------
    # 6. Nested Check-Then-Act
    # -----------------------
    class NestedState:
        def __init__(self):
            self.flag_a = 0
            self.flag_b = 0

    def nested_check_then_act():
        state = protect(NestedState())
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    if state.flag_a == 0:
                        chaos_delay()
                        state.flag_a = 1
                    if state.flag_b == 0:
                        chaos_delay()
                        state.flag_b = 1
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_state = unbind(state)
        results["nested_check_then_act"] = {
            "expected": (1,1),
            "actual": (raw_state.flag_a, raw_state.flag_b),
            "race_happened": (raw_state.flag_a, raw_state.flag_b) != (1,1),
            "detected": races[0] > 0
        }

    # -----------------------
    # 7. Multiple Interacting Variables
    # -----------------------
    class MultiVar:
        def __init__(self):
            self.x = 0
            self.y = 0
            self.z = 0

    def multi_var_race():
        state = protect(MultiVar())
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    temp_x = state.x
                    temp_y = state.y
                    chaos_delay()
                    state.x = temp_x + 1
                    state.y = temp_y + 1
                    state.z = state.x + state.y
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_state = unbind(state)
        results["multi_var_race"] = {
            "expected": "approx",
            "actual": (raw_state.x, raw_state.y, raw_state.z),
            "race_happened": True,
            "detected": races[0] > 0
        }

    # -----------------------
    # 8. Nested Object Mutation
    # -----------------------
    class Obj:
        def __init__(self):
            self.inner = {"count": 0}

    def nested_object_mutation():
        state = protect(Obj())
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    temp = state.inner["count"]
                    chaos_delay()
                    state.inner["count"] = temp + 1
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_count = unbind(state).inner["count"]
        results["nested_object_mutation"] = {
            "expected": "THREADS * ITERATIONS",
            "actual": raw_count,
            "race_happened": raw_count != THREAD_COUNTS[0]*ITERATIONS,
            "detected": races[0] > 0
        }

    # -----------------------
    # 9. Cross-Variable Race / Conditional
    # -----------------------
    class CrossVar:
        def __init__(self):
            self.a = 0
            self.b = 0

    def cross_variable_race():
        state = protect(CrossVar())
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    if state.a == state.b:
                        chaos_delay()
                        state.a += 1
                        state.b += 1
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_state = unbind(state)
        results["cross_variable_race"] = {
            "expected": "approx",
            "actual": (raw_state.a, raw_state.b),
            "race_happened": True,
            "detected": races[0] > 0
        }

    # -----------------------
    # 10. Collection Stress
    # -----------------------
    def collection_stress():
        lst = protect([])
        dct = protect({})
        races = [0]
        def worker():
            for i in range(ITERATIONS):
                try:
                    lst.append(i)
                    dct[i] = i
                    chaos_delay()
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        results["collection_stress"] = {
            "list_len": len(unbind(lst)),
            "dict_len": len(unbind(dct)),
            "race_happened": True,
            "detected": races[0] > 0
        }

    # -----------------------
    # 11. No-Race Control
    # -----------------------
    def no_race_control():
        state = protect({"counter": 0})
        lock = threading.Lock()
        races = [0]
        def worker():
            for _ in range(ITERATIONS):
                try:
                    with lock:
                        state["counter"] += 1
                except RaceConditionError:
                    races[0] += 1

        execute_and_detect(worker, THREAD_COUNTS[0])
        raw_count = unbind(state)["counter"]
        results["no_race_control"] = {
            "expected": ITERATIONS * THREAD_COUNTS[0],
            "actual": raw_count,
            "race_happened": raw_count != ITERATIONS * THREAD_COUNTS[0],
            "detected": races[0] > 0
        }

    # Run All
    lost_update()
    check_then_act()
    atomicity_violation()
    publication_race()
    aba_race()
    nested_check_then_act()
    multi_var_race()
    nested_object_mutation()
    cross_variable_race()
    collection_stress()
    no_race_control()

    duration = time.perf_counter() - start_total
    print(f"\nBenchmark completed in {duration:.4f} seconds.")
    return results

if __name__ == "__main__":
    results = mega_raceguard_benchmark()
    
    print("\n" + "="*50)
    print(" MEGA BENCHMARK RESULTS ".center(50))
    print("="*50)
    for name, data in results.items():
        status = "✅ CAUGHT!" if data.get("detected") and data.get("race_happened") else \
                 "💬 CAUGHT (BENIGN)" if data.get("detected") and not data.get("race_happened") else \
                 "✅ SAFE!" if not data.get("race_happened") and not data.get("detected") else \
                 f"❌ MISSED (Raced:{data.get('race_happened')}, Detected:{data.get('detected')} Expected:{data.get('expected')} Actual:{data.get('actual')})"
        print(f"{name:<30} | {status}")
    print("="*50)
