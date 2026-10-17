#!/usr/bin/env python3
"""Tests for the application object that Emacs calls into.

An instance is built with `object.__new__` and only the attributes a method
needs, so the EPC server and the Qt application are never started.  Extension
modules are real files written to a temporary directory and loaded by the
production loader.
"""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test import fake_qt  # noqa: E402  (installs PyQt6 substitutes)

fake_qt.install()

from core import application, extension  # noqa: E402
from test.fake_qt import QNetworkProxy, QUrl, QWebEngineView  # noqa: E402

EXTENSION_SOURCE = """
class Handler:
    \"\"\"A slot class for the web channel test.\"\"\"

    def __init__(self, web_window, *args):
        \"\"\"Remember the window and the channel arguments.\"\"\"
        self.web_window = web_window
        self.args = args

    def cmd(self, value):
        \"\"\"Echo VALUE.\"\"\"
        return ("ok", value)


def hello(popweb, word):
    \"\"\"Record WORD on POPWEB.\"\"\"
    popweb.hello_word = word
"""


class FakeWindow:
    """The parts of a `WebWindow` that the application methods use."""

    def __init__(self):
        """Create a visible window with a fake view and developer tools."""
        self.webview = QWebEngineView()
        self.developer_tools_view = QWebEngineView()
        self.visible = True

    def hide(self):
        """Mark the window hidden."""
        self.visible = False


def make_app(tmp):
    """Return an application instance wired to a temporary module directory."""
    app = object.__new__(application.POPWEB)
    app.web_window_dict = {}
    app.module_dict = {}
    app.screen_size = fake_qt._Size(1920, 1080)
    app.proxy = ("", "", "")
    app.is_proxy = False
    return app


class ApplicationTest(unittest.TestCase):
    """Caching, extension loading, placement and the lifecycle calls."""

    def setUp(self):
        """Create a temporary directory and the application instance."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = make_app(self.tmp.name)
        self.module_path = str(Path(self.tmp.name) / "extension.py")
        Path(self.module_path).write_text(EXTENSION_SOURCE, encoding="utf-8")
        QNetworkProxy.application_proxy = None

    def test_get_web_window_creates_and_caches(self):
        """A window is created once per module name."""
        fake_window = FakeWindow()
        with mock.patch.object(application, "WebWindow", return_value=fake_window) as factory:
            first = self.app.get_web_window("dict_bing")
            second = self.app.get_web_window("dict_bing")
        self.assertIs(first, second)
        factory.assert_called_once_with(self.app.screen_size)

    def test_get_module_loads_and_caches(self):
        """A module is executed once per path."""
        with mock.patch.object(application.extension, "load_module", wraps=extension.load_module) as loader:
            first = self.app.get_module(self.module_path)
            second = self.app.get_module(self.module_path)
        self.assertIs(first, second)
        loader.assert_called_once_with(self.module_path)
        self.assertEqual(first.__name__, self.module_path)

    def test_call_module_method_prepends_the_application(self):
        """An extension function receives the application as its first argument."""
        self.app.call_module_method(self.module_path, "hello", ["world"])
        self.assertEqual(self.app.hello_word, "world")

    def test_call_module_method_passes_every_argument(self):
        """Arguments keep their order after the application object."""
        received = []

        module = types.ModuleType("probe")
        module.collect = lambda *args: received.append(args)
        self.app.module_dict[self.module_path] = module
        self.app.call_module_method(self.module_path, "collect", ["a", 1, "b"])
        self.assertEqual(received, [(self.app, "a", 1, "b")])

    def test_hide_web_window_hides_and_clears_the_page(self):
        """Hiding also loads a blank page and hides the developer tools."""
        window = FakeWindow()
        self.app.web_window_dict["dict_bing"] = window
        self.app.hide_web_window("dict_bing")
        self.assertFalse(window.visible)
        self.assertIsInstance(window.webview.url_value, QUrl)
        self.assertEqual(str(window.webview.url_value), "")
        self.assertFalse(window.developer_tools_view.isVisible())

    def test_hide_web_window_ignores_unknown_names(self):
        """A hide for a window that was never created is a no-op."""
        self.app.hide_web_window("missing")

    def test_build_web_channel_registers_the_handler(self):
        """The slot class is instantiated and registered under its JS name."""
        window = FakeWindow()
        with mock.patch.object(self.app, "get_web_window", return_value=window):
            self.app.build_web_channel(
                self.module_path, "anki_review", "handler", "Handler", "cmd", "media", "callback"
            )
        handler = window.webview.handler
        self.assertEqual(handler.args, ("media", "callback"))
        self.assertIs(window.webview.channel.objects["handler"], handler)
        self.assertIs(window.webview.page().web_channel, window.webview.channel)

    def test_build_web_channel_decorates_the_real_method(self):
        """The slot decorator is applied to the method name, not to a new attribute."""
        window = FakeWindow()
        with mock.patch.object(self.app, "get_web_window", return_value=window):
            self.app.build_web_channel(
                self.module_path, "anki_review", "handler", "Handler", "cmd", "media", "callback"
            )
        handler_class = type(window.webview.handler)
        self.assertFalse(hasattr(handler_class, "slot_method_name"))
        self.assertEqual(window.webview.handler.cmd("value"), ("ok", "value"))

    def test_adjust_render_pos_reads_the_option(self):
        """The method reads `popweb-popup-pos` and delegates the arithmetic."""
        with mock.patch.object(application, "get_emacs_var", return_value="top-left"):
            position = self.app.adjust_render_pos(500, 400, 0, 20, 200, 100, 100, 50, 1000, 800)
        self.assertEqual(position, (100, 50))

    def test_import_browser_cookies_copies_every_field(self):
        """A browser cookie becomes a Qt cookie with the same attributes."""
        browser = types.ModuleType("browser_cookie3")
        cookie = types.SimpleNamespace(
            name="session", value="abc", domain=".example.com", secure=True, path="/", expires=123
        )
        browser.chrome = lambda domain_name=None: [cookie]
        recorded = []

        with mock.patch.dict(sys.modules, {"browser_cookie3": browser}), mock.patch.object(
            application.CookiesManager, "add_cookie", side_effect=recorded.append
        ):
            self.app.import_browser_cookies("chrome", "example.com")

        self.assertEqual(len(recorded), 1)
        qt_cookie = recorded[0]
        self.assertEqual(qt_cookie.name().data(), b"session")
        self.assertEqual(qt_cookie.domain(), ".example.com")
        self.assertEqual(qt_cookie.path(), "/")
        self.assertEqual(qt_cookie.expiration.seconds, 123)

    def test_import_browser_cookies_maps_a_missing_expiry_to_zero(self):
        """A session cookie of the browser has no expiry and gets epoch zero."""
        browser = types.ModuleType("browser_cookie3")
        cookie = types.SimpleNamespace(
            name="n", value="v", domain="example.com", secure=False, path="/", expires=None
        )
        browser.firefox = lambda domain_name=None: [cookie]
        recorded = []

        with mock.patch.dict(sys.modules, {"browser_cookie3": browser}), mock.patch.object(
            application.CookiesManager, "add_cookie", side_effect=recorded.append
        ):
            self.app.import_browser_cookies("firefox", "example.com")

        self.assertEqual(recorded[0].expiration.seconds, 0)

    def test_import_browser_cookies_swallows_errors(self):
        """An unknown browser is reported, not raised into the EPC handler."""
        with mock.patch.object(application.traceback, "print_exc") as printer:
            self.app.import_browser_cookies("no-such-browser", "example.com")
        printer.assert_called_once()

    def test_cleanup_closes_the_client(self):
        """The cleanup method only closes the EPC client."""
        with mock.patch.object(application, "close_epc_client") as closer:
            self.app.cleanup()
        closer.assert_called_once()


class ProxyTest(unittest.TestCase):
    """The three proxy methods and the Qt proxy they install."""

    def setUp(self):
        """Create an application with an HTTP proxy configured."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = make_app(self.tmp.name)
        self.app.proxy = ("http", "127.0.0.1", "8080")
        QNetworkProxy.application_proxy = None

    def test_enable_proxy_sets_type_host_and_port(self):
        """The HTTP proxy is installed as the application proxy."""
        self.app.enable_proxy()
        installed = QNetworkProxy.application_proxy
        self.assertEqual(installed.proxy_type, QNetworkProxy.ProxyType.HttpProxy)
        self.assertEqual(installed.host, "127.0.0.1")
        self.assertEqual(installed.port, 8080)
        self.assertTrue(self.app.is_proxy)

    def test_enable_proxy_supports_socks5(self):
        """The SOCKS5 type is mapped to the Qt type of the same name."""
        self.app.proxy = ("socks5", "127.0.0.1", "1080")
        self.app.enable_proxy()
        self.assertEqual(QNetworkProxy.application_proxy.proxy_type, QNetworkProxy.ProxyType.Socks5Proxy)

    def test_disable_proxy_installs_no_proxy(self):
        """Disabling replaces the proxy with the explicit no-proxy value."""
        self.app.is_proxy = True
        self.app.disable_proxy()
        self.assertEqual(QNetworkProxy.application_proxy.proxy_type, QNetworkProxy.ProxyType.NoProxy)
        self.assertFalse(self.app.is_proxy)

    def test_toggle_proxy_flips_the_state(self):
        """Toggling twice comes back to the starting state."""
        self.app.toggle_proxy()
        self.assertTrue(self.app.is_proxy)
        self.app.toggle_proxy()
        self.assertFalse(self.app.is_proxy)


if __name__ == "__main__":
    unittest.main()
