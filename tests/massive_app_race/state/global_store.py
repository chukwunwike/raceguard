import time
from raceguard import protect

# Global store representing an in-memory database or Redis cache
# Shared across the entire multi-folder application
DB = protect({
    "active_orders": {
        "order_A1B2": {
            "status": "pending_payment",
            "items": [{"sku": "GPU-4090", "qty": 1}],
            "customer_id": "cust_828",
            "created_at": time.time(),
            "metadata": {
                "shipping": "express",
                "payment_cleared": False
            }
        }
    }
})
