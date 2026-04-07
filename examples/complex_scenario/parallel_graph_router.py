"""
Concurrent Graph Routing Simulation

This demonstrates an incredibly hard-to-find race condition.
1. The shared state is a deeply nested dictionary (Node -> Metrics).
2. The logic traverses the graph asynchronously.
3. The actual destructive race happens inside a tiny helper function `_recalculate_decay`
   that is called several functions deep in the stack.

Finding this manually requires reading thousands of lines of code. Raceguard spots
it instantly because it proxies the dictionary itself and its nested components.
"""
import threading
import time
import random
import sys
import os
os.environ["RACEGUARD_WINDOW"] = "0.1"

# Ensure raceguard is importable from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))
from raceguard import protect, configure
import raceguard

# Log mode emits to python's standard logger without halting execution
configure(mode="warn")

class RoutingNetwork:
    def __init__(self, size):
        # The main routing table
        # We protect the individual node metric dictionaries. 
        # Raceguard requires explicit wrapping of the data structures that will be concurrently mutated.
        self.routing_table = {
            node_id: protect({"active": True, "load": 0.0, "packets": 0}) 
            for node_id in range(size)
        }

    def _recalculate_decay(self, node_metrics, load_delta):
        # A deeply nested helper function where the actual race happens!
        current_load = node_metrics["load"]
        # Context switch opportunity
        time.sleep(random.uniform(0.0001, 0.001))
        
        # BUG: Race condition! Writing to the same dictionary key without a lock
        node_metrics["load"] = (current_load * 0.9) + load_delta
        node_metrics["packets"] += 1

    def _process_node(self, node_id, packet_size):
        # Mid-level logic processing
        metrics = self.routing_table[node_id]
        if metrics["active"]:
            self._recalculate_decay(metrics, packet_size)

    def route_packet(self, packet_id, path):
        """Simulate a packet traversing a series of nodes."""
        for node_id in path:
            # Simulate network travel time
            time.sleep(random.uniform(0.001, 0.005))
            # Process arrival at node
            self._process_node(node_id, packet_size=random.uniform(1.0, 5.0))

def simulate_network_traffic():
    network = RoutingNetwork(size=10)
    threads = []
    
    # 20 packets routing concurrently across overlapping paths
    print("[*] Simulating high-concurrency network traffic...")
    for p_id in range(20):
        # Random path of 4 nodes
        path = [random.randint(0, 9) for _ in range(4)]
        t = threading.Thread(
            target=network.route_packet, 
            args=(f"PKT-{p_id}", path),
            name=f"PacketThread-{p_id}"
        )
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

if __name__ == "__main__":
    print("==================================================")
    print(" ASYNC GRAPH ROUTING SIMULATION (RACE BUGGED)")
    print("==================================================")
    
    start = time.time()
    simulate_network_traffic()
    print(f"[*] Traffic simulation ended in {time.time() - start:.3f}s")
    
    warnings = raceguard.warnings
    if warnings:
        print(f"\n[!] RACEGUARD CAUGHT {len(warnings)} DEEP NESTED RACE CONDITIONS:")
        
        print("\n--- WORST OFFENSE (Deep Call Stack) ---")
        print(warnings[0])
        print("-" * 50)
        
        print("\n[?] WHY IS THIS COMPLICATED?")
        print("1. The error occurs inside `_recalculate_decay`.")
        print("2. The shared state is passed as a reference: `node_metrics`.")
        print("3. It is effectively impossible to spot visually since `node_metrics` isn't a global variable, it's just a local reference to a piece of a global dictionary.")
        print("Raceguard sees correctly through all references!")
