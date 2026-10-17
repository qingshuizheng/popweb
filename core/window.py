"""The Qt window that shows a popup, and the page inside it.

`WebWindow` is a frameless, always-on-top window with one `QWebEngineView`.
The page is a normal browser page, so an extension only has to say what to
load and which JavaScript to run after the load; it never touches Qt itself.

`PostGui` is the thread bridge: the EPC server runs on a worker thread, while
Qt insists that widget calls happen on the GUI thread.  A decorated method
emits a signal instead of running, and the slot runs it on the GUI thread.

The dark mode support is a vendored copy of Dark Reader (`darkreader.js`),
injected into a page the first time a dark theme is used.
"""

from __future__ import annotations

import functools
import os
import platform
import traceback
from typing import Any

# NOTE: QtWebEngineWidgets must be imported before a QCoreApplication instance
# is created, which is why this import comes before any other PyQt6 import.
from PyQt6.QtWebEngineWidgets import QWebEngineView

from PyQt6 import QtCore
from PyQt6.QtCore import QEventLoop, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from .bridge import eval_in_emacs, get_emacs_func_result, get_emacs_var
from .cookies import CookiesManager

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""Directory of popweb.py, which is also where darkreader.js lives."""


class PostGui(QtCore.QObject):
    """Decorator that runs a method on the Qt GUI thread.

    Decorate a `WebWindow` or `POPWEB` method with `@PostGui()` when it
    touches widgets but is called from the EPC worker thread.  The wrapper
    emits `through_thread' with the arguments, and the connected slot calls
    the original method on the thread that owns the object.
    """

    through_thread = QtCore.pyqtSignal(object, object)

    def __init__(self, inclass: bool = True) -> None:
        """Create the bridge.

        INCLASS says whether the decorated callable is a method: when it is,
        the first argument of the emitted signal is the object to call, and
        the rest are the method arguments.
        """
        super().__init__()
        self.through_thread.connect(self.on_signal_received)
        self.inclass = inclass

    def __call__(self, func: Any) -> Any:
        """Wrap FUNC so that calling it schedules it on the GUI thread."""
        self._func = func

        @functools.wraps(func)
        def obj_call(*args: Any, **kwargs: Any) -> None:
            """Emit the signal that runs FUNC on the GUI thread."""
            self.emit_signal(args, kwargs)

        return obj_call

    def emit_signal(self, args: tuple, kwargs: dict) -> None:
        """Emit the signal that carries ARGS and KWARGS to the GUI thread."""
        self.through_thread.emit(args, kwargs)

    def on_signal_received(self, args: tuple, kwargs: dict) -> None:
        """Run the wrapped function with ARGS and KWARGS on the GUI thread."""
        if self.inclass:
            obj, args = args[0], args[1:]
            self._func(obj, *args, **kwargs)
        else:
            self._func(*args, **kwargs)


class WebView(QWebEngineView):
    """A web view that remembers its cookies through `CookiesManager'."""

    def __init__(self) -> None:
        """Create the view and attach a cookie manager to it."""
        super().__init__()
        self.cookies_manager = CookiesManager(self)


class BrowserPage(QWebEnginePage):
    """A page whose JavaScript can be run synchronously.

    Qt only offers `runJavaScript' with a callback.  `execute_javascript'
    turns that into a blocking call by running a nested event loop, which is
    what the LaTeX and colour-picker extensions need to size their window from
    the rendered content.
    """

    def __init__(self) -> None:
        """Create an empty page."""
        QWebEnginePage.__init__(self)

    def execute_javascript(self, script_src: str) -> Any:
        """Run SCRIPT_SRC in the page and return its value.

        The call blocks until the page reports the result, so it must not be
        used from inside a Qt signal handler that the page is waiting on.
        """
        self.loop = QEventLoop()

        self.runJavaScript(script_src, self.callback_js)

        self.loop.exec()

        return self.result

    def callback_js(self, result: Any) -> None:
        """Store the JavaScript RESULT and leave the nested event loop."""
        self.result = result
        self.loop.quit()


class WebWindow(QWidget):
    """The frameless popup window and the web page shown in it."""

    def __init__(self, screen_size: Any = None) -> None:
        """Create the window for a screen of SCREEN_SIZE.

        SCREEN_SIZE is the primary screen's size; it is read from the running
        application when it is nil.  A screen wider than 3000 pixels gets twice
        the configured zoom factor, which is what keeps a popup readable on a
        4K display without a second option.
        """
        super().__init__()

        if screen_size is None:
            screen_size = QApplication.instance().primaryScreen().size()

        if platform.system() == "Windows":
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.ToolTip
            )
        self.setContentsMargins(0, 0, 0, 0)

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(0, 0, 0, 0)

        self.zoom_factor = get_emacs_var("popweb-zoom-factor")
        if screen_size.width() > 3000:
            self.zoom_factor = self.zoom_factor * 2

        self.loading_js_code = ""
        self.js_file_code = ""
        self.js_file_code_args = None
        self.load_finish_callback = None

        with open(os.path.join(PACKAGE_DIR, "darkreader.js")) as darkreader_file:
            self.dark_mode_js = darkreader_file.read()

        self.update_theme_mode()
        self.webview = WebView()
        self.web_page = BrowserPage()
        self.webview.setPage(self.web_page)
        self.web_page.setBackgroundColor(
            QColor(get_emacs_func_result("popweb-get-theme-background", []))
        )

        self.developer_tools_view = QWebEngineView()
        self.developer_tools_view.setZoomFactor(self.zoom_factor)
        screen = QApplication.instance().primaryScreen()
        self.developer_tools_view.resize(
            int(screen.size().width() / 2), int(screen.size().height() / 2)
        )

        self.webview.loadStarted.connect(lambda: self.reset_zoom())
        self.webview.loadProgress.connect(lambda: self.execute_loading_js_code())
        self.webview.loadFinished.connect(self.execute_load_finish_js_code)
        self.reset_zoom()

        self.vbox.addWidget(self.webview)
        self.setLayout(self.vbox)

        self.webview.installEventFilter(self)

        self.settings = self.webview.settings()
        try:
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.AllowGeolocationOnInsecureOrigins, True)
            self.settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        except Exception:
            traceback.print_exc()

    def popup(self) -> None:
        """Show the window, and the developer tools when they are enabled."""
        self.show()

        enable_developer_tools = get_emacs_var("popweb-enable-developer-tools")
        if enable_developer_tools:
            self.web_page.setDevToolsPage(self.developer_tools_view.page())
            self.developer_tools_view.show()

    def reset_zoom(self) -> None:
        """Apply `zoom_factor' to the web view."""
        self.webview.setZoomFactor(self.zoom_factor)

    def update_theme_mode(self) -> None:
        """Read the Emacs theme mode into `theme_mode'."""
        self.theme_mode = get_emacs_func_result("popweb-get-theme-mode", [])

    def execute_loading_js_code(self) -> None:
        """Run the per-page loading JavaScript, and enable dark mode if needed.

        This is connected to the load progress signal, so it runs repeatedly
        while a page loads; the extension sets `loading_js_code' to the snippet
        that trims the page, and an empty string keeps the page untouched.
        """
        if self.loading_js_code != "":
            self.webview.page().runJavaScript(self.loading_js_code)

        if self.theme_mode == "dark":
            self.load_dark_mode_js()
            self.enable_dark_mode()

    def execute_load_finish_js_code(self) -> None:
        """Run the JavaScript that must wait for the page to be complete.

        `js_file_code' is the optional content of a JavaScript file that the
        extension asks Python to read, and `js_file_code_args' is appended as
        the argument list of its call.  `load_finish_callback', when set, runs
        after the snippet.
        """
        if self.js_file_code != "":
            js_code = self.js_file_code + "({0});".format(str(self.js_file_code_args or ""))
            self.webview.page().runJavaScript(js_code)
        if self.load_finish_callback is not None:
            self.load_finish_callback()

    def load_dark_mode_js(self) -> None:
        """Inject Dark Reader into the page once, if it is not there yet."""
        self.webview.page().runJavaScript(
            """if (typeof DarkReader === 'undefined') {{ {} }} """.format(self.dark_mode_js)
        )

    def enable_dark_mode(self) -> None:
        """Turn Dark Reader on with the values popweb has always used."""
        self.webview.page().runJavaScript(
            "DarkReader.setFetchMethod(window.fetch); "
            "DarkReader.enable({brightness: 100, contrast: 90, sepia: 10});"
        )

    def disable_dark_mode(self) -> None:
        """Turn Dark Reader off."""
        self.webview.page().runJavaScript("""DarkReader.disable();""")

    def eval_in_emacs(self, method_name: str, args: list) -> None:
        """Call the Emacs function METHOD_NAME with ARGS.

        The Anki extension receives the function name as a string and calls it
        with the words of a dictionary query, which is why ARGS is a list and
        not a single value.
        """
        eval_in_emacs(method_name, args)
