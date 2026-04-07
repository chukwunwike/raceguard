import sys
import os

# Add parent directory to sys.path so tests.* absolute imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import threading
from raceguard import configure
from tests.massive_app_race.services.inventory_manager import RebalancerService
from tests.massive_app_race.controllers.checkout_api import CheckoutController

def test_sprawling_architecture_race():
    """
    This test orchestrates the massive multi-folder application simulation.
    It proves Raceguard detects memory violations even when the code is wildly 
    distributed across abstractions (Controllers -> Services -> Global State).
    """
    configure(mode="raise")
    
    inventory_service = RebalancerService()
    inventory_service.start()
    
    controller = CheckoutController()
    
    # Simulate a thundering herd of payment webhooks hitting the API at once
    threads = []
    for _ in range(100):
        t = threading.Thread(target=controller.handle_payment_webhook, args=("order_A1B2",))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    inventory_service.stop()
    
    total_races = controller.races_caught + inventory_service.races_caused
    assert total_races > 0, "Failed to catch the architectural check-then-act race"
    
    print("\n" + "="*50)
    print("MASSIVE ARCHITECTURE RACE TEST RESULTS")
    print("="*50)
    print(f"Checkout Controllers caught: {controller.races_caught}")
    print(f"Background Rebalancers caught: {inventory_service.races_caused}")
    print(f"Total Structural Races Prevented: {total_races}")
    print("="*50 + "\n")

if __name__ == "__main__":
    test_sprawling_architecture_race()
