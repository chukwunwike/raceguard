import threading
import time
from raceguard import protect, configure, clear_warnings, unbind

def run_simulation(use_protection: bool):
    if use_protection:
        configure(enabled=True, mode="raise", strict=True)
    else:
        configure(enabled=False)
        
    clear_warnings()
        
    inventory = {"laptop": 1}
    if use_protection:
        inventory = protect(inventory)
        
    orders = [{"id": 1, "item": "laptop"}, {"id": 2, "item": "laptop"}, {"id": 3, "item": "laptop"}]
    
    success_count = 0
    errors = []
    
    barrier = threading.Barrier(3)
    
    def process_order(order):
        nonlocal success_count
        try:
            barrier.wait()
            item = order["item"]
            
            current_stock = inventory[item]
            
            time.sleep(0.01)
            
            if current_stock > 0:
                inventory[item] = current_stock - 1
                success_count += 1
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=process_order, args=(o,)) for o in orders]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    raw_inventory = unbind(inventory) if use_protection else inventory
    
    print(f"Protection: {use_protection}")
    print(f"Final Inventory: {raw_inventory['laptop']}")
    print(f"Successful Orders: {success_count}")
    if errors:
        print(f"Errors Caught: {len(errors)}")
    print("-" * 40)

if __name__ == "__main__":
    print("Running WITHOUT Raceguard (Exploit Succeeds)")
    run_simulation(use_protection=False)
    
    print("\nRunning WITH Raceguard (Exploit Blocked)")
    run_simulation(use_protection=True)
