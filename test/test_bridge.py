#!/usr/bin/env python3
"""Tests for the EPC bridge to Emacs.

The EPC client is replaced by a recorder, so the tests check the calls the
bridge makes (method names and Base64 encoded arguments) rather than the wire
protocol, which `test/popweb-epc-test.el' covers from the other side.
"""

import base64
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import bridge  # noqa: E402  (import after sys.path)


class RecordingClient:
    """EPC client that records calls and returns canned answers."""

    def __init__(self, answers=None):
        """Create a client whose `call_sync' answers are taken from ANSWERS."""
        self.calls = []
        self.sync_calls = []
        self.answers = list(answers or [])
        self.closed = False

    def call(self, method, args):
        """Record an asynchronous call."""
        self.calls.append((method, args))

    def call_sync(self, method, args):
        """Record a synchronous call and return the next canned answer."""
        self.sync_calls.append((method, args))
        return self.answers.pop(0) if self.answers else []

    def close(self):
        """Remember that the client was closed."""
        self.closed = True


def decode_args(args):
    """Return ARGS with every Base64 element decoded to text."""
    return [base64.b64decode(arg).decode() for arg in args]


class BridgeTest(unittest.TestCase):
    """The encoding rules and the two directions of the conversation."""

    def setUp(self):
        """Install a recording client and forget any cached config directory."""
        self.client = RecordingClient()
        self.saved_client = bridge.epc_client
        self.saved_dir = bridge.emacs_config_dir
        bridge.epc_client = self.client
        bridge.emacs_config_dir = ""

    def tearDown(self):
        """Restore the module state that the tests changed."""
        bridge.epc_client = self.saved_client
        bridge.emacs_config_dir = self.saved_dir

    def test_string_passes_through(self):
        """A string is not rewritten."""
        self.assertEqual(bridge.convert_arg_to_str("hello"), "hello")

    def test_bool_becomes_upper_case(self):
        """Booleans are spelled the way the Emacs side reads them."""
        self.assertEqual(bridge.convert_arg_to_str(True), "TRUE")
        self.assertEqual(bridge.convert_arg_to_str(False), "FALSE")

    def test_list_becomes_parenthesised(self):
        """A list becomes one parenthesized string, with nested lists too."""
        self.assertEqual(bridge.convert_arg_to_str(["a", "b"]), "(a b)")
        self.assertEqual(bridge.convert_arg_to_str([1, [True, "x"]]), "(1 (TRUE x))")

    def test_empty_list_becomes_empty_parentheses(self):
        """An empty list keeps its shape, so Emacs can split it back to nil."""
        self.assertEqual(bridge.convert_arg_to_str([]), "()")

    def test_numbers_pass_through(self):
        """Only strings, booleans and lists have a special form."""
        self.assertEqual(bridge.convert_arg_to_str(42), 42)

    def test_base64_round_trip_of_unicode(self):
        """The encoding is UTF-8, not the platform encoding."""
        encoded = bridge.string_to_base64("héllo — 世界")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), "héllo — 世界")

    def test_base64_accepts_non_strings(self):
        """A value is printed before it is encoded, like the original did."""
        self.assertEqual(base64.b64decode(bridge.string_to_base64(42)).decode(), "42")

    def test_eval_in_emacs_encodes_every_argument(self):
        """The method name stays plain and every argument is Base64."""
        bridge.eval_in_emacs("my-func", ["a b", True, ["x", "y"]])
        method, args = self.client.calls[0]
        self.assertEqual(method, "eval-in-emacs")
        self.assertEqual(args[0], "my-func")
        self.assertEqual(decode_args(args[1:]), ["a b", "TRUE", "(x y)"])

    def test_eval_in_emacs_without_a_client_reports_and_returns(self):
        """Calling Emacs before the client exists prints instead of raising."""
        bridge.epc_client = None
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            bridge.eval_in_emacs("my-func", [])
        self.assertIn("init_epc_client", output.getvalue())

    def test_get_emacs_vars_converts_booleans_and_empty_lists(self):
        """The boolean flag decides whether the Lisp value is a Python bool."""
        self.client.answers = [[[True, "t"], [False, "nil"], [], ["value", "nil"]]]
        self.assertEqual(bridge.get_emacs_vars(["a", "b", "c", "d"]), [True, False, False, "value"])

    def test_get_emacs_var_returns_the_value(self):
        """A single variable is read with the same conversion."""
        self.client.answers = [["dark", "nil"]]
        self.assertEqual(bridge.get_emacs_var("popweb-popup-pos"), "dark")

    def test_get_emacs_var_reports_a_boolean(self):
        """A boolean variable comes back as a Python bool."""
        self.client.answers = [[True, "t"]]
        self.assertIs(bridge.get_emacs_var("popweb-enable-debug"), True)

    def test_get_emacs_func_result_turns_nil_into_false(self):
        """EPC reports Lisp nil as an empty list, which callers read as False."""
        self.client.answers = [[]]
        self.assertIs(bridge.get_emacs_func_result("popweb-get-theme-mode", []), False)

    def test_get_emacs_func_result_returns_the_value(self):
        """A non-empty answer is returned unchanged."""
        self.client.answers = ["dark"]
        self.assertEqual(bridge.get_emacs_func_result("popweb-get-theme-mode", []), "dark")

    def test_get_emacs_config_dir_creates_and_caches(self):
        """The directory is created once and its path is reused afterwards."""
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "popweb")
            with mock.patch.object(bridge, "get_emacs_var", return_value=target) as getter:
                first = bridge.get_emacs_config_dir()
                second = bridge.get_emacs_config_dir()
            self.assertTrue(Path(first).is_dir())
            self.assertTrue(first.endswith("/"))
            self.assertEqual(first, second)
            getter.assert_called_once_with("popweb-config-location")

    def test_init_epc_client_connects_once(self):
        """A second init keeps the first connection."""
        bridge.epc_client = None
        with mock.patch.object(bridge, "EPCClient") as client_class:
            bridge.init_epc_client(1234)
            bridge.init_epc_client(1234)
        client_class.assert_called_once()
        self.assertEqual(client_class.call_args.args, (("127.0.0.1", 1234),))

    def test_close_epc_client_only_closes_a_live_client(self):
        """Closing before the client exists is a no-op."""
        bridge.epc_client = None
        bridge.close_epc_client()
        bridge.epc_client = RecordingClient()
        bridge.close_epc_client()
        self.assertTrue(bridge.epc_client.closed)


if __name__ == "__main__":
    unittest.main()
