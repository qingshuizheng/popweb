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
from typing import Any, Optional, Tuple

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

RESIZE_MARGIN = 8
"""Pixels from an edge that start a drag-resize of the popup."""

MIN_WINDOW_WIDTH = 160
"""Smallest width a popup can be dragged to."""

MIN_WINDOW_HEIGHT = 100
"""Smallest height a popup can be dragged to."""


def resize_edges(
    x: float, y: float, width: float, height: float, margin: float = RESIZE_MARGIN
) -> Tuple[bool, bool, bool, bool]:
    """Return the window edges that the point (X, Y) is close enough to grab.

    The result is (LEFT, TOP, RIGHT, BOTTOM).  A point in the middle of the
    window, or one that is not in a WIDTH by HEIGHT window at all, has all
    four flags nil.
    """
    return (x <= margin, y <= margin, x >= width - margin, y >= height - margin)


def resized_geometry(
    x: float,
    y: float,
    width: float,
    height: float,
    dx: float,
    dy: float,
    edges: Tuple[bool, bool, bool, bool],
) -> Tuple[int, int, int, int]:
    """Return the geometry after dragging EDGES by DX and DY.

    EDGES comes from `resize_edges'.  A left or top edge moves the origin as
    it resizes, so the opposite edge stays where it was; a right or bottom
    edge only changes the size.  The result never goes below
    `MIN_WINDOW_WIDTH' or `MIN_WINDOW_HEIGHT'.
    """
    left, top, right, bottom = edges
    new_x, new_y, new_width, new_height = x, y, width, height

    if left:
        new_x = x + dx
        new_width = width - dx
    elif right:
        new_width = width + dx
    if top:
        new_y = y + dy
        new_height = height - dy
    elif bottom:
        new_height = height + dy

    if new_width < MIN_WINDOW_WIDTH:
        if left:
            new_x = x + width - MIN_WINDOW_WIDTH
        new_width = MIN_WINDOW_WIDTH
    if new_height < MIN_WINDOW_HEIGHT:
        if top:
            new_y = y + height - MIN_WINDOW_HEIGHT
        new_height = MIN_WINDOW_HEIGHT

    return int(new_x), int(new_y), int(new_width), int(new_height)


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

        # A size the user dragged wins over the size an extension computes;
        # `forget_user_size' gives control back to the extension.
        self.user_size: Optional[Tuple[int, int]] = None
        self._resize_edges: Optional[Tuple[bool, bool, bool, bool]] = None
        self._resize_start: Any = None
        self._resize_start_geometry: Any = None
        self._cursor_widget: Any = None

        # The web view renders into a child widget, which receives the mouse
        # events; the application-wide filter is what sees them on every
        # platform.  The direct filter covers a plain QWebEngineView.
        self.webview.installEventFilter(self)
        for tracked_widget in (self.webview, self.webview.focusProxy()):
            if tracked_widget is not None:
                tracked_widget.setMouseTracking(True)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

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

    def resize(self, width: int, height: int) -> None:
        """Resize the window, unless the user dragged it to a size of their own.

        A dragged size is remembered per window (one window per extension
        module), so the next popup of the same module keeps it.  Extensions
        still call `resize' with the size they computed; this override is
        where the user's choice wins.  `forget_user_size' removes it.
        """
        if self.user_size is not None:
            width, height = self.user_size
        super().resize(int(width), int(height))

    def resize_to_fit(self, width: int, height: int) -> None:
        """Resize to at least WIDTH by HEIGHT, keeping a larger dragged size.

        This is for a popup whose size depends on its content, such as the
        LaTeX preview: a formula that needs more room grows the window even
        after the user dragged it, while a smaller formula keeps the dragged
        size instead of clipping.
        """
        width, height = int(width), int(height)
        if self.user_size is not None:
            width = max(width, self.user_size[0])
            height = max(height, self.user_size[1])
            self.user_size = (width, height)
        super().resize(width, height)

    def forget_user_size(self) -> None:
        """Forget the size set by dragging, so extensions size the popup again."""
        self.user_size = None

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Resize the frameless window when the user drags one of its edges.

        The filter is installed on the web view and on the application, so it
        sees the events that the web engine delivers to its internal render
        widget.  An event outside this window, or one that does not start on
        an edge, is left to Qt and to the page.
        """
        if not isinstance(watched, QWidget):
            return False
        if watched is not self and watched.window() is not self:
            return False

        event_type = event.type()
        if event_type == QtCore.QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            x, y = self._mouse_point(watched, event)
            edges = resize_edges(x, y, self.width(), self.height())
            if any(edges):
                self._resize_edges = edges
                self._resize_start = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                return True
        elif event_type == QtCore.QEvent.Type.MouseMove:
            x, y = self._mouse_point(watched, event)
            if self._resize_edges is None:
                self._update_resize_cursor(watched, x, y)
            else:
                point = event.globalPosition().toPoint()
                dx = point.x() - self._resize_start.x()
                dy = point.y() - self._resize_start.y()
                geometry = self._resize_start_geometry
                super().setGeometry(
                    *resized_geometry(
                        geometry.x(),
                        geometry.y(),
                        geometry.width(),
                        geometry.height(),
                        dx,
                        dy,
                        self._resize_edges,
                    )
                )
                return True
        elif event_type == QtCore.QEvent.Type.MouseButtonRelease:
            if self._resize_edges is not None:
                self.user_size = (self.width(), self.height())
                self._resize_edges = None
                self._resize_start = None
                self._resize_start_geometry = None
                return True
        return False

    def _mouse_point(self, watched: Any, event: Any) -> Tuple[int, int]:
        """Return the event position in the window's coordinates."""
        point = event.position().toPoint()
        if watched is not self:
            point = watched.mapTo(self, point)
        return int(point.x()), int(point.y())

    def _update_resize_cursor(self, watched: Any, x: int, y: int) -> None:
        """Show the resize cursor when (X, Y) is on an edge, and clear it after."""
        left, top, right, bottom = resize_edges(x, y, self.width(), self.height())
        if (left and top) or (right and bottom):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif (left and bottom) or (right and top):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif left or right:
            shape = Qt.CursorShape.SizeHorCursor
        elif top or bottom:
            shape = Qt.CursorShape.SizeVerCursor
        else:
            shape = None

        if shape is not None:
            if self._cursor_widget is not None and self._cursor_widget is not watched:
                self._cursor_widget.unsetCursor()
            watched.setCursor(shape)
            self._cursor_widget = watched
        elif self._cursor_widget is not None:
            self._cursor_widget.unsetCursor()
            self._cursor_widget = None

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
