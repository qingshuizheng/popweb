#!/usr/bin/env python3
"""Tests for the JSON store of popup sizes.

The store must survive a process restart, ignore a corrupt file, and remove
the file when the last size is forgotten.  All of it is file handling, so the
tests use a temporary directory and never touch Qt.
"""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.sizes import WindowSizes  # noqa: E402  (import after sys.path)


class WindowSizesTest(unittest.TestCase):
    """Reading, writing and clearing the saved sizes."""

    def setUp(self):
        """Create a store in a temporary directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "popweb" / "sizes.json")
        self.sizes = WindowSizes(self.path)

    def test_missing_file_starts_empty(self):
        """The first run has no file and no error."""
        self.assertEqual(self.sizes.sizes, {})
        self.assertIsNone(self.sizes.get("dict_bing"))

    def test_a_set_size_is_written_and_read_back(self):
        """A size survives a new WindowSizes instance."""
        self.sizes.set("dict_bing", 640, 480)
        self.assertTrue(Path(self.path).is_file())
        self.assertEqual(self.sizes.get("dict_bing"), (640, 480))

        reloaded = WindowSizes(self.path)
        self.assertEqual(reloaded.get("dict_bing"), (640, 480))
        self.assertEqual(json.loads(Path(self.path).read_text())["dict_bing"], [640, 480])

    def test_a_second_set_keeps_the_first(self):
        """Sizes of different modules coexist."""
        self.sizes.set("dict_bing", 640, 480)
        self.sizes.set("url-preview", 480, 270)
        reloaded = WindowSizes(self.path)
        self.assertEqual(
            reloaded.sizes,
            {"dict_bing": (640, 480), "url-preview": (480, 270)},
        )

    def test_clear_one_module(self):
        """Clearing one module leaves the others alone."""
        self.sizes.set("dict_bing", 640, 480)
        self.sizes.set("url-preview", 480, 270)
        self.sizes.clear("dict_bing")
        self.assertEqual(self.sizes.sizes, {"url-preview": (480, 270)})
        self.assertEqual(WindowSizes(self.path).sizes, {"url-preview": (480, 270)})

    def test_clear_everything_removes_the_file(self):
        """An empty store does not leave an empty JSON document behind."""
        self.sizes.set("dict_bing", 640, 480)
        self.sizes.clear()
        self.assertEqual(self.sizes.sizes, {})
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(WindowSizes(self.path).sizes, {})

    def test_clearing_a_missing_file_is_harmless(self):
        """Reset before any size was saved is a no-op."""
        self.sizes.clear()
        self.assertFalse(Path(self.path).exists())

    def test_a_corrupt_file_is_ignored(self):
        """A malformed file is reported and treated as empty."""
        Path(self.path).parent.mkdir(parents=True)
        Path(self.path).write_text("{not json", encoding="utf-8")
        output = StringIO()
        with redirect_stderr(output):
            sizes = WindowSizes(self.path)
        self.assertEqual(sizes.sizes, {})
        self.assertIn("Traceback", output.getvalue())

    def test_an_invalid_entry_is_skipped(self):
        """Only positive integer pairs are sizes."""
        Path(self.path).parent.mkdir(parents=True)
        Path(self.path).write_text(
            json.dumps(
                {
                    "good": [640, 480],
                    "short": [640],
                    "negative": [-1, 480],
                    "float": [640.5, 480],
                    "bool": [True, False],
                    "string": "640x480",
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(WindowSizes(self.path).sizes, {"good": (640, 480)})

    def test_a_non_object_top_level_is_ignored(self):
        """A JSON array is not a size map."""
        Path(self.path).parent.mkdir(parents=True)
        Path(self.path).write_text("[]", encoding="utf-8")
        self.assertEqual(WindowSizes(self.path).sizes, {})

    def test_no_temporary_file_is_left_behind(self):
        """The atomic write cleans up its temporary file."""
        self.sizes.set("dict_bing", 640, 480)
        self.assertEqual(list(Path(self.path).parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
