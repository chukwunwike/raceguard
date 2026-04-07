from tests.massive_app_race.state.global_store import DB
from tests.massive_app_race.services.payment_gateway import BraintreeMock
from raceguard import RaceConditionError

class CheckoutController:
    """
    The entrypoint for frontend web requests.
    A developer writes this completely unaware that `inventory_manager.py` 
    is aggressively mutating the `DB` in the background.
    """
    def __init__(self):
        self.races_caught = 0
        
    def handle_payment_webhook(self, order_id: str):
        try:
            # 1. Developer fetches the order object
            # (must use subscripting so Raceguard correctly wraps the nested dict)
            try:
                order = DB["active_orders"][order_id]
            except KeyError:
                return {"status": "not_found"}
                
            # 2. Domain logic: Verify order is valid and unpaid
            if order["status"] == "pending_payment" and not order["metadata"]["payment_cleared"]:
                if len(order["items"]) > 0:
                    
                    # 3. YIELD THREAD: Call external service.
                    # This takes 5-15ms. The RebalancerService is scanning every 2ms!
                    # The order might be completely emptied out from beneath us!
                    success = BraintreeMock.process_charge(1500.00)
                    
                    if success:
                        # 4. FATAL ACT: The checkout controller forces payment completion on the reference
                        # BUG: The customer just paid $1500 for a cart that was emptied and cancelled!
                        order["metadata"]["payment_cleared"] = True
                        order["status"] = "fulfilled"
                        
                        return {"status": "success"}
                        
        except RaceConditionError:
            self.races_caught += 1
            return {"status": "race_detected"}
        except KeyError:
            return {"status": "order_disappeared"}

        return {"status": "ignored"}
