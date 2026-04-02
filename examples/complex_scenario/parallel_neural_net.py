"""
Parallel Neural Network Training Simulation

Why is this extremely complicated to find without Raceguard?
When parallelizing training, a common approach is to compute local gradients
across threads and apply them to shared weights. 

In Python, the line:
    self.weights[idx] += local_grad

Looks like a single atomic operation, but it is actually three bytecode instructions:
1. LOAD value (Read)
2. ADD grad (Compute)
3. STORE value (Write)

When thousands of updates happen per second, threads silently overwrite each other's 
weight updates. The network simply fails to converge, loss goes to NaN, or accuracy halts.
The program NEVER crashes, it just produces bad math. 

Raceguard intercepts this implicitly and pinpoints the exact collision.
"""
import threading
import random
import time
import sys
import os
os.environ["RACEGUARD_WINDOW"] = "0.1"

# Ensure raceguard is importable from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))
from raceguard import protect, configure
import raceguard

# Configure raceguard to warn, so the program can finish and report all issues
configure(mode="warn")

class NeuralNetwork:
    def __init__(self, params_count):
        # We protect the weight arrays. Raceguard will now track every read/write to these lists.
        self.weights = protect([0.1] * params_count)
        self.biases = protect([0.0] * params_count)

    def apply_gradients(self, thread_idx, batch_data, learning_rate=0.01):
        # Local gradients computed per thread (simulated)
        local_gradient_w = [random.uniform(-0.1, 0.1) for _ in batch_data]
        local_gradient_b = [random.uniform(-0.01, 0.01) for _ in batch_data]
        
        # Wait a tiny bit to simulate heavy matmul computation
        time.sleep(random.uniform(0.001, 0.005))
        
        for idx_w, grad in enumerate(local_gradient_w):
            # Simulate processing jitter
            time.sleep(random.uniform(0.0001, 0.001)) 
            
            # RACE CONDITION: Read-Modify-Write
            # Thread A reads weights[0], yields. Thread B reads weights[0], writes. Thread A writes -> B's update is lost!
            self.weights[idx_w] += grad * learning_rate
            
        for idx_b, grad in enumerate(local_gradient_b):
            # RACE CONDITION: Read-Modify-Write
            self.biases[idx_b] += grad * learning_rate


def train_distributed(model, data_chunks):
    threads = []
    
    print(f"[*] Dispatching {len(data_chunks)} worker threads to apply gradients...")
    for i, chunk in enumerate(data_chunks):
        t = threading.Thread(
            target=model.apply_gradients, 
            args=(i, chunk),
            name=f"Worker-GPU-{i}"
        )
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()


if __name__ == "__main__":
    print("==================================================")
    print(" DISTRIBUTED ML TRAINING SIMULATION (RACE BUGGED)")
    print("==================================================")
    
    # 5 network parameters
    model = NeuralNetwork(params_count=5)
    
    # 15 chunks of data, each 5 elements (triggering 15 threads)
    data_chunks = [[random.random() for _ in range(5)] for _ in range(15)]
    
    start_time = time.time()
    train_distributed(model, data_chunks)
    
    print(f"[*] Training run completed in {time.time() - start_time:.3f}s")
    
    # Without raceguard, you would just see the program finish with no errors.
    warnings = raceguard.warnings
    
    if not warnings:
        print("[+] No race conditions detected.")
    else:
        print(f"\n[!] RACEGUARD CAUGHT {len(warnings)} EXTREMELY SUBTLE RACE CONDITIONS:")
        
        # Display the first 3 worst offenses
        for i, w in enumerate(warnings[:3]):
            print(f"\n--- RACE #{i+1} ---")
            print(w)
            print("-" * 50)
            
        if len(warnings) > 3:
            print(f"... and {len(warnings) - 3} more silent math corruptions caught.")
            
        print("\n[?] WHY IS THIS DANGEROUS?")
        print("Because `self.weights[idx_w] += grad` is NOT thread-safe in Python.")
        print("The interpreter switches context between the LOAD and the STORE.")
        print("Without Raceguard, your model would simply fail to converge with zero error logs.")
