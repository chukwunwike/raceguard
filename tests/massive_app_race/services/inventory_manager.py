import time
import threading
from raceguard import locked, RaceConditionError
from tests.massive_app_race.state.global_store import DB

class RebalancerService:
    """
    A terrifying background service that runs as a daemon.
    It periodically scans the global store for orders that are "pending_payment"
    but their items have gone out of stock globally, and cancels them.
    It runs in a completely different part of the codebase.
    """
    def __init__(self):
        self.running = True
        self.races_caused = 0

    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        while self.running:
            try:
                # Iterate over a live view of orders
                # Note: We must use .keys() and subscripting because 
                # Raceguard protects nested objects via __getitem__. 
                # Using .items() directly returns raw objects from the underlying dictated memory!
                for order_id in list(DB["active_orders"].keys()):
                    order = DB["active_orders"][order_id]
                    # Anti-pattern: it checks status, then forces cancellation
                    # This happens concurrently while controllers are trying to fulfill orders!
                    if order["status"] == "pending_payment" and not order["metadata"]["payment_cleared"]:
                        # "GPU-4090 went out of stock!"
                        order["items"].clear()
                        order["status"] = "inventory_cancelled"
                        
                        # Immediately restore the simulation state so the race can continue reproducing
                        time.sleep(0.001)
                        order["items"].append({"sku": "GPU-4090", "qty": 1})
                        order["metadata"]["payment_cleared"] = False
                        order["status"] = "pending_payment"
                        
            except (KeyError, RuntimeError):
                pass
            except RaceConditionError:
                self.races_caused += 1

            time.sleep(0.002)

    def stop(self):
        self.running = False
