"""
Task Processing System (Integrated with Raceguard)

Tests raceguard's ability to catch:
- Global data structure races (TASK_QUEUE, CACHE)
- Nested stat races (STATS)
- Lazy initialization races (RESOURCE)
- Complex background worker interleaving
"""

import threading
import time
import random
from collections import defaultdict
from raceguard import protect, configure, warnings, clear_warnings

# =========================
# GLOBAL SHARED STATE
# =========================

# Wrap the global data structures
TASK_QUEUE = protect([])
TASK_RESULTS = protect({})
CACHE = protect({})
STATS = protect({
    "tasks_created": 0,
    "tasks_completed": 0,
    "cache_hits": 0,
    "cache_misses": 0,
})
WORKERS = []
SYSTEM_RUNNING = True

LOCK = threading.Lock()

# Configure raceguard
configure(
    enabled=True,
    mode="warn",
    race_window=0.04,
    strict=True
)

# =========================
# TASK MODEL
# =========================

class Task:
    def __init__(self, task_id, payload):
        self.task_id = task_id
        self.payload = payload
        self.result = None
        self.completed = False

    def process(self):
        time.sleep(random.uniform(0.001, 0.005))

        # RACE: shared cache read/write
        if self.payload in CACHE:
            STATS["cache_hits"] += 1
            return CACHE[self.payload]

        STATS["cache_misses"] += 1
        result = self.payload * 2

        # RACE: write to shared cache
        CACHE[self.payload] = result
        return result


# =========================
# TASK CREATION
# =========================

def create_task():
    # RACE: increment without lock
    task_id = STATS["tasks_created"]
    STATS["tasks_created"] += 1

    payload = random.randint(1, 100)
    task = Task(task_id, payload)

    # RACE: append without lock
    TASK_QUEUE.append(task)


def task_producer():
    while SYSTEM_RUNNING:
        create_task()
        time.sleep(random.uniform(0.001, 0.005))


# =========================
# WORKER LOGIC
# =========================

def worker_loop(worker_id):
    while SYSTEM_RUNNING:
        if not TASK_QUEUE:
            time.sleep(0.001)
            continue

        try:
            # RACE: pop without lock
            task = TASK_QUEUE.pop(0)
        except (IndexError, AttributeError):
            continue

        time.sleep(random.uniform(0.0001, 0.001))
        result = task.process()

        # RACE: write to results
        TASK_RESULTS[task.task_id] = result

        # RACE: increment stat
        STATS["tasks_completed"] += 1


# =========================
# CACHE CLEANER
# =========================

def cache_cleaner():
    while SYSTEM_RUNNING:
        if len(CACHE) > 50:
            # RACE: iterate and modify dict
            keys = list(CACHE.keys())
            for key in keys:
                if random.random() < 0.3:
                    try:
                        del CACHE[key]
                    except KeyError:
                        pass
        time.sleep(0.01)


# =========================
# STATS MONITOR
# =========================

def stats_monitor():
    while SYSTEM_RUNNING:
        total = STATS["tasks_created"]
        done = STATS["tasks_completed"]

        if done > total:
            # This should be caught by raceguard's read/write tracking
            pass
        time.sleep(0.01)


# =========================
# LAZY RESOURCE INIT (PROXIED)
# =========================

_RESOURCE_HOLDER = protect({"res": None, "init": False})

def get_resource():
    # We use a protected dict to catch races on the lazy init flags too!
    if not _RESOURCE_HOLDER["init"]:
        time.sleep(random.uniform(0.001, 0.005))
        _RESOURCE_HOLDER["res"] = {"data": random.randint(1, 100)}
        _RESOURCE_HOLDER["init"] = True

    return _RESOURCE_HOLDER["res"]


# =========================
# RESOURCE USERS
# =========================

def resource_user():
    while SYSTEM_RUNNING:
        res = get_resource()
        if res:
            # Note: res here might be raw if not explicitly protected
            # But get_resource returned _RESOURCE_HOLDER["res"], 
            # and our new raceguard AUTOMATICALLY protects nested mutables!
            try:
                res["data"] += 1
            except TypeError:
                pass
        time.sleep(random.uniform(0.001, 0.005))


# =========================
# PARTIAL LOCK MISUSE
# =========================

def partially_safe_update():
    while SYSTEM_RUNNING:
        with LOCK:
            value = STATS["tasks_completed"]

        value += 1
        # RACE: write outside lock
        STATS["tasks_completed"] = value
        time.sleep(0.002)


# =========================
# START SYSTEM
# =========================

def start_system():
    global WORKERS
    
    threads = []
    # producers
    for _ in range(2):
        t = threading.Thread(target=task_producer, name="Producer")
        t.daemon = True
        t.start()
        threads.append(t)

    # workers
    for i in range(4):
        t = threading.Thread(target=worker_loop, args=(i,), name=f"Worker-{i}")
        t.daemon = True
        t.start()
        threads.append(t)

    # background systems
    funcs = [
        cache_cleaner,
        stats_monitor,
        resource_user,
        partially_safe_update,
    ]

    for f in funcs:
        t = threading.Thread(target=f, name=f.__name__)
        t.daemon = True
        t.start()
        threads.append(t)
    
    return threads


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print("==========================================")
    print(" RACEGUARD TEST: TASK PROCESSING SYSTEM")
    print("==========================================")

    clear_warnings()
    all_threads = start_system()

    # let it run
    time.sleep(3)

    SYSTEM_RUNNING = False
    print("[*] Stopping system...")
    
    # Check findings
    import raceguard
    all_events = raceguard.warnings
    print("\n==========================================")
    print(f" RACE DETECTION SUMMARY ({len(all_events)} events)")
    print("==========================================")

    from collections import Counter
    summary = Counter()
    for w in all_events:
        summary[f"{w.object_type}.{w.mode} at {w.current_location[2]}"] += 1

    # Print top 15 unique races
    for event, count in summary.most_common(15):
        print(f"[{count:3d}x] {event}")

    if len(all_events) > 0:
        print("\n[+] SUCCESS: Raceguard captured the data races!")
    else:
        print("\n[-] FAILURE: No race conditions detected.")
