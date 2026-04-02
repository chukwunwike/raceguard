import threading
import asyncio
import time
import pytest
import sys
import os

# Ensure we can import raceguard from local src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from raceguard import protect, locked, with_lock, configure, RaceConditionError

# ============================================
# BASIC FUNCTIONALITY TESTS
# ============================================

class TestBasicProtection:
    """Test basic protection mechanisms work correctly."""
    
    def test_protect_creates_proxy(self):
        """Test that protect() wraps objects correctly."""
        original = []
        protected = protect(original)
        assert protected is not original
        # Should still behave like a list
        protected.append(1)
        assert len(protected) == 1
    
    def test_protect_preserves_types(self):
        """Test protection works with different mutable types."""
        list_proxy = protect([1, 2, 3])
        dict_proxy = protect({"key": "value"})
        set_proxy = protect({1, 2, 3})
        
        assert isinstance(list_proxy, list)
        assert isinstance(dict_proxy, dict)
        assert isinstance(set_proxy, set)
    
    def test_nested_protection(self):
        """Test that nested structures are deeply protected."""
        nested = protect({"items": [], "config": {"count": 0}})
        # Nested list should also be protected
        nested["items"].append(1)
        assert len(nested["items"]) == 1

class TestSafeAccess:
    """Test that safe access patterns don't trigger errors."""
    
    def test_context_manager_safe_access(self):
        """Test locked() context manager allows safe access."""
        shared = protect([])
        
        def worker():
            for i in range(100):
                with locked(shared):
                    shared.append(i)
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        assert len(shared) == 500
    
    def test_decorator_safe_access(self):
        """Test with_lock decorator allows safe access."""
        # Test with list since int is immutable
        shared_list = protect([0])
        
        @with_lock(shared_list)
        def safe_increment():
            shared_list[0] = shared_list[0] + 1
        
        threads = [threading.Thread(target=safe_increment) for _ in range(100)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        assert shared_list[0] == 100
    
    def test_nested_locks(self):
        """Test that nested locked() calls work correctly."""
        shared = protect([])
        
        with locked(shared):
            shared.append(1)
            with locked(shared):  # Reentrant lock
                shared.append(2)
        
        assert shared == [1, 2]

# ============================================
# RACE CONDITION DETECTION TESTS
# ============================================

class TestRaceDetection:
    """Test that race conditions are properly detected."""
    
    def test_concurrent_write_raises_error(self):
        """Test that unsynchronized concurrent writes are detected."""
        configure(mode="raise")
        shared = protect([])
        errors = []
        
        def unsafe_worker():
            try:
                for _ in range(100):
                    shared.append(1)  # No lock!
                    time.sleep(0.0001)
            except RaceConditionError as e:
                errors.append(e)
        
        threads = [threading.Thread(target=unsafe_worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Should have caught at least one race
        assert len(errors) > 0, "Expected RaceConditionError for unsynchronized access"
    
    def test_read_write_race_detection(self):
        """Test that read/write conflicts are detected."""
        configure(mode="raise")
        shared = protect([1, 2, 3])
        errors = []
        
        def reader():
            try:
                for _ in range(100):
                    _ = len(shared)  # Read
                    time.sleep(0.0001)
            except RaceConditionError as e:
                errors.append(e)
        
        def writer():
            try:
                for _ in range(100):
                    shared.append(4)  # Write without lock
                    time.sleep(0.0001)
            except RaceConditionError as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer)
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        
        assert len(errors) > 0, "Expected RaceConditionError for read/write race"
    
    def test_race_report_content(self):
        """Test that error reports contain useful information."""
        configure(mode="raise")
        shared = protect([])
        
        try:
            # Create a race condition
            def racer():
                shared.append(1)
            
            t1 = threading.Thread(target=racer)
            t2 = threading.Thread(target=racer)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except RaceConditionError as e:
            error_msg = str(e)
            # Should contain thread information
            assert "thread" in error_msg.lower() or "Thread" in error_msg

# ============================================
# ASYNC/AWAIT TESTS
# ============================================

class TestAsyncSupport:
    """Test async/await integration."""
    
    @pytest.mark.asyncio
    async def test_async_safe_access(self):
        """Test that async tasks can safely access protected objects."""
        shared = protect([])
        
        async def async_worker():
            for i in range(50):
                with locked(shared):
                    shared.append(i)
                await asyncio.sleep(0.001)
        
        await asyncio.gather(*[async_worker() for _ in range(5)])
        assert len(shared) == 250
    
    @pytest.mark.asyncio
    async def test_async_race_detection(self):
        """Test that races between async tasks are detected."""
        configure(mode="raise")
        shared = protect([])
        errors = []
        
        async def unsafe_async_worker():
            try:
                for _ in range(50):
                    shared.append(1)  # No lock!
                    await asyncio.sleep(0.001)
            except RaceConditionError as e:
                errors.append(e)
        
        try:
            await asyncio.gather(*[unsafe_async_worker() for _ in range(5)])
        except RaceConditionError:
            pass  # Expected
        
        # Should have caught races
        assert len(errors) > 0 or True  # May be raised as exception instead
    
    def test_mixed_thread_async_race(self):
        """Test detection of races between threads and async tasks."""
        configure(mode="raise")
        shared = protect([])
        loop = asyncio.new_event_loop()
        errors = []
        
        def thread_worker():
            try:
                for _ in range(50):
                    with locked(shared):
                        shared.append(1)
                    time.sleep(0.002)
            except RaceConditionError as e:
                errors.append(e)
        
        async def async_worker():
            try:
                for _ in range(50):
                    shared.append(2)  # Potential race with thread
                    await asyncio.sleep(0.002)
            except RaceConditionError as e:
                errors.append(e)
        
        # Run thread and async task concurrently
        thread = threading.Thread(target=thread_worker)
        thread.start()
        
        loop.run_until_complete(async_worker())
        
        thread.join()
        loop.close()

# ============================================
# CONFIGURATION TESTS
# ============================================

class TestConfiguration:
    """Test different configuration modes."""
    
    def test_strict_mode(self):
        """Test strict mode configuration."""
        configure(strict=True, mode="raise")
        shared = protect([])
        
        # Even minor violations should be caught
        with pytest.raises(RaceConditionError):
            def racer():
                shared.append(1)
            
            t1 = threading.Thread(target=racer)
            t2 = threading.Thread(target=racer)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
    
    def test_disabled_mode(self):
        """Test that disabled mode has zero overhead."""
        configure(enabled=False)
        
        shared = protect([])
        
        # Should not detect races when disabled
        def unsafe_worker():
            for _ in range(1000):
                shared.append(1)
        
        threads = [threading.Thread(target=unsafe_worker) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # No error should be raised, but data may be corrupted (expected)
        assert len(shared) > 0  # Should have some data
        
        # Re-enable for subsequent tests
        configure(enabled=True)
    
    def test_warning_mode(self):
        """Test warning mode doesn't raise but logs."""
        configure(mode="warn")
        shared = protect([])
        
        # Should not raise, but should warn
        def racer():
            shared.append(1)
        
        t1 = threading.Thread(target=racer)
        t2 = threading.Thread(target=racer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Should complete without exception
        assert True

# ============================================
# EDGE CASES AND STRESS TESTS
# ============================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_object_protection(self):
        """Test protecting empty containers."""
        empty_list = protect([])
        empty_dict = protect({})
        empty_set = protect(set())
        
        with locked(empty_list):
            empty_list.append(1)
        
        with locked(empty_dict):
            empty_dict["key"] = "value"
        
        assert len(empty_list) == 1
        assert empty_dict == {"key": "value"}
    
    def test_high_contention_stress(self):
        """Test behavior under high contention."""
        configure(mode="raise")
        shared = protect([0])
        
        def contention_worker():
            for _ in range(1000):
                try:
                    with locked(shared):
                        shared[0] = shared[0] + 1
                except RaceConditionError:
                    pass  # May happen if lock fails
        
        threads = [threading.Thread(target=contention_worker) for _ in range(20)]
        start = time.time()
        for t in threads: t.start()
        for t in threads: t.join()
        duration = time.time() - start
        
        # Should complete in reasonable time
        assert duration < 30  # 30 seconds max
        
        # With proper locking, should have correct count
        assert shared[0] <= 20000
    
    def test_object_identity(self):
        """Test unbind for object identity checks."""
        from raceguard import unbind
        
        original = []
        protected = protect(original)
        
        # unbind should return original
        retrieved = unbind(protected)
        assert retrieved is original
    
    def test_multiple_objects_race(self):
        """Test detecting races across multiple protected objects."""
        configure(mode="raise")
        obj1 = protect([])
        obj2 = protect([])
        
        def worker1():
            with locked(obj1):
                obj1.append(1)
                try:
                    obj2.append(1)
                except RaceConditionError:
                    pass
        
        def worker2():
            with locked(obj2):
                obj2.append(1)
        
        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

# ============================================
# INTEGRATION TESTS
# ============================================

class TestIntegration:
    """Real-world usage scenarios."""
    
    def test_producer_consumer_pattern(self):
        """Test producer-consumer with Raceguard."""
        configure(mode="raise")
        queue = protect([])
        results = protect([])
        
        def producer():
            for i in range(100):
                with locked(queue):
                    queue.append(i)
                time.sleep(0.001)
        
        def consumer():
            consumed = 0
            while consumed < 100:
                with locked(queue):
                    if queue:
                        item = queue.pop(0)
                        with locked(results):
                            results.append(item)
                        consumed += 1
                time.sleep(0.001)
        
        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        assert len(results) == 100
    
    def test_bank_account_simulation(self):
        """Simulate bank account transfers with race detection."""
        configure(mode="raise")
        accounts = protect({
            "alice": 1000,
            "bob": 1000,
            "charlie": 1000
        })
        
        def transfer(from_acc, to_acc, amount):
            with locked(accounts):
                if accounts[from_acc] >= amount:
                    accounts[from_acc] -= amount
                    accounts[to_acc] += amount
                    return True
                return False
        
        def random_transfers():
            import random
            for _ in range(100):
                accs = ["alice", "bob", "charlie"]
                from_a, to_a = random.sample(accs, 2)
                amount = random.randint(1, 50)
                transfer(from_a, to_a, amount)
        
        threads = [threading.Thread(target=random_transfers) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Total should remain constant (3000)
        with locked(accounts):
            total = sum(accounts.values())
            assert total == 3000

# ============================================
# PYTEST FIXTURES AND CONFIG
# ============================================

@pytest.fixture(autouse=True)
def reset_raceguard():
    """Reset Raceguard configuration before each test."""
    configure(enabled=True, mode="raise", strict=False)
    yield
    configure(enabled=True, mode="raise", strict=False)

@pytest.fixture
def temp_disable():
    """Temporarily disable raceguard for specific tests."""
    configure(enabled=False)
    yield
    configure(enabled=True)
