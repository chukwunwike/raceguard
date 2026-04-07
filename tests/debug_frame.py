import faulthandler
import sys

# Dump stack traces of all threads after 2 seconds and exit!
faulthandler.dump_traceback_later(2, exit=True)

from tests.apocalypse_test import TestGILBytecodeExploitation

print("Starting isolated test_frame_evaluation_race...", flush=True)
t = TestGILBytecodeExploitation()
t.test_frame_evaluation_race()
print("Finished isolated test_frame_evaluation_race!", flush=True)
