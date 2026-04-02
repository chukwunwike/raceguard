import threading
import time
import sys
sys.path.append('src')
from raceguard import protect, RaceConditionError

def check():
    shared = protect([0])
    errors = []
    
    def reader():
        try:
            # Just read without a lock
            val = len(shared)
        except Exception as e:
            errors.append(e)

    # Use a barrier to force simultaneous reads
    barrier = threading.Barrier(2)

    def reader_with_barrier():
        barrier.wait()
        reader()

    t1 = threading.Thread(target=reader_with_barrier)
    t2 = threading.Thread(target=reader_with_barrier)

    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    if any(isinstance(e, RaceConditionError) for e in errors):
        print("CONCURRENT READ ISSUE STILL EXISTS")
    else:
        print("CONCURRENT READ ISSUE FIXED")

if __name__ == "__main__":
    check()
