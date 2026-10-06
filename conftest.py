# Ensure the reference-implementation root is importable regardless of how
# pytest was invoked (python -m pytest, bare pytest, or an IDE runner).
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 2026-10-06: the system Python has the full `litellm` package installed, and a
# regular package always beats the local namespace shim `./litellm/` (no
# __init__.py) in import resolution - so evals/callback_test.py's
# `from litellm.routing_callback import ...` failed with ModuleNotFoundError even
# though the file lives right here (the component documented in README and
# architecture.md as "repair inside LiteLLM"). Extend the imported package's
# __path__ with the shim directory before collection; site-packages content is
# untouched and the local file becomes litellm.routing_callback again.
try:
    import litellm as _litellm

    _shim = os.path.join(ROOT, "litellm")
    if _shim not in list(getattr(_litellm, "__path__", [])):
        _litellm.__path__.append(_shim)
except Exception:  # pragma: no cover - litellm absent: nothing to extend
    pass
