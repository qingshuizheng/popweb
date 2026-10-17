#!/usr/bin/env python3
"""Report definitions that have no docstring, in the elisp and Python sources.

This is the gate for the "every definition is documented" requirement:

    scripts/docstring-report.py              # totals + worst files
    scripts/docstring-report.py --list       # every missing item
    scripts/docstring-report.py --check      # exit 1 when anything is missing

Elisp is walked with a real Emacs reader (macros, quoting and reader syntax
cannot fool it); Python uses `ast`.  Third-party files kept verbatim are
skipped on purpose -- see VENDORED.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Third-party code kept verbatim so it can still be diffed against upstream:
# rewriting its docstrings would only make future merges harder.
VENDORED: set[str] = set()

# kind -> index of the docstring inside the top-level form
ELISP_DOC_INDEX = {
    "defun": 3,
    "defsubst": 3,
    "defmacro": 3,
    "cl-defun": 3,
    "cl-defmacro": 3,
    "cl-defstruct": 2,
    "defvar": 3,
    "defvar-local": 3,
    "defconst": 3,
    "defcustom": 3,
    "defface": 3,
    "defvaralias": 3,
    "define-minor-mode": 2,
    "define-globalized-minor-mode": 2,
    "define-derived-mode": 4,
}

ELISP_INDEX_FORM = "(defvar z/doc-index '(%s))" % " ".join(
    f'("{kind}" . {idx})' for kind, idx in ELISP_DOC_INDEX.items()
)

# Print FILE<TAB>path, then MISSING<TAB>kind<TAB>name<TAB>line per finding,
# then TOTAL<TAB>definitions<TAB>missing.
ELISP_PROGRAM = r"""
(defun z/report (file)
  (let ((forms 0) (missing 0))
    (princ (format "FILE\t%s\n" file))
    (with-temp-buffer
      (set-syntax-table emacs-lisp-mode-syntax-table)
      (setq-local parse-sexp-ignore-comments t)
      (insert-file-contents file)
      (goto-char (point-min))
      (condition-case nil
          (while t
            (let ((form (read (current-buffer))))
              (when (and (consp form) (symbolp (car form)))
                (let* ((head (symbol-name (car form)))
                       ;; A `defvar' without a value is a declaration of a
                       ;; variable that another file defines; it cannot carry a
                       ;; docstring without also giving the variable a value, so
                       ;; it is not counted here.  A `defvar' with a value still
                       ;; needs one.
                       (declaration (and (member head '("defvar" "defvar-local"))
                                         (<= (length form) 2)))
                       (idx (cdr (assoc head z/doc-index)))
                       (name (nth 1 form)))
                  (when (and idx (symbolp name) (not declaration))
                    (setq forms (1+ forms))
                    (unless (stringp (nth idx form))
                      (setq missing (1+ missing))
                      (princ (format "MISSING\t%s\t%s\t%d\n"
                                     head name (line-number-at-pos)))))))))
        (end-of-file nil)
        (error (princ (format "PARSE-ERROR\t%s\t%d\n" file (point))))))
    (princ (format "TOTAL\t%d\t%d\n" forms missing))))
"""


def existing(files: list[pathlib.Path]) -> list[pathlib.Path]:
    """Return FILES without the ones the working tree no longer has.

    The file lists come from `git ls-files`, which reports the index: a file that
    a change under review deletes is still listed until the deletion is staged,
    and reading it would fail the gate for a file that is gone on purpose.
    """
    return [path for path in files if path.exists()]


def repo_files(pattern: str) -> list[pathlib.Path]:
    """Return the repository files matching PATTERN.

    Uses `git ls-files' with `--others --exclude-standard', so ignored trees
    (a .venv created by `uv run', for one) never end up in the report, while
    files that are new but not committed yet are still checked.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z",
         pattern],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / name for name in out.split("\0") if name]


def elisp_files(limit: set[str] | None) -> list[pathlib.Path]:
    """Return the elisp files to check, vendored ones excluded.

    When LIMIT is given it holds repo-relative paths and only those files are
    returned.
    """
    return sorted(
        p for p in repo_files("*.el")
        if p.name not in VENDORED
        and (limit is None or str(p.relative_to(ROOT)) in limit)
    )


def python_files(limit: set[str] | None) -> list[pathlib.Path]:
    """Return the Python files to check, vendored and test files excluded.

    When LIMIT is given it holds repo-relative paths and only those files are
    returned.
    """
    return sorted(
        p for p in repo_files("*.py")
        if str(p.relative_to(ROOT)) not in VENDORED
        and "test/" not in str(p.relative_to(ROOT))
        and "scripts/" not in str(p.relative_to(ROOT))
        and (limit is None or str(p.relative_to(ROOT)) in limit)
    )


def run_elisp(files: list[pathlib.Path]) -> tuple[list[tuple[str, str, int, str]], dict[str, tuple[int, int]]]:
    """Check FILES with a real Emacs reader.

    Return the missing items as (path, kind, line, name) tuples and, per file,
    the number of definitions and of missing docstrings.
    """
    missing: list[tuple[str, str, int, str]] = []
    per_file: dict[str, tuple[int, int]] = {}
    for f in files:
        rel = str(f.relative_to(ROOT))
        out = subprocess.run(
            ["emacs", "-Q", "--batch",
             "--eval", ELISP_INDEX_FORM,
             "--eval", ELISP_PROGRAM,
             "--eval", f'(z/report "{f}")'],
            capture_output=True, text=True, cwd=ROOT,
        )
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if parts[0] == "MISSING":
                missing.append((rel, parts[1], int(parts[3]), parts[2]))
            elif parts[0] == "TOTAL":
                per_file[rel] = (int(parts[1]), int(parts[2]))
            elif parts[0] == "PARSE-ERROR":
                print(f"PARSE ERROR {rel}:{parts[2]}", file=sys.stderr)
    return missing, per_file


def run_python(files: list[pathlib.Path]) -> tuple[list[tuple[str, str, int, str]], dict[str, tuple[int, int]]]:
    """Check FILES with `ast`.

    Return the missing items as (path, kind, line, name) tuples and, per file,
    the number of definitions and of missing docstrings.  Files that do not
    parse are reported on stderr and skipped.
    """
    missing: list[tuple[str, str, int, str]] = []
    per_file: dict[str, tuple[int, int]] = {}
    for f in files:
        rel = str(f.relative_to(ROOT))
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            print(f"PARSE ERROR {rel}: {exc}", file=sys.stderr)
            continue
        total = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                total += 1
                if not ast.get_docstring(node):
                    missing.append((rel, type(node).__name__.lower(), node.lineno, node.name))
        per_file[rel] = (total, sum(1 for m in missing if m[0] == rel))
    return missing, per_file


def main() -> int:
    """Print the report and, with --check, exit non-zero on missing docstrings."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="list every missing docstring")
    ap.add_argument("--check", action="store_true", help="exit 1 when anything is missing")
    ap.add_argument("paths", nargs="*", help="limit to these paths (repo-relative)")
    args = ap.parse_args()
    limit = set(args.paths) or None

    missing, per_file = run_elisp(existing(elisp_files(limit)))
    py_missing, py_per_file = run_python(existing(python_files(limit)))
    missing += py_missing
    per_file.update(py_per_file)

    total_defs = sum(d for d, _ in per_file.values())
    total_missing = sum(m for _, m in per_file.values())
    print(f"definitions {total_defs}   missing docstring {total_missing}   "
          f"documented {total_defs - total_missing} "
          f"({100 * (total_defs - total_missing) / max(total_defs, 1):.1f}%)")
    print()
    print(f"{'file':<40}{'defs':>6}{'missing':>9}")
    for rel, (defs, miss) in sorted(per_file.items(), key=lambda kv: (-kv[1][1], kv[0])):
        if miss:
            print(f"{rel:<40}{defs:>6}{miss:>9}")
    if args.list:
        print()
        for rel, kind, line, name in sorted(missing):
            print(f"{rel}:{line}: {kind} {name}")

    if args.check and total_missing:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
