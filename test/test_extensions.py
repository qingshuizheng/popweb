#!/usr/bin/env python3
"""Tests for the Python half of the five extensions.

Each module is loaded from its real path with the production loader, and is
handed a `FakePopweb` whose two protocol methods record their arguments.  The
window objects are recorders too, so an assertion says what the extension
asked the application to do: which URL was loaded, at which size, and where it
was moved.
"""

import importlib.util
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from test import fake_qt  # noqa: E402  (installs PyQt6 substitutes)

fake_qt.install()


def load_extension(relative_path):
    """Load the extension module at RELATIVE_PATH from its real file."""
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(str(path), str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dict_module = load_extension("extension/dict/popweb-dict.py")
latex_module = load_extension("extension/latex/popweb-latex.py")
color_module = load_extension("extension/color-picker/color-picker.py")
url_module = load_extension("extension/url-preview/popweb-url.py")
anki_module = load_extension("extension/anki-review/popweb-anki-review.py")


class FakePage:
    """Page that records scripts and returns canned JavaScript results."""

    def __init__(self):
        """Create a page with an empty script list and result queue."""
        self.scripts = []
        self.js_results = []
        self.web_channel = None

    def runJavaScript(self, script, callback=None):
        """Record SCRIPT; call CALLBACK with the next canned result."""
        self.scripts.append(script)
        if callback is not None:
            callback(self.js_results.pop(0) if self.js_results else None)

    def execute_javascript(self, script):
        """Record SCRIPT and return the next canned result."""
        self.scripts.append(script)
        return self.js_results.pop(0) if self.js_results else None

    def setWebChannel(self, channel):
        """Remember CHANNEL."""
        self.web_channel = channel


class FakeView:
    """View that records the loaded URL or HTML."""

    def __init__(self, with_channel_attributes=True):
        """Create an empty view.

        WITH_CHANNEL_ATTRIBUTES controls whether the two attributes that the
        Anki extension probes for already exist.
        """
        self.url_value = None
        self.html = None
        self.page_obj = FakePage()
        if with_channel_attributes:
            self.channel = None
            self.handler = None

    def setUrl(self, url):
        """Remember URL."""
        self.url_value = url

    def setHtml(self, html, base_url=None):
        """Remember HTML and its base URL."""
        self.html = html
        self.url_value = base_url

    def load(self, url):
        """Remember URL."""
        self.url_value = url

    def page(self):
        """Return the page."""
        return self.page_obj


class FakeWebWindow:
    """The part of `WebWindow` that an extension uses."""

    def __init__(self, zoom_factor=1.0, with_channel_attributes=True):
        """Create a window with the given zoom factor."""
        self.zoom_factor = zoom_factor
        self.webview = FakeView(with_channel_attributes)
        self.web_page = FakePage()
        self.loading_js_code = "previous-loading"
        self.js_file_code = "previous-file"
        self.js_file_code_args = "previous-args"
        self.render_width = None
        self.render_height = None
        self.theme_updates = 0
        self.popups = 0
        self.size = None
        self.position = None

    def update_theme_mode(self):
        """Count a theme update."""
        self.theme_updates += 1

    def resize(self, width, height):
        """Remember the size."""
        self.size = (width, height)

    def move(self, x, y):
        """Remember the position."""
        self.position = (x, y)

    def popup(self):
        """Count a popup."""
        self.popups += 1


class FakePopweb:
    """The application protocol: three methods and one geometry helper."""

    def __init__(self, windows=None, theme="#abcdef", position=(11, 22)):
        """Create an application with WINDOWS preloaded and a fixed position."""
        self.windows = dict(windows or {})
        self.theme = theme
        self.position = position
        self.adjust_calls = []
        self.channel_calls = []

    def get_web_window(self, module_name):
        """Return the window of MODULE_NAME, creating a recorder."""
        if module_name not in self.windows:
            self.windows[module_name] = FakeWebWindow(with_channel_attributes=False)
        return self.windows[module_name]

    def adjust_render_pos(self, *args):
        """Record ARGS and return the canned position."""
        self.adjust_calls.append(args)
        return self.position

    def build_web_channel(self, *args):
        """Record the channel request and pretend the view now has one."""
        self.channel_calls.append(args)
        window = self.windows[args[1]]
        window.webview.channel = object()
        window.webview.handler = object()

    def get_emacs_func_result(self, method_name, args):
        """Return the theme background that the extensions ask for."""
        if method_name == "popweb-get-theme-background":
            return self.theme
        return None


class DictExtensionTest(unittest.TestCase):
    """The translation window."""

    def test_window_is_loaded_and_sized(self):
        """The URL, the trimming snippet and the optional file reach the window."""
        with tempfile.TemporaryDirectory() as tmp:
            js_file = Path(tmp) / "extra.js"
            js_file.write_text("function extra(args) { return args; }", encoding="utf-8")
            popweb = FakePopweb()
            dict_module.pop_translate_window(
                popweb,
                "dict_bing",
                10,
                20,
                30,
                40,
                100,
                50,
                1000,
                800,
                0.3,
                0.5,
                "https://example.com/?q=word",
                "trim()",
                str(js_file),
                "args",
            )
        window = popweb.windows["dict_bing"]
        self.assertEqual(str(window.webview.url_value), "https://example.com/?q=word")
        self.assertEqual(window.loading_js_code, "trim()")
        self.assertEqual(window.js_file_code, "function extra(args) { return args; }")
        self.assertEqual(window.js_file_code_args, "args")
        self.assertEqual(window.size, (300, 400))
        self.assertEqual(window.position, (11, 22))
        self.assertEqual(window.popups, 1)
        self.assertEqual(window.theme_updates, 1)
        self.assertEqual(popweb.adjust_calls[-1], (40, 60, 30, 40, 300, 400, 100, 50, 1000, 800))

    def test_missing_js_file_is_reported_and_ignored(self):
        """A missing optional file leaves the page working without it."""
        output = io.StringIO()
        with redirect_stdout(output):
            content = dict_module.read_js_content("/nonexistent/popweb.js")
        self.assertEqual(content, "")
        self.assertIn("File not found", output.getvalue())


class LatexExtensionTest(unittest.TestCase):
    """The KaTeX preview window."""

    def write_index(self, directory):
        """Write an index page with the three placeholders and return its path."""
        path = Path(directory) / "index.html"
        path.write_text("BG=BACKGROUND;DIR=INDEX_DIR;TEX=LATEX", encoding="utf-8")
        return str(path)

    def test_formula_page_is_filled_in_and_measured(self):
        """The theme, the directory and the formula replace the placeholders."""
        with tempfile.TemporaryDirectory() as tmp:
            index = self.write_index(tmp)
            window = FakeWebWindow(zoom_factor=1.5)
            window.web_page.js_results = [100, 40]
            popweb = FakePopweb({"latex": window})
            latex_module.pop_latex_window(
                popweb, "latex", index, 10, 20, 30, 40, 100, 50, 1000, 800, True, True, "x^2"
            )
        self.assertEqual(window.webview.html, "BG=#abcdef;DIR={0};TEX=x^2".format(str(Path(index).parent)))
        self.assertEqual(window.loading_js_code, "")
        self.assertEqual(window.size, (180, 60))
        self.assertEqual(window.position, (11, 22))
        self.assertEqual(window.popups, 1)

    def test_unchanged_formula_does_not_reload_the_page(self):
        """`new_latex' nil keeps the page, but still moves the window."""
        with tempfile.TemporaryDirectory() as tmp:
            index = self.write_index(tmp)
            window = FakeWebWindow()
            window.render_width = 120
            window.render_height = 40
            popweb = FakePopweb({"latex": window})
            latex_module.pop_latex_window(
                popweb, "latex", index, 10, 20, 30, 40, 100, 50, 1000, 800, True, False, "x^2"
            )
        self.assertIsNone(window.webview.html)
        self.assertEqual(window.position, (11, 22))

    def test_adjust_uses_the_rendered_size_and_zoom(self):
        """The measured width gets a 1.2 margin, the height only the zoom."""
        window = FakeWebWindow(zoom_factor=2)
        window.web_page.js_results = [50, 30]
        popweb = FakePopweb({"latex": window})
        latex_module.adjust_latex_window(
            popweb, window, 10, 20, 0, 0, 0, 0, 1000, 800, True, True
        )
        self.assertEqual(window.size, (120, 60))
        self.assertEqual(popweb.adjust_calls[-1][4:6], (120, 60))


class ColorPickerExtensionTest(unittest.TestCase):
    """The colour picker window."""

    def write_index(self, directory):
        """Write an index page with the two placeholders and return its path."""
        path = Path(directory) / "index.html"
        path.write_text("DIR=INDEX_DIR;COLOR=DEFAULT_COLOR", encoding="utf-8")
        return str(path)

    def test_empty_colour_becomes_black(self):
        """The picker falls back to black when point is not on a colour."""
        with tempfile.TemporaryDirectory() as tmp:
            index = self.write_index(tmp)
            window = FakeWebWindow()
            popweb = FakePopweb({"color-picker": window})
            color_module.pop_color_picker_window(
                popweb, "color-picker", index, 10, 20, 30, 40, 100, 50, 1000, 800, ""
            )
        self.assertEqual(window.webview.html, "DIR={0};COLOR=#000000".format(str(Path(index).parent)))
        self.assertEqual(window.size, (200, 309))
        self.assertEqual(window.position, (11, 22))
        self.assertEqual(window.popups, 1)

    def test_given_colour_is_passed_through(self):
        """A colour found at point is not replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            index = self.write_index(tmp)
            window = FakeWebWindow()
            popweb = FakePopweb({"color-picker": window})
            color_module.pop_color_picker_window(
                popweb, "color-picker", index, 0, 0, 0, 0, 0, 0, 1000, 800, "#ff0000"
            )
        self.assertIn("COLOR=#ff0000", window.webview.html)

    def test_size_scales_with_the_zoom_factor(self):
        """The fixed page size is multiplied by the popup zoom."""
        window = FakeWebWindow(zoom_factor=1.5)
        popweb = FakePopweb({"color-picker": window})
        color_module.adjust_color_picker_window(popweb, window, 0, 0, 0, 0, 0, 0, 1000, 800)
        self.assertEqual(window.size, (300, 463))


class UrlExtensionTest(unittest.TestCase):
    """The URL preview window."""

    def test_absolute_size_is_used_when_configured(self):
        """The pixel size is passed straight to the window."""
        window = FakeWebWindow()
        popweb = FakePopweb({"url-preview": window})
        url_module.pop_url_window(
            popweb, "url-preview", 10, 20, 30, 40, 100, 50, 1000, 800,
            0.8, 0.45, 480, 270, True, "https://example.com",
        )
        self.assertEqual(str(window.webview.url_value), "https://example.com")
        self.assertEqual(window.size, (480, 270))
        self.assertEqual(window.position, (11, 22))
        self.assertEqual(window.popups, 1)
        self.assertEqual(popweb.adjust_calls[-1], (40, 60, 30, 40, 480, 270, 100, 50, 1000, 800))

    def test_relative_size_scales_with_the_frame(self):
        """The scale factors are applied to the frame size."""
        window = FakeWebWindow()
        popweb = FakePopweb({"url-preview": window})
        url_module.pop_url_window(
            popweb, "url-preview", 10, 20, 30, 40, 100, 50, 1000, 800,
            0.8, 0.45, 480, 270, False, "https://example.com",
        )
        self.assertEqual(window.size, (800, 360))
        self.assertEqual(popweb.adjust_calls[-1][4:6], (800, 360))


class AnkiExtensionTest(unittest.TestCase):
    """The Anki review window and its web channel handler."""

    def write_assets(self, directory):
        """Write the index page and the tooltip script, and return both paths."""
        index = Path(directory) / "index.html"
        index.write_text("QUERY=QUERY_PLACEHOLD;HEAD=HEAD-PLACEHOLD", encoding="utf-8")
        script = Path(directory) / "tooltip.js"
        script.write_text("function setTooltipSearchResults() {}", encoding="utf-8")
        return str(index), str(script)

    def test_tooltip_script_embeds_the_file_and_the_channel_bootstrap(self):
        """The wrapper carries the stylesheet, the script and the channel code."""
        with tempfile.TemporaryDirectory() as tmp:
            _, script = self.write_assets(tmp)
            html = anki_module.get_tooltip_script(script)
        self.assertIn("function setTooltipSearchResults", html)
        self.assertIn("qt.webChannelTransport", html)
        self.assertIn(".rev-tooltip", html)

    def test_missing_tooltip_script_is_reported(self):
        """A missing script yields an empty string instead of an exception."""
        output = io.StringIO()
        with redirect_stdout(output):
            html = anki_module.get_tooltip_script("/nonexistent/tooltip.js")
        self.assertEqual(html, "")
        self.assertIn("Script file not found", output.getvalue())

    def test_window_builds_the_channel_once_and_fills_the_page(self):
        """The first call builds the web channel; every call reloads the page."""
        with tempfile.TemporaryDirectory() as tmp:
            index, script = self.write_assets(tmp)
            window = FakeWebWindow(with_channel_attributes=False)
            popweb = FakePopweb({"anki_review": window})
            anki_module.pop_anki_review_window(
                popweb, "/tmp/anki.py", "anki_review", index, 10, 20, 30, 40,
                100, 50, 1000, 800, 0.8, 0.5, True, script, "/media", True,
                "hello", "callback",
            )
        self.assertEqual(
            popweb.channel_calls[0],
            ("/tmp/anki.py", "anki_review", "handler", "CallHandler", "expanded_on_bridge_cmd", "/media", "callback"),
        )
        self.assertIn("QUERY=hello", window.webview.html)
        self.assertIn("function setTooltipSearchResults", window.webview.html)
        self.assertEqual(window.size, (800, 400))
        self.assertEqual(window.position, (11, 22))
        self.assertEqual(window.popups, 1)
        self.assertEqual(window.loading_js_code, "")


class CallHandlerTest(unittest.TestCase):
    """The QWebChannel handler behind the Anki popup."""

    def make_handler(self, query_notes=None):
        """Return a handler with a recording view and no real Anki."""
        window = FakeWebWindow()
        handler = anki_module.CallHandler(window, "/media", "popweb-dict-callback")
        handler.web_window = window
        return handler

    def test_request_has_the_anki_connect_shape(self):
        """AnkiConnect expects action, params and version 6."""
        handler = self.make_handler()
        self.assertEqual(
            handler.request("findNotes", query="x"),
            {"action": "findNotes", "params": {"query": "x"}, "version": 6},
        )

    def test_get_notes_marks_the_query_and_joins_the_fields(self):
        """Every non-empty field is joined by a rule and the match is marked."""
        handler = self.make_handler()
        responses = {
            "findNotes": [1],
            "notesInfo": [{"noteId": 1, "fields": {"Front": {"value": "Hello world"}, "Empty": {"value": ""}}}],
        }
        handler.invoke = lambda action, **params: responses[action]
        self.assertEqual(handler.get_notes("hello"), [[1, "<mark>hello</mark> world"]])

    def test_search_runs_javascript_for_a_long_enough_query(self):
        """A three character ASCII query is searched and rendered."""
        handler = self.make_handler()
        handler.get_notes = lambda query: [[7, "card"]]
        result = handler.expanded_on_bridge_cmd("rev-search 3 hello")
        self.assertEqual(result, (True, None))
        self.assertEqual(handler.web_window.webview.page().scripts[-1], 'setTooltipSearchResults(3, [[7, "card"]])')

    def test_search_ignores_a_too_short_query(self):
        """A two character ASCII query does not reach Anki."""
        handler = self.make_handler()
        handler.get_notes = mock.Mock()
        handler.expanded_on_bridge_cmd("rev-search 3 ab")
        handler.get_notes.assert_not_called()

    def test_edit_opens_the_note_in_anki(self):
        """The edit command only calls AnkiConnect."""
        handler = self.make_handler()
        calls = []
        handler.invoke = lambda action, **params: calls.append((action, params))
        self.assertEqual(handler.expanded_on_bridge_cmd("rev-tt-edit 42"), (True, None))
        self.assertEqual(calls, [("guiEditNote", {"note": 42})])

    def test_dictionary_command_calls_emacs_with_the_words(self):
        """The words of the dictionary command reach the configured Emacs function."""
        handler = self.make_handler()
        calls = []
        handler.web_window.eval_in_emacs = lambda function, args: calls.append((function, args))
        handler.expanded_on_bridge_cmd("rev-tt-dictionary hello there")
        self.assertEqual(calls, [("popweb-dict-callback", ["hello", "there"])])

    def test_playsound_plays_every_sound_of_the_note(self):
        """The [sound:...] tags are resolved against the media directory."""
        handler = self.make_handler()
        handler.invoke = lambda action, **notes: {"notesInfo": "text [sound:one.mp3] [sound:two.mp3]"}
        played = []
        fake_playsound = types.ModuleType("playsound")
        fake_playsound.playsound = played.append
        with mock.patch.dict(sys.modules, {"playsound": fake_playsound}):
            result = handler.expanded_on_bridge_cmd("rev-tt-playsound 1")
        self.assertEqual(result, (True, None))
        self.assertEqual(played, ["/media/one.mp3", "/media/two.mp3"])


if __name__ == "__main__":
    unittest.main()
