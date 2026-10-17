#!/bin/sh
# Run every test that does not need a running Emacs frame or a real Anki.
#
#   scripts/check-test.sh
#
# The ERT suites are read straight from the sources (`load-prefer-newer'), so a
# stale .elc left over from debugging cannot make them pass or fail wrongly.
# The Python tests run through `uv run --frozen' when `uv' is available, which
# is what provides epc/sexpdata, and through python3 otherwise.
set -eu
cd "$(dirname "$0")/.."

EMACS=${EMACS:-emacs}

LOAD_PATH="-L ."
for directory in extension/*/; do
    LOAD_PATH="$LOAD_PATH -L ${directory%/}"
done
LOAD_PATH="$LOAD_PATH -L test"

if command -v uv >/dev/null 2>&1; then
    run_python() { uv run --frozen --quiet python "$@"; }
else
    run_python() { python3 "$@"; }
fi

echo "== docstrings (scripts/docstring-report.py --check)"
python3 scripts/docstring-report.py --check

echo "== EPC contract (scripts/check-protocol.py)"
run_python scripts/check-protocol.py

for suite in test/*-test.el; do
    [ -f "$suite" ] || continue
    echo "== ERT: $suite"
    "$EMACS" -Q --batch --eval "(setq load-prefer-newer t)" \
        $LOAD_PATH -l "$suite" -f ert-run-tests-batch-and-exit
done

echo "== Python tests"
run_python -m unittest discover -s test -p 'test_*.py' -t .
