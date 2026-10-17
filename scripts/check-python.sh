#!/bin/sh
# Check the Python half of the tree.
#
#   scripts/check-python.sh            # the whole gate
#   scripts/check-python.sh --no-lint  # skip ruff (useful before it is installed)
#
# The docstring gate is strict here: every definition has one, so there is no
# work list to report.  `uv run --frozen' is preferred because it uses the
# interpreter that carries epc, sexpdata and ruff.
set -eu
cd "$(dirname "$0")/.."

LINT=1
[ "${1:-}" = "--no-lint" ] && LINT=0

command -v uv >/dev/null 2>&1 && UV=1 || UV=0

run_python() {
    if [ "$UV" = 1 ]; then
        uv run --frozen --quiet python "$@"
    else
        python3 "$@"
    fi
}

run_ruff() {
    if [ "$UV" = 1 ]; then
        uv run --frozen --quiet ruff "$@"
    else
        ruff "$@"
    fi
}

PY=$(git ls-files --cached --others --exclude-standard '*.py' \
     | grep -v '^test/' | grep -v '^scripts/' \
     | while read -r f; do [ -f "$f" ] && echo "$f"; done)

echo "== py_compile"
# shellcheck disable=SC2086
run_python -m py_compile $PY

echo "== docstring presence (scripts/docstring-report.py --check)"
run_python scripts/docstring-report.py --check

echo "== every source file is named by a test (scripts/coverage-report.py --check)"
run_python scripts/coverage-report.py --check

echo "== the two halves agree on the EPC contract (scripts/check-protocol.py)"
run_python scripts/check-protocol.py

if [ "$LINT" = 1 ]; then
    echo "== ruff: hard gate (E9,F63,F7,F82,E722,F841,W291,W293)"
    # shellcheck disable=SC2086
    run_ruff check --no-cache --output-format concise \
        --select E9,F63,F7,F82,E722,F841,W291,W293 $PY

    echo "== ruff: documentation gate (D), strict"
    # The rules left out here are the stylistic ones pyproject.toml ignores;
    # the CLI --select overrides the config's select, so the ignore list has
    # to be repeated.
    # shellcheck disable=SC2086
    run_ruff check --no-cache --select D --ignore D107,D203,D213,D401,D403 $PY
fi
