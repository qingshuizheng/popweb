#!/usr/bin/env python3
"""Tests for the popup window, its page and the GUI thread bridge.

`WebWindow.__init__` is exercised against the fake Qt classes, which record
the window flags, the settings and the scripts that were run.  The methods are
also tested on instances whose web view is a plain recorder, so the assertions
are about what popweb asks Qt to do rather than about Qt itself.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test import fake_qt  # noqa: E402  (installs PyQt6 substitutes)

fake_qt.install()

from core import window as window_module  # noqa: E402
from test.fake_qt import (  # noqa: E402
    QApplication,
    QEventLoop,
    QUrl,
    QWebEnginePage,
)


class FakeMouseEvent:
    """Mouse event with the four methods the window filter calls."""

    def __init__(self, event_type, x, y, global_x, global_y):
        """Create an event at (X, Y) inside the window and (GLOBAL_X, GLOBAL_Y) on screen."""
        self._type = event_type
        self._position = fake_qt._Point(x, y)
        self._global = fake_qt._Point(global_x, global_y)

    def type(self):
        """Return the event type."""
        return self._type

    def button(self):
        """Return the pressed button."""
        return fake_qt._Qt.MouseButton.LeftButton

    def position(self):
        """Return the position relative to the receiving widget."""
        return self._position

    def globalPosition(self):
        """Return the position on the screen."""
        return self._global


class FakeWebView:
    """Minimal stand-in for the view, with a page that records scripts."""

    def __init__(self):
        """Create the view with a recording page."""
        self._page = QWebEnginePage()
        self.zoom_factor = 1.0
        self.loaded = None

    def page(self):
        """Return the page."""
        return self._page

    def setZoomFactor(self, factor):
        """Remember the zoom factor."""
        self.zoom_factor = factor

    def load(self, url):
        """Remember the loaded URL."""
        self.loaded = url


class FakeSizes:
    """The part of the size store that a window uses."""

    def __init__(self, saved=None):
        """Create a store with SAVED as its initial content."""
        self.saved = dict(saved or {})
        self.written = []

    def get(self, module_name):
        """Return the saved size of MODULE_NAME."""
        return self.saved.get(module_name)

    def set(self, module_name, width, height):
        """Remember a dragged size."""
        self.saved[module_name] = (int(width), int(height))
        self.written.append((module_name, int(width), int(height)))


def make_window(sizes=None, module_name=None):
    """Return a window whose shell was built by `__init__` against fake Qt."""
    with mock.patch.object(window_module, "get_emacs_var", return_value=1), mock.patch.object(
        window_module,
        "get_emacs_func_result",
        side_effect=lambda name, args: "#123456" if name == "popweb-get-theme-background" else "dark",
    ), mock.patch.object(
        window_module.CookiesManager, "get_cookies_dir", return_value="/tmp/popweb-test-cookies"
    ):
        return window_module.WebWindow(
            fake_qt._Size(1920, 1080), module_name=module_name, sizes=sizes
        )


class PostGuiTest(unittest.TestCase):
    """The decorator that moves a call onto the GUI thread."""

    def test_method_runs_with_its_arguments(self):
        """A decorated method is called on the object it was called on."""

        class Greeter(fake_qt.QObject):
            def __init__(self):
                super().__init__()
                self.calls = []

            @window_module.PostGui()
            def hello(self, name, punctuation=""):
                self.calls.append((name, punctuation))

        greeter = Greeter()
        greeter.hello("world", punctuation="!")
        self.assertEqual(greeter.calls, [("world", "!")])

    def test_plain_function_runs_with_its_arguments(self):
        """With INCLASS nil the first argument is not treated as the object."""
        calls = []

        @window_module.PostGui(inclass=False)
        def record(value):
            calls.append(value)

        record(42)
        self.assertEqual(calls, [42])


class WebWindowInitTest(unittest.TestCase):
    """What `__init__` asks Qt to set up."""

    def test_window_is_frameless_and_on_top(self):
        """The window has no decorations and stays above other windows."""
        window = make_window()
        self.assertEqual(
            window.window_flags,
            fake_qt._Qt.WindowType.FramelessWindowHint
            | fake_qt._Qt.WindowType.WindowStaysOnTopHint
            | fake_qt._Qt.WindowType.ToolTip,
        )
        self.assertEqual(window.margins, (0, 0, 0, 0))

    def test_view_and_page_are_connected(self):
        """The window owns one view, and the view owns the page."""
        window = make_window()
        self.assertIs(window.webview.page(), window.web_page)
        self.assertEqual(window.layout_obj.widgets, [window.webview])

    def test_background_and_theme_come_from_emacs(self):
        """The page is painted with the Emacs background before it loads."""
        window = make_window()
        self.assertEqual(window.web_page.background_color.value, "#123456")
        self.assertEqual(window.theme_mode, "dark")

    def test_settings_are_enabled(self):
        """Every web engine setting popweb relies on is switched on."""
        window = make_window()
        attributes = window.settings.attributes
        self.assertEqual(len(attributes), 11)
        self.assertTrue(attributes[fake_qt.QWebEngineSettings.WebAttribute.JavascriptEnabled])
        self.assertFalse(attributes[fake_qt.QWebEngineSettings.WebAttribute.ShowScrollBars])

    def test_zoom_is_doubled_on_a_wide_screen(self):
        """A screen wider than 3000 pixels gets twice the configured zoom."""
        with mock.patch.object(window_module, "get_emacs_var", return_value=1), mock.patch.object(
            window_module,
            "get_emacs_func_result",
            side_effect=lambda name, args: "#000000" if name == "popweb-get-theme-background" else "light",
        ), mock.patch.object(
            window_module.CookiesManager, "get_cookies_dir", return_value="/tmp/popweb-test-cookies"
        ):
            window = window_module.WebWindow(fake_qt._Size(3200, 2000))
        self.assertEqual(window.zoom_factor, 2)
        self.assertEqual(window.webview.zoom_factor, 2)


class WebWindowBehaviourTest(unittest.TestCase):
    """The methods that run after the window exists."""

    def setUp(self):
        """Create a window and replace its view with a recorder."""
        self.window = make_window()
        self.view = FakeWebView()
        self.window.webview = self.view
        self.window.web_page = self.view.page()

    def test_popup_shows_the_window(self):
        """Without developer tools only the window itself is shown."""
        with mock.patch.object(window_module, "get_emacs_var", return_value=False):
            self.window.popup()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.developer_tools_view.isVisible())
        self.assertIsNone(self.window.web_page.dev_tools_page)

    def test_popup_shows_developer_tools_when_enabled(self):
        """The tools window is attached to the page when the option is on."""
        with mock.patch.object(window_module, "get_emacs_var", return_value=True):
            self.window.popup()
        self.assertTrue(self.window.developer_tools_view.isVisible())
        self.assertIsNotNone(self.window.web_page.dev_tools_page)

    def test_reset_zoom_applies_the_factor(self):
        """The zoom factor is applied to the view, not kept in the window."""
        self.window.zoom_factor = 1.5
        self.window.reset_zoom()
        self.assertEqual(self.view.zoom_factor, 1.5)

    def test_update_theme_mode_reads_emacs(self):
        """The mode is read on demand, so a theme switch is picked up."""
        with mock.patch.object(window_module, "get_emacs_func_result", return_value="light"):
            self.window.update_theme_mode()
        self.assertEqual(self.window.theme_mode, "light")

    def test_loading_js_runs_on_progress(self):
        """The trimming snippet runs while the page loads."""
        self.window.loading_js_code = "trim()"
        self.window.theme_mode = "light"
        self.window.execute_loading_js_code()
        self.assertEqual(self.view.page().scripts, ["trim()"])

    def test_dark_mode_is_injected_once_per_load(self):
        """A dark theme injects Dark Reader and enables it."""
        self.window.loading_js_code = "trim()"
        self.window.theme_mode = "dark"
        self.window.execute_loading_js_code()
        scripts = self.view.page().scripts
        self.assertEqual(len(scripts), 3)
        self.assertEqual(scripts[0], "trim()")
        self.assertIn("if (typeof DarkReader === 'undefined')", scripts[1])
        self.assertIn("DarkReader.enable", scripts[2])

    def test_load_finish_runs_the_file_js_then_the_callback(self):
        """The optional file content is called with the arguments, then the callback."""
        called = []
        self.window.js_file_code = "function result"
        self.window.js_file_code_args = "42"
        self.window.load_finish_callback = lambda: called.append(True)
        self.window.execute_load_finish_js_code()
        self.assertEqual(self.view.page().scripts, ["function result(42);"])
        self.assertEqual(called, [True])

    def test_load_finish_without_arguments_calls_with_empty_parentheses(self):
        """No arguments means `code();`, which is what the upstream format does."""
        self.window.js_file_code = "function result"
        self.window.js_file_code_args = None
        self.window.execute_load_finish_js_code()
        self.assertEqual(self.view.page().scripts, ["function result();"])

    def test_eval_in_emacs_forwards_the_argument_list(self):
        """The window method is a thin wrapper over the module function."""
        with mock.patch.object(window_module, "eval_in_emacs") as evaluate:
            self.window.eval_in_emacs("my-func", ["word"])
        evaluate.assert_called_once_with("my-func", ["word"])

    def test_disable_dark_mode_runs_the_disable_call(self):
        """Disabling is one JavaScript call."""
        self.window.disable_dark_mode()
        self.assertIn("DarkReader.disable", self.view.page().scripts[0])


class BrowserPageTest(unittest.TestCase):
    """The synchronous JavaScript helper used by LaTeX and the colour picker."""

    def test_execute_javascript_returns_the_page_value(self):
        """The callback result is returned after the nested loop ends."""
        page = window_module.BrowserPage()
        page.js_results = [18, 4]
        self.assertEqual(page.execute_javascript("width()"), 18)
        self.assertEqual(page.execute_javascript("height()"), 4)
        self.assertEqual(page.scripts, ["width()", "height()"])

    def test_execute_javascript_returns_nil_when_the_page_does(self):
        """A JavaScript expression without a value yields None."""
        page = window_module.BrowserPage()
        self.assertIsNone(page.execute_javascript("void 0"))


class ResizeEdgesTest(unittest.TestCase):
    """The pure arithmetic behind drag-resizing."""

    def test_edges_are_detected_in_the_eight_pixel_band(self):
        """Each edge and corner is recognised, the middle is not."""
        self.assertEqual(window_module.resize_edges(2, 2, 400, 300), (True, True, False, False))
        self.assertEqual(window_module.resize_edges(398, 298, 400, 300), (False, False, True, True))
        self.assertEqual(window_module.resize_edges(2, 298, 400, 300), (True, False, False, True))
        self.assertEqual(window_module.resize_edges(200, 150, 400, 300), (False, False, False, False))

    def test_right_and_bottom_edges_only_change_the_size(self):
        """Dragging the bottom right corner leaves the origin alone."""
        self.assertEqual(
            window_module.resized_geometry(100, 100, 400, 300, 20, 10, (False, False, True, True)),
            (100, 100, 420, 310),
        )

    def test_left_and_top_edges_move_the_origin(self):
        """Dragging the top left corner keeps the opposite edges in place."""
        self.assertEqual(
            window_module.resized_geometry(100, 100, 400, 300, 20, 10, (True, True, False, False)),
            (120, 110, 380, 290),
        )

    def test_size_is_clamped_and_the_origin_follows(self):
        """A drag past the minimum stops growing and keeps the right edge fixed."""
        self.assertEqual(
            window_module.resized_geometry(100, 100, 300, 200, 200, 150, (True, True, False, False)),
            (240, 200, window_module.MIN_WINDOW_WIDTH, window_module.MIN_WINDOW_HEIGHT),
        )


class WindowResizeTest(unittest.TestCase):
    """The remembered size and the drag that sets it."""

    def setUp(self):
        """Create a window at a known place and size."""
        self.window = make_window()
        self.window.resize(400, 300)
        self.window.move(100, 100)

    def drag(self, x, y, global_x, global_y, release=False):
        """Send one mouse event to the window filter."""
        event_type = fake_qt.QEvent.Type.MouseButtonRelease if release else fake_qt.QEvent.Type.MouseMove
        event = FakeMouseEvent(event_type, x, y, global_x, global_y)
        return self.window.eventFilter(self.window, event)

    def test_a_dragged_size_wins_over_the_extension(self):
        """After the drag, `resize' keeps the size the user chose."""
        press = FakeMouseEvent(fake_qt.QEvent.Type.MouseButtonPress, 2, 2, 102, 102)
        self.assertTrue(self.window.eventFilter(self.window, press))
        self.assertTrue(self.drag(20, 20, 120, 120))
        self.assertEqual(
            (self.window.width(), self.window.height()), (382, 282)
        )
        self.assertTrue(self.drag(20, 20, 120, 120, release=True))
        self.assertEqual(self.window.user_size, (382, 282))
        self.window.resize(300, 200)
        self.assertEqual((self.window.width(), self.window.height()), (382, 282))

    def test_forget_user_size_returns_control_to_the_extension(self):
        """Forgetting the drag lets the next extension size take effect."""
        self.window.user_size = (500, 400)
        self.window.resize(300, 200)
        self.assertEqual((self.window.width(), self.window.height()), (500, 400))
        self.window.forget_user_size()
        self.window.resize(300, 200)
        self.assertEqual((self.window.width(), self.window.height()), (300, 200))

    def test_a_saved_size_is_loaded_and_a_drag_updates_it(self):
        """The previous session's size wins, and a new drag is written back."""
        sizes = FakeSizes({"dict_bing": (640, 480)})
        window = make_window(sizes=sizes, module_name="dict_bing")
        self.assertEqual(window.user_size, (640, 480))
        window.resize(300, 200)
        self.assertEqual((window.width(), window.height()), (640, 480))

        window.move(100, 100)
        press = FakeMouseEvent(fake_qt.QEvent.Type.MouseButtonPress, 2, 2, 102, 102)
        self.assertTrue(window.eventFilter(window, press))
        move = FakeMouseEvent(fake_qt.QEvent.Type.MouseMove, 20, 20, 300, 300)
        self.assertTrue(window.eventFilter(window, move))
        release = FakeMouseEvent(fake_qt.QEvent.Type.MouseButtonRelease, 20, 20, 300, 300)
        self.assertTrue(window.eventFilter(window, release))
        self.assertEqual(sizes.written, [("dict_bing", window.width(), window.height())])

    def test_resize_to_fit_grows_but_does_not_clip(self):
        """A larger content size wins; a smaller one keeps the dragged size."""
        self.window.user_size = (400, 300)
        self.window.resize_to_fit(500, 350)
        self.assertEqual((self.window.width(), self.window.height()), (500, 350))
        self.assertEqual(self.window.user_size, (500, 350))
        self.window.resize_to_fit(200, 200)
        self.assertEqual((self.window.width(), self.window.height()), (500, 350))

    def test_a_press_in_the_middle_is_left_to_the_page(self):
        """Only the edge band starts a resize."""
        press = FakeMouseEvent(fake_qt.QEvent.Type.MouseButtonPress, 200, 150, 300, 250)
        self.assertFalse(self.window.eventFilter(self.window, press))
        self.assertIsNone(self.window._resize_edges)

    def test_moving_over_an_edge_sets_the_cursor(self):
        """The cursor changes while the pointer is in the edge band."""
        self.drag(2, 150, 102, 250)
        self.assertEqual(self.window.cursor, fake_qt._Qt.CursorShape.SizeHorCursor)
        self.drag(200, 150, 300, 250)
        self.assertIsNone(self.window.cursor)


if __name__ == "__main__":
    unittest.main()
