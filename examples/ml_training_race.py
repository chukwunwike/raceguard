"""
Production-like Distributed Training System (Integrated with Raceguard)

This script tests raceguard's ability to catch:
- Hidden RMW races (ParameterServer.apply_update)
- Cross-thread safety violations (Metrics.increment)
- Deep nested races (GradientBuffer.push)
- Inconsistent snapshots (Monitor.run)
"""

import threading
import random
import time
import math
import sys
from collections import defaultdict
from raceguard import protect, configure, RaceConditionError

# =========================
# GLOBAL CONFIG
# =========================

NUM_PARAMS = 50
NUM_WORKERS = 10  # Reduced for faster detection in simulation
BATCH_SIZE = 20
EPOCHS = 1

# Configure raceguard
configure(
    enabled=True,
    mode="warn",  # We want to continue and see HOW MANY it finds
    race_window=0.05,
    strict=True
)

# =========================
# SHARED INFRASTRUCTURE
# =========================

class Metrics:
    def __init__(self):
        # PROTECTED
        self.data = protect(defaultdict(int))

    def increment(self, key):
        # RACE: no lock
        self.data[key] += 1

    def get(self, key):
        return self.data[key]


class ParameterServer:
    def __init__(self, size):
        # PROTECTED
        self.weights = protect([0.1] * size)
        self.biases = protect([0.0] * size)

        # misleading lock usage
        self.lock = threading.Lock()

    def read_weight(self, idx):
        return self.weights[idx]

    def write_weight(self, idx, value):
        self.weights[idx] = value

    def apply_update(self, idx, delta):
        """
        Looks safe. It is not.
        Split critical section introduces race.
        """
        with self.lock:
            current = self.read_weight(idx)

        updated = current + delta  # computation outside lock

        with self.lock:
            self.write_weight(idx, updated)

    def apply_bias(self, idx, delta):
        # Completely unsafe
        self.biases[idx] += delta


class GradientBuffer:
    def __init__(self):
        # PROTECTED
        self.buffer = protect(defaultdict(list))

    def push(self, idx, grad):
        # RACE: concurrent writes
        # Deep proxying should catch races on the list items too!
        self.buffer[idx].append(grad)

    def flush(self):
        # RACE: iterate while mutating
        result = {}
        for k, v in self.buffer.items():
            result[k] = sum(v)
        self.buffer.clear()
        return result


# =========================
# MODEL
# =========================

class Model:
    def __init__(self, ps):
        self.ps = ps

    def forward(self, x):
        # simple linear model
        return sum(self.ps.weights[i] * x[i] for i in range(len(x)))

    def loss(self, pred, target):
        return (pred - target) ** 2

    def compute_gradients(self, x, target):
        pred = self.forward(x)
        error = pred - target

        grads_w = [2 * error * xi for xi in x]
        grads_b = [2 * error for _ in x]

        return grads_w, grads_b


# =========================
# WORKER
# =========================

class Worker(threading.Thread):
    def __init__(self, wid, model, buffer, metrics):
        super().__init__(name=f"Worker-{wid}")
        self.wid = wid
        self.model = model
        self.buffer = buffer
        self.metrics = metrics

    def run(self):
        for _ in range(EPOCHS):
            batch = self._generate_batch()

            for x, y in batch:
                grads_w, grads_b = self.model.compute_gradients(x, y)

                # simulate compute delay
                time.sleep(random.uniform(0.0001, 0.001))

                self._accumulate(grads_w, grads_b)

    def _generate_batch(self):
        return [
            ([random.random() for _ in range(NUM_PARAMS)], random.random())
            for _ in range(BATCH_SIZE)
        ]

    def _accumulate(self, grads_w, grads_b):
        for i, g in enumerate(grads_w):
            self.buffer.push(i, g)

        for i, g in enumerate(grads_b):
            # hidden race
            self.model.ps.apply_bias(i, g)

        self.metrics.increment("grads_accumulated")


# =========================
# AGGREGATOR
# =========================

class Aggregator(threading.Thread):
    def __init__(self, ps, buffer, metrics):
        super().__init__(name="Aggregator")
        self.ps = ps
        self.buffer = buffer
        self.metrics = metrics
        self.running = True

    def run(self):
        while self.running:
            updates = self.buffer.flush()

            for idx, grad_sum in updates.items():
                # simulate delay
                time.sleep(random.uniform(0.0001, 0.001))

                self.ps.apply_update(idx, grad_sum * 0.01)

            if not updates:
                time.sleep(0.01)

            self.metrics.increment("updates_applied")

    def stop(self):
        self.running = False


# =========================
# MONITORING
# =========================

class Monitor(threading.Thread):
    def __init__(self, ps, metrics):
        super().__init__(name="Monitor")
        self.ps = ps
        self.metrics = metrics
        self.running = True

    def run(self):
        while self.running:
            # inconsistent snapshot
            try:
                weight_sum = sum(self.ps.weights)
                updates = self.metrics.get("updates_applied")
                
                if math.isnan(weight_sum):
                    print("[!] NaN detected in weights")
            except Exception:
                pass

            time.sleep(0.02)

    def stop(self):
        self.running = False


# =========================
# TRAINING ORCHESTRATION
# =========================

class Trainer:
    def __init__(self):
        self.metrics = Metrics()
        self.ps = ParameterServer(NUM_PARAMS)
        self.buffer = GradientBuffer()
        self.model = Model(self.ps)

        self.workers = [
            Worker(i, self.model, self.buffer, self.metrics)
            for i in range(NUM_WORKERS)
        ]

        self.aggregator = Aggregator(self.ps, self.buffer, self.metrics)
        self.monitor = Monitor(self.ps, self.metrics)

    def train(self):
        print("[*] Starting aggregator and monitor...")
        self.aggregator.start()
        self.monitor.start()

        print(f"[*] Starting {NUM_WORKERS} workers...")
        for w in self.workers:
            w.start()

        for w in self.workers:
            w.join()

        print("[*] Workers finished. Stopping aggregator...")
        self.aggregator.stop()
        self.monitor.stop()

        self.aggregator.join()
        self.monitor.join()

        return self.ps.weights


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print("==========================================")
    print(" RACEGUARD TEST: COMPLEX ML SIMULATOR")
    print("==========================================")

    trainer = Trainer()

    start = time.time()
    try:
        parallel_weights = trainer.train()
        print(f"[*] Parallel training finished in {time.time() - start:.2f}s")
    except Exception as e:
        print(f"[!] Crashed: {e}")

    # Check findings
    import raceguard
    all_warnings = raceguard.warnings
    print("\n==========================================")
    print(f" RACE DETECTION SUMMARY ({len(all_warnings)} events)")
    print("==========================================")

    # Group by object/method to keep it readable
    from collections import Counter
    summary = Counter()
    for w in all_warnings:
        summary[f"{w.object_type}.{w.mode} at {w.current_location[2]}"] += 1

    for event, count in summary.items():
        print(f"[{count:3d}x] {event}")

    if len(all_warnings) > 0:
        print("\n[+] SUCCESS: Raceguard correctly identified concurrency issues!")
    else:
        print("\n[-] FAILURE: No race conditions detected.")
