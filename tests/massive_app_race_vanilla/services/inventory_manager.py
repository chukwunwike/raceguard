import time
import threading
from tests.massive_app_race_vanilla.state.global_store import DB

class RebalancerService:
    """
    A terrifying background service that runs as a daemon.
    It periodically scans the global store for orders that are "pending_payment"
    but their items have gone out of stock globally, and cancels them.
    It runs in a completely different part of the codebase.
    """
    def __init__(self):
        self.running = True
        self.cancellations_attempted = 0

    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        while self.running:
            try:
                # In vanilla Python, iterating via list(keys()) is standard
                for order_id in list(DB["active_orders"].keys()):
                    order = DB["active_orders"][order_id]
                    
                    if order["status"] == "pending_payment" and not order["metadata"]["payment_cleared"]:
                        # "GPU-4090 went out of stock! We must empty the cart!"
                        order["items"].clear()
                        order["status"] = "inventory_cancelled"
                        self.cancellations_attempted += 1
                        
                        # Keep it empty long enough for checkout threads to wake up and cause corruption
                        time.sleep(0.020)
                        
                        order["items"].append({"sku": "GPU-4090", "qty": 1})
                        order["metadata"]["payment_cleared"] = False
                        order["status"] = "pending_payment"
                        
            except (KeyError, RuntimeError):
                pass

            time.sleep(0.002)

    def stop(self):
        self.running = False
