import time

# Vanilla Python dictionary without Raceguard protection
DB = {
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
}
