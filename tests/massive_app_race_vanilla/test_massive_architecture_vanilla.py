import sys
import os

# Add parent directory to sys.path so tests.* absolute imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import threading
from tests.massive_app_race_vanilla.services.inventory_manager import RebalancerService
from tests.massive_app_race_vanilla.controllers.checkout_api import CheckoutController
from tests.massive_app_race_vanilla.state.global_store import DB

def test_vanilla_architecture_corrupts_data():
    """
    This test runs the same scenario as the massive architecture 
    race test, but WITHOUT Raceguard protection.
    
    It proves and counts how many times silent data corruption occurred.
    """
    inventory_service = RebalancerService()
    inventory_service.start()
    
    controller = CheckoutController()
    
    # Thundering herd of payment webhooks
    threads = []
    for _ in range(100):
        t = threading.Thread(target=controller.handle_payment_webhook, args=("order_A1B2",))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    inventory_service.stop()
    
    # We expect silent data corruption to have happened multiple times!
    assert controller.corrupted_orders > 0, "Failed to corrupt the unprotected data"
    
    print("\n" + "="*60)
    print("MASSIVE ARCHITECTURE (VANILLA/UNPROTECTED) RESULTS")
    print("="*60)
    print(f"Total Database Read/Writes: {controller.successful_payments}")
    print(f"Inventory Cancellation Sweeps: {inventory_service.cancellations_attempted}")
    print(f"SILENT DATA CORRUPTIONS (Paid for 0 Items): {controller.corrupted_orders}")
    print("="*60)
    print(f"Final DB Order Status: {DB['active_orders']['order_A1B2']['status']}")
    print(f"Final DB Item Count: {len(DB['active_orders']['order_A1B2']['items'])}")
    print("="*60 + "\n")

if __name__ == "__main__":
    test_vanilla_architecture_corrupts_data()
