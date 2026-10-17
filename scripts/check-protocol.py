#!/usr/bin/env python3
"""Check that the two halves of popweb agree on the EPC contract.

The interface between Emacs and Python is made of names only: EPC method
names, the Emacs variables Python reads, and the extension functions that
Emacs calls by string.  A rename on one side is not a compile error on the
other, it is a popup that silently does nothing, so this script compares the
names on both sides.

    scripts/check-protocol.py
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

ELISP_DEFINITION = re.compile(
    r"^\((?:defun|defsubst|defmacro|cl-defun|cl-defmacro|defvar|defvar-local|"
    r"defconst|defcustom|defgroup|define-minor-mode)\s+([\w-]+)",
    re.MULTILINE,
)
ELISP_EPC_CALL = re.compile(r'\(popweb-call-(?:async|sync)\s+"([\w-]+)"')
MODULE_CALL = re.compile(r'"call_module_method"\s+([\w-]+)\s+"([\w-]+)"')
PYTHON_EMACS_NAME = re.compile(r'"(popweb[\w-]*)"')
PYTHON_METHOD = re.compile(r"^    def (\w+)\(", re.MULTILINE)
PYTHON_FUNCTION = re.compile(r"^def (\w+)\(", re.MULTILINE)

#: The extension directories and the file that holds their Emacs/Python halves.
EXTENSIONS = {
    "dict": ("extension/dict/popweb-dict.el", "extension/dict/popweb-dict.py"),
    "latex": ("extension/latex/popweb-latex.el", "extension/latex/popweb-latex.py"),
    "color-picker": (
        "extension/color-picker/popweb-color-picker.el",
        "extension/color-picker/color-picker.py",
    ),
    "url-preview": ("extension/url-preview/popweb-url.el", "extension/url-preview/popweb-url.py"),
    "anki-review": (
        "extension/anki-review/popweb-anki-review.el",
        "extension/anki-review/popweb-anki-review.py",
    ),
}


def source_files(pattern: str) -> list[pathlib.Path]:
    """Return the source files matching PATTERN, tests and scripts excluded."""
    files = []
    for path in sorted(ROOT.glob(pattern)):
        relative = str(path.relative_to(ROOT))
        if relative.startswith(("test/", "scripts/")):
            continue
        if path.is_file():
            files.append(path)
    return files


def read(path: pathlib.Path) -> str:
    """Return the text of PATH."""
    return path.read_text(encoding="utf-8")


def elisp_definitions() -> set[str]:
    """Return every name that the Elisp tree defines."""
    names = set()
    for path in source_files("**/*.el"):
        names.update(ELISP_DEFINITION.findall(read(path)))
    return names


def elisp_epc_methods() -> set[str]:
    """Return the Python methods that Elisp calls by name."""
    names = set()
    for path in source_files("**/*.el"):
        names.update(ELISP_EPC_CALL.findall(read(path)))
    return names


def python_methods() -> set[str]:
    """Return the methods that the Python application exposes to Elisp."""
    return set(PYTHON_METHOD.findall(read(ROOT / "core/application.py")))


def python_emacs_names() -> set[str]:
    """Return the Emacs names that Python refers to as strings."""
    names = set()
    for path in source_files("**/*.py"):
        names.update(PYTHON_EMACS_NAME.findall(read(path)))
    return names


def main() -> int:
    """Compare the names of both halves and exit non-zero on a mismatch."""
    definitions = elisp_definitions()
    epc_methods = elisp_epc_methods()
    methods = python_methods()
    emacs_names = python_emacs_names()

    problems = []

    missing_methods = sorted(epc_methods - methods)
    if missing_methods:
        problems.append("Elisp calls methods that core/application.py does not define: "
                        + ", ".join(missing_methods))

    missing_emacs = sorted(name for name in emacs_names if name not in definitions)
    if missing_emacs:
        problems.append("Python reads Emacs names that the Elisp tree does not define: "
                        + ", ".join(missing_emacs))

    checked = 0
    for directory, (elisp_path, python_path) in EXTENSIONS.items():
        elisp = read(ROOT / elisp_path)
        python = read(ROOT / python_path)
        functions = set(PYTHON_FUNCTION.findall(python))
        for module_variable, function in MODULE_CALL.findall(elisp):
            if directory == "url-preview" and "url" not in module_variable:
                continue
            if module_variable not in elisp:
                continue
            checked += 1
            if function not in functions:
                problems.append(
                    "%s calls %s, which %s does not define"
                    % (elisp_path, function, python_path)
                )

    print("elisp definitions %d   epc methods %d   emacs names %d   extension methods %d"
          % (len(definitions), len(epc_methods), len(emacs_names), checked))

    if problems:
        for problem in problems:
            print("FAILED: " + problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
