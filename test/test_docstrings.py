#!/usr/bin/env python3
"""The documentation gate for the Python half of the tree.

`scripts/docstring-report.py' is the authoritative report (it also walks the
Elisp files with a real Emacs reader); this test is the fast copy that keeps
the answer visible from the test suite.  It fails on the first definition that
has no docstring, and names the file and line so the fix is obvious.
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_GLOBS = ("popweb.py", "core/*.py", "extension/*/*.py")


def source_files():
    """Return every Python source file that must be documented."""
    files = []
    for pattern in SOURCE_GLOBS:
        files.extend(sorted(ROOT.glob(pattern)))
    return [path for path in files if path.is_file()]


def definitions(tree):
    """Yield (kind, name, line) for every module, class and function in TREE."""
    yield ("module", tree, 1)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield ("function", node, node.lineno)
        elif isinstance(node, ast.ClassDef):
            yield ("class", node, node.lineno)


class DocstringTest(unittest.TestCase):
    """Every module, class and function has a docstring."""

    def test_every_definition_is_documented(self):
        """The report is empty, or the test names what is missing."""
        missing = []
        checked = 0
        for path in source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for kind, node, line in definitions(tree):
                checked += 1
                if not ast.get_docstring(node):
                    name = getattr(node, "name", path.name)
                    missing.append("{0}:{1}: {2} {3}".format(path.relative_to(ROOT), line, kind, name))
        self.assertGreater(checked, 0, "no Python source file was found")
        self.assertEqual(missing, [], "\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
