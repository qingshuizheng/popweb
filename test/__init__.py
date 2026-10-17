"""The popweb test suite.

The tests are split in two halves that are run by `scripts/check-test.sh':

- Elisp suites are named `*-test.el' and run under ERT.
- Python tests are named `test_*.py' and run with `unittest'.

The Python tests import the production modules from the repository root, which
is why they are run with `-t .`; `test/fake_qt.py` supplies the Qt classes when
PyQt6 is not installed.
"""
