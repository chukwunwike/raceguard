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
            config = {"port": 8080}
            
            def handle(self):
                return self.config["port"]

        # Protect the CLASS object's dict/attributes
        ProtectedWebService = protect(WebService)
        
        races_caught = 0
        
        def monkey_patcher():
            nonlocal races_caught
            try:
                # One thread tries to mutate the class-level config directly
                # while another thread does it too
                current_port = ProtectedWebService.config["port"]
                time.sleep(0.001)
                ProtectedWebService.config["port"] = current_port + 1
            except RaceConditionError:
                races_caught += 1

        threads = [threading.Thread(target=monkey_patcher) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert races_caught > 0, "Failed to catch concurrent class metadata monkey-patching race"
        print(f"Class/Metaclass monkey-patching races caught: {races_caught}")

if __name__ == '__main__':
    t = TestFinalBossEdgeCases()
    print("Running ContextVar Bleed Race...")
    t.test_contextvar_mutation_bleed_race()
    print("\nRunning Class Monkey-Patching Race...")
    t.test_class_object_monkey_patching_race()
    print("\nAll Final Boss tests passed!")
