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


def make_window():
    """Return a window whose shell was built by `__init__` against fake Qt."""
    with mock.patch.object(window_module, "get_emacs_var", return_value=1), mock.patch.object(
        window_module,
        "get_emacs_func_result",
        side_effect=lambda name, args: "#123456" if name == "popweb-get-theme-background" else "dark",
    ), mock.patch.object(
        window_module.CookiesManager, "get_cookies_dir", return_value="/tmp/popweb-test-cookies"
    ):
        return window_module.WebWindow(fake_qt._Size(1920, 1080))


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


if __name__ == "__main__":
    unittest.main()
