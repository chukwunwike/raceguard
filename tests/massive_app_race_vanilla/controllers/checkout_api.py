from tests.massive_app_race_vanilla.state.global_store import DB
from tests.massive_app_race_vanilla.services.payment_gateway import BraintreeMock

class CheckoutController:
    """
    The entrypoint for frontend web requests.
    This reads from standard, unprotected Python dictionaries.
    """
    def __init__(self):
        self.successful_payments = 0
        self.corrupted_orders = 0
        
    def handle_payment_webhook(self, order_id: str):
        try:
            # 1. Fetch the raw dictionary
            order = DB["active_orders"][order_id]
                
            # 2. Check: Verify order is valid and unpaid
            if order["status"] == "pending_payment" and not order["metadata"]["payment_cleared"]:
                if len(order["items"]) > 0:
                    
                    # 3. YIELD: The massive vulnerability window
                    success = BraintreeMock.process_charge(1500.00)
                    
                    if success:
                        # 4. FATAL ACT: The checkout controller forces payment completion!
                        # Without Raceguard, this blindly forces the order to successful 
                        # even if the inventory_manager emptied the items!
                        order["metadata"]["payment_cleared"] = True
                        order["status"] = "fulfilled"
                        self.successful_payments += 1
                        
                        # MEASURE SILENT CORRUPTION:
                        # If we marked it fulfilled, but the cart is empty, SILENT DATA CORRUPTION HAPPENED!
                        if len(order["items"]) == 0:
                            self.corrupted_orders += 1
                            import threading
                            print(f"[RACE!] SILENT DATA CORRUPTION in {threading.current_thread().name}: "
                                  f"Payment $1500 cleared, but cart has 0 items!")
                        
                        return {"status": "success"}
                        
        except KeyError:
            return {"status": "order_disappeared"}

        return {"status": "ignored"}
