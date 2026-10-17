#!/usr/bin/env python3
"""Tests for the popup placement arithmetic.

Every position `popweb-popup-pos' accepts is checked against a hand computed
value, including the flip above or left of the cursor when the popup would
leave the frame, and the clamp at the screen origin.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.geometry import adjust_render_pos  # noqa: E402  (import after sys.path)


class AdjustRenderPosTest(unittest.TestCase):
    """The eight positions of `popweb-popup-pos'."""

    def place(self, popup_pos, cursor=(500, 400), size=(200, 100), frame=(100, 50, 1000, 800), offsets=(0, 20)):
        """Call the function under test with a consistent set of defaults."""
        x, y = cursor
        w, h = size
        frame_x, frame_y, frame_w, frame_h = frame
        x_offset, y_offset = offsets
        return adjust_render_pos(
            popup_pos, x, y, x_offset, y_offset, w, h, frame_x, frame_y, frame_w, frame_h
        )

    def test_top_left_uses_the_frame_origin(self):
        """The top left corner ignores the cursor entirely."""
        self.assertEqual(self.place("top-left"), (100, 50))

    def test_top_right_anchors_to_the_right_edge(self):
        """The top right corner is one popup width from the right edge."""
        self.assertEqual(self.place("top-right"), (900, 50))

    def test_bottom_left_anchors_to_the_bottom_edge(self):
        """The bottom left corner subtracts the popup height and the y offset."""
        self.assertEqual(self.place("bottom-left"), (100, 730))

    def test_bottom_right_anchors_to_both_edges(self):
        """The bottom right corner subtracts the popup size from both edges."""
        self.assertEqual(self.place("bottom-right"), (900, 730))

    def test_point_bottom_centres_below_the_cursor(self):
        """The default point position is centred horizontally and starts at the cursor."""
        self.assertEqual(self.place("point-bottom"), (400, 400))

    def test_point_bottom_flips_above_and_left_on_overflow(self):
        """A popup that would leave the frame is moved above and to the left."""
        self.assertEqual(self.place("point-bottom", cursor=(1050, 800)), (900, 680))

    def test_point_bottom_clamps_at_the_origin(self):
        """A cursor near the origin does not produce a negative coordinate."""
        self.assertEqual(self.place("point-bottom", cursor=(-50, -10)), (0, 0))

    def test_point_bottom_right_starts_at_the_cursor(self):
        """The point-bottom-right position does not centre the window."""
        self.assertEqual(self.place("point-bottom-right"), (500, 400))

    def test_point_bottom_right_flips_on_overflow(self):
        """Both axes flip when the popup would leave the frame."""
        self.assertEqual(self.place("point-bottom-right", cursor=(1000, 800)), (900, 680))

    def test_middle_centres_in_the_frame(self):
        """The middle position uses half of the remaining space, as a float."""
        self.assertEqual(self.place("middle"), (500.0, 380.0))

    def test_empty_offset_does_not_shift_the_frame_positions(self):
        """Frame anchored positions ignore the cursor but still subtract the offset."""
        self.assertEqual(self.place("top-right", offsets=(10, 20)), (890, 50))

    def test_unknown_position_raises(self):
        """An unknown option is a configuration error, not a silent default."""
        with self.assertRaises(Exception) as raised:
            self.place("point-top")
        self.assertIn("popweb-popup-pos", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
