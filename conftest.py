# Ensure the reference-implementation root is importable regardless of how
# pytest was invoked (python -m pytest, bare pytest, or an IDE runner).
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
