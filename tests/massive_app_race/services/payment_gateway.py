import time
import random

class BraintreeMock:
    @staticmethod
    def process_charge(amount: float) -> bool:
        """Simulates a slow, highly variable network call to a payment gateway."""
        time.sleep(random.uniform(0.005, 0.015))
        return True
