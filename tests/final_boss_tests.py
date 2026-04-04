import threading
import asyncio
import time
import contextvars
from raceguard import protect, locked, with_lock, configure, RaceConditionError

# ============================================
# FINAL BOSS EDGE CASES
# ============================================

class TestFinalBossEdgeCases:
    """The absolutely weirdest edge cases in Python concurrency."""
    
    def test_contextvar_mutation_bleed_race(self):
        """
        PEP 567 ContextVars are designed to handle async context natively.
        However, a common trap is storing a MUTABLE structure in a ContextVar and mutating
        it directly instead of using `.set()`. 
        If the context is inherited (e.g. via asyncio.create_task), the mutable structure 
        is shared across async tasks! This causes silent data races.
        Raceguard should catch this.
        """
        configure(mode="raise")
        
        # A context var storing a protected dict
        shared_state = contextvars.ContextVar('shared_state', default=protect({"requests": 0}))
        
        races_caught = 0
        
        async def handle_request():
            nonlocal races_caught
            # We don't call state.set(), we just mutate the dictionary in-place.
            # Because the asyncio task inherited the context, ALL tasks share THIS dict!
            current_state = shared_state.get()
            
            try:
                # Deliberate race: Read, yield, write (Check-then-act)
                val = current_state["requests"]
                await asyncio.sleep(0.001)
                current_state["requests"] = val + 1
            except RaceConditionError:
                races_caught += 1

        async def main():
            # Spawn 10 concurrent requests that all inherit the same contextvar dictionary
            tasks = [asyncio.create_task(handle_request()) for _ in range(10)]
            await asyncio.gather(*tasks)
            
        asyncio.run(main())
        
        # At least one race should be caught due to contextvar state bleed
        assert races_caught > 0, "Failed to catch ContextVar state bleed mutation race"
        print(f"ContextVar bleed races caught in async environment: {races_caught}")


    def test_class_object_monkey_patching_race(self):
        """
        In Python, classes are just objects (instances of `type`).
        It is possible to `protect()` a class object itself, to prevent concurrent monkey-patching.
        Web frameworks and ORMs do this during dynamic initialization.
        """
        configure(mode="raise")
        
        class WebService:
            # Class-level attribute
            port = 8080
            
            def handle(self):
                return self.port

        # Protect the CLASS object's attributes directly!
        ProtectedWebService = protect(WebService)
        
        races_caught = 0
        
        def monkey_patcher():
            nonlocal races_caught
            try:
                # One thread tries to mutate the class-level config directly
                # while another thread does it too
                # This tests `__getattr__` and `__setattr__` on a CLASS proxy
                current_port = ProtectedWebService.port
                time.sleep(0.001)
                ProtectedWebService.port = current_port + 1
            except RaceConditionError:
                races_caught += 1

        threads = [threading.Thread(target=monkey_patcher) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_extreme_ecommerce_checkout_race(self):
        """
        An EXTREMELY COMPLEX and terrifyingly realistic Check-Then-Act race condition.
        This simulates an e-commerce platform with two asynchronous flows:
        1. A Payment Processor (Worker) authorizing a user's cart.
        2. An Inventory Webhook (Sweeper) cancelling carts if items go out of stock.

        The Race:
        The Payment Processor aliases the deep dictionary `state["carts"]["cart_1"]`.
        It checks if the cart is "active" and has items.
        It simulates a 3rd-party API call to Stripe (yielding the thread).
        Concurrently, the Inventory Webhook fires, determines the item is out of stock,
        checks that payment isn't authorized yet, empties the cart, and marks it "cancelled".
        The Payment Processor wakes up and forces `authorized = True` and `status = "paid"`,
        resulting in a customer paying for an empty, cancelled cart.

        Raceguard catches this precise read/write collision deep within the 
        nested ["payment"]["authorized"] and ["status"] branches.
        """
        configure(mode="raise")
        
        # Deeply nested, highly realistic application state
        app_state = protect({
            "carts": {
                "cart_999": {
                    "status": "active",
                    "items": [{"id": "SKU_42", "price": 299.99}],
                    "payment": {
                        "authorized": False,
                        "transaction_id": None
                    }
                }
            }
        })
        
        races_caught = 0
        running = True
        
        def inventory_webhook_sweeper():
            # Out-of-Stock webhook randomly fires and cancels un-paid carts
            while running:
                try:
                    cart = app_state["carts"]["cart_999"]
                    
                    # Webhook logic: If active and unpaid, cancel it
                    if cart["status"] == "active" and not cart["payment"]["authorized"]:
                        cart["items"].clear()
                        cart["status"] = "cancelled"
                    
                    # Reset the simulation state so the Payment Processors can try again
                    time.sleep(0.001)
                    cart["items"].append({"id": "SKU_42", "price": 299.99})
                    cart["payment"]["authorized"] = False
                    cart["payment"]["transaction_id"] = None
                    cart["status"] = "active"
                    
                except (KeyError, RuntimeError):
                    pass
                except RaceConditionError:
                    nonlocal races_caught
                    races_caught += 1

        def payment_processor_worker(cart_id):
            nonlocal races_caught
            try:
                # 1. Developer aliases the deeply nested cart 
                user_cart = app_state["carts"][cart_id]
                
                # 2. CHECK: verify cart is active, unpaid, and has items
                if user_cart["status"] == "active" and not user_cart["payment"]["authorized"]:
                    if len(user_cart["items"]) > 0:
                        
                        # 3. YIELD: Simulate 3rd-party Stripe API call taking a few ms
                        # This is the massive vulnerability window.
                        time.sleep(random.uniform(0.001, 0.005))
                        
                        # 4. ACT: Stripe returned success! Charge the user.
                        # BUG: The webhook might have cancelled and emptied the cart!
                        # The user is now charged for 0 items!
                        user_cart["payment"]["authorized"] = True
                        user_cart["payment"]["transaction_id"] = f"txn_{random.randint(1000, 9999)}"
                        user_cart["status"] = "paid"
                        
            except RaceConditionError:
                races_caught += 1
            except Exception:
                pass


        import random
        # Start the aggressive Inventory Webhook
        webhook_thread = threading.Thread(target=inventory_webhook_sweeper, daemon=True)
        webhook_thread.start()
        
        # Fire a storm of concurrent Payment Requests (like a bot drop or double-clicks)
        payment_threads = []
        for _ in range(100):
            t = threading.Thread(target=payment_processor_worker, args=("cart_999",))
            payment_threads.append(t)
            t.start()
            
        for t in payment_threads:
            t.join()
            
        running = False
        webhook_thread.join(timeout=1.0)

        assert races_caught > 0, "Failed to catch the extreme ecommerce check-then-act race"
        print(f"Extreme E-Commerce Check-Then-Act races caught: {races_caught}")


if __name__ == '__main__':
    t = TestFinalBossEdgeCases()
    print("Running ContextVar Bleed Race...")
    t.test_contextvar_mutation_bleed_race()
    print("\nRunning Class Monkey-Patching Race...")
    t.test_class_object_monkey_patching_race()
    print("\nRunning Extreme E-Commerce Checkout Race...")
    t.test_extreme_ecommerce_checkout_race()
    print("\nAll Final Boss tests passed!")
