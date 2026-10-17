"""Load the Python half of an extension by file name.

Emacs passes an absolute path in every `call_module_method' request, so the
Python side cannot import an extension as a package: the file is executed on
its own with `importlib'.  The application caches the loaded module by path,
because a popup is created many times per session and executing the module
again for every keystroke would be wasteful.
"""

from __future__ import annotations

import importlib.util
import types


def load_module(module_path: str) -> types.ModuleType:
    """Execute the Python file at MODULE_PATH and return its module.

    The module is not registered in `sys.modules'; a path that appears twice
    under different spellings therefore produces two module objects, which is
    what the application-level cache by absolute path avoids.
    """
    spec = importlib.util.spec_from_file_location(module_path, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
