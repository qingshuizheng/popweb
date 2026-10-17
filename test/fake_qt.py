"""A small stand-in for PyQt6, so the Python tests run without Qt installed.

The production code imports PyQt6 at module level, which is the right thing to
do in a program that always has it.  A test machine does not, and installing a
browser engine just to check arithmetic is not reasonable, so this module
builds the handful of classes the code touches and registers them under the
real module names.

Only the operations popweb performs are implemented, and every one of them is
observable: a widget remembers where it was moved, a page remembers which
script ran, a cookie store remembers which cookie was set.  That is enough for
the tests to assert what the code would have done with real Qt.

Call `install()` before importing `core.window` or `core.application`.  The
call is idempotent, so several test modules can each call it.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Callable, List, Optional
from urllib.parse import urlparse


class _Signal:
    """A signal that calls its connected slots synchronously when emitted."""

    def __init__(self) -> None:
        """Create a signal with no slots."""
        self.slots: List[Callable] = []

    def connect(self, slot: Callable) -> None:
        """Call SLOT on every emit."""
        self.slots.append(slot)

    def disconnect(self, slot: Optional[Callable] = None) -> None:
        """Forget SLOT, or every slot when SLOT is nil."""
        if slot is None:
            self.slots.clear()
        elif slot in self.slots:
            self.slots.remove(slot)

    def emit(self, *args: Any) -> None:
        """Call every connected slot with ARGS."""
        for slot in list(self.slots):
            slot(*args)


class _SignalDescriptor:
    """Descriptor that gives every instance of a QObject its own signal."""

    def __init__(self) -> None:
        """Create a descriptor that has not been bound to a class yet."""
        self.attr = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """Remember the attribute name the descriptor was assigned to."""
        self.attr = "_signal_" + name

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        """Return the signal of OBJ, creating it on first access."""
        if obj is None:
            return self
        if self.attr not in obj.__dict__:
            obj.__dict__[self.attr] = _Signal()
        return obj.__dict__[self.attr]


def pyqtSignal(*args: Any, **kwargs: Any) -> _SignalDescriptor:
    """Return a signal descriptor; the signatures are not validated."""
    return _SignalDescriptor()


def pyqtSlot(*args: Any, **kwargs: Any) -> Callable[[Callable], Callable]:
    """Return a decorator that leaves the decorated method unchanged."""

    def decorate(func: Callable) -> Callable:
        return func

    return decorate


class QObject:
    """Base class that accepts and ignores constructor arguments."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Ignore ARGS and KWARGS, like the real base class does with a parent."""
        self.event_filter = None

    def installEventFilter(self, event_filter: Any) -> None:
        """Remember EVENT_FILTER; the fake never calls it."""
        self.event_filter = event_filter


class QVariant:
    """Placeholder for the Qt value wrapper; any value is accepted."""

    def __init__(self, value: Any = None) -> None:
        """Store VALUE."""
        self.value = value


class QEventLoop:
    """Event loop whose exec is synchronous, because the fake page is too."""

    def exec(self) -> int:
        """Return 0 immediately."""
        return 0

    def quit(self) -> None:
        """Do nothing."""
        pass


class QUrl:
    """URL wrapper that can report its host, which is all the code uses."""

    def __init__(self, url: str = "") -> None:
        """Store URL."""
        self._url = url

    def host(self) -> str:
        """Return the host name of the URL, or the empty string."""
        url = str(self._url)
        if not url:
            return ""
        if "://" not in url:
            url = "file://" + url
        return urlparse(url).hostname or ""

    def __str__(self) -> str:
        """Return the URL as it was given."""
        return str(self._url)

    def toString(self) -> str:
        """Return the URL as it was given."""
        return str(self._url)


class _Size:
    """Screen size with the two accessors the code calls."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        """Store WIDTH and HEIGHT."""
        self._width = width
        self._height = height

    def width(self) -> int:
        """Return the width in pixels."""
        return self._width

    def height(self) -> int:
        """Return the height in pixels."""
        return self._height


class _Screen:
    """Screen that reports a fixed size."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        """Create a screen of WIDTH by HEIGHT pixels."""
        self._size = _Size(width, height)

    def size(self) -> _Size:
        """Return the screen size."""
        return self._size


class _Point:
    """Point with the two accessors Qt code uses."""

    def __init__(self, x: int = 0, y: int = 0) -> None:
        """Store X and Y."""
        self._x = x
        self._y = y

    def x(self) -> int:
        """Return the x coordinate."""
        return self._x

    def y(self) -> int:
        """Return the y coordinate."""
        return self._y

    def toPoint(self) -> "_Point":
        """Return a copy, like QPointF.toPoint."""
        return _Point(self._x, self._y)


class _Rect:
    """Rectangle with the four accessors geometry() returns."""

    def __init__(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> None:
        """Store the rectangle."""
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def x(self) -> int:
        """Return the left edge."""
        return self._x

    def y(self) -> int:
        """Return the top edge."""
        return self._y

    def width(self) -> int:
        """Return the width."""
        return self._width

    def height(self) -> int:
        """Return the height."""
        return self._height


class QWidget(QObject):
    """Widget that records its geometry, visibility and window flags."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a hidden widget at (0, 0) with size (0, 0)."""
        super().__init__()
        self._visible = False
        self._position = (0, 0)
        self._size = (0, 0)
        self.window_flags = 0
        self.margins = None
        self.layout_obj = None
        self.event_filter = None
        self.mouse_tracking = False
        self.cursor = None

    def setWindowFlags(self, flags: int) -> None:
        """Remember FLAGS."""
        self.window_flags = flags

    def setContentsMargins(self, left: int, top: int, right: int, bottom: int) -> None:
        """Remember the margins as a tuple."""
        self.margins = (left, top, right, bottom)

    def setLayout(self, layout: Any) -> None:
        """Remember LAYOUT."""
        self.layout_obj = layout

    def resize(self, width: int, height: int) -> None:
        """Remember the new size."""
        self._size = (width, height)

    def move(self, x: int, y: int) -> None:
        """Remember the new position."""
        self._position = (x, y)

    def setGeometry(self, x: int, y: int, width: int, height: int) -> None:
        """Remember the new position and size."""
        self._position = (x, y)
        self._size = (width, height)

    def geometry(self) -> _Rect:
        """Return the recorded geometry."""
        return _Rect(self._position[0], self._position[1], self._size[0], self._size[1])

    def width(self) -> int:
        """Return the recorded width."""
        return self._size[0]

    def height(self) -> int:
        """Return the recorded height."""
        return self._size[1]

    def mapTo(self, parent: Any, point: _Point) -> _Point:
        """Return POINT unchanged; the fake has no nested widgets."""
        return point

    def window(self) -> "QWidget":
        """Return the top level widget, which is this one in the fake."""
        return self

    def setMouseTracking(self, enabled: bool) -> None:
        """Remember whether mouse tracking is on."""
        self.mouse_tracking = enabled

    def setCursor(self, shape: Any) -> None:
        """Remember the cursor shape."""
        self.cursor = shape

    def unsetCursor(self) -> None:
        """Forget the cursor shape."""
        self.cursor = None

    def show(self) -> None:
        """Mark the widget visible."""
        self._visible = True

    def hide(self) -> None:
        """Mark the widget hidden."""
        self._visible = False

    def isVisible(self) -> bool:
        """Return whether the widget is visible."""
        return self._visible

    def installEventFilter(self, event_filter: Any) -> None:
        """Remember EVENT_FILTER."""
        self.event_filter = event_filter


class QWebEngineSettings:
    """Settings object that records every attribute it is given."""

    class WebAttribute:
        """The attributes popweb sets; the values only have to be distinct."""

        FullScreenSupportEnabled = "FullScreenSupportEnabled"
        DnsPrefetchEnabled = "DnsPrefetchEnabled"
        FocusOnNavigationEnabled = "FocusOnNavigationEnabled"
        PlaybackRequiresUserGesture = "PlaybackRequiresUserGesture"
        PluginsEnabled = "PluginsEnabled"
        JavascriptEnabled = "JavascriptEnabled"
        LocalContentCanAccessRemoteUrls = "LocalContentCanAccessRemoteUrls"
        LocalContentCanAccessFileUrls = "LocalContentCanAccessFileUrls"
        AllowRunningInsecureContent = "AllowRunningInsecureContent"
        AllowGeolocationOnInsecureOrigins = "AllowGeolocationOnInsecureOrigins"
        ShowScrollBars = "ShowScrollBars"

    def __init__(self) -> None:
        """Create an empty settings object."""
        self.attributes = {}

    def setAttribute(self, attribute: Any, value: Any) -> None:
        """Remember VALUE for ATTRIBUTE."""
        self.attributes[attribute] = value


class _CookieStore:
    """Cookie store that keeps the operations the manager performs."""

    def __init__(self) -> None:
        """Create an empty store with the two signals the manager connects."""
        self.cookieAdded = _Signal()
        self.cookieRemoved = _Signal()
        self.cookies: List[Any] = []

    def setCookie(self, cookie: Any, url: Any = None) -> None:
        """Remember COOKIE, and the URL it belongs to."""
        self.cookies.append((cookie, url))

    def deleteCookie(self, cookie: Any) -> None:
        """Forget COOKIE."""
        self.cookies = [item for item in self.cookies if item[0] is not cookie]

    def deleteAllCookies(self) -> None:
        """Forget every cookie."""
        self.cookies.clear()


class QWebEngineProfile:
    """Profile with an in-memory cookie store."""

    class PersistentCookiesPolicy:
        """The policy values the manager compares itself against."""

        NoPersistentCookies = 0

    def __init__(self) -> None:
        """Create a profile with an empty cookie store."""
        self._cookie_store = _CookieStore()
        self.persistent_cookies_policy = None

    def cookieStore(self) -> _CookieStore:
        """Return the cookie store."""
        return self._cookie_store

    def setPersistentCookiesPolicy(self, policy: Any) -> None:
        """Remember POLICY."""
        self.persistent_cookies_policy = policy


class QWebEnginePage(QObject):
    """Page that records scripts, background colour, devtools and channel."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create an empty page with a profile and a result queue."""
        super().__init__()
        self.scripts: List[str] = []
        self.js_results: List[Any] = []
        self.background_color = None
        self.dev_tools_page = None
        self.web_channel = None
        self._profile = QWebEngineProfile()
        self._view = None

    def profile(self) -> QWebEngineProfile:
        """Return the profile that owns the cookie store."""
        return self._profile

    def runJavaScript(self, script: str, callback: Optional[Callable] = None) -> None:
        """Remember SCRIPT and call CALLBACK with the next queued result."""
        self.scripts.append(script)
        if callback is not None:
            result = self.js_results.pop(0) if self.js_results else None
            callback(result)

    def setBackgroundColor(self, color: Any) -> None:
        """Remember COLOR."""
        self.background_color = color

    def setDevToolsPage(self, page: Any) -> None:
        """Remember PAGE."""
        self.dev_tools_page = page

    def setWebChannel(self, channel: Any) -> None:
        """Remember CHANNEL."""
        self.web_channel = channel


class QWebEngineView(QWidget):
    """View that records its page, URL, HTML, zoom and settings."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create an empty view with the three load signals connected."""
        super().__init__()
        self._page: Optional[QWebEnginePage] = QWebEnginePage()
        self.url_value: Any = None
        self.html: Optional[str] = None
        self.zoom_factor = 1.0
        self._settings = QWebEngineSettings()
        self.loadStarted = _Signal()
        self.loadProgress = _Signal()
        self.loadFinished = _Signal()
        self.channel = None
        self.handler = None

    def setPage(self, page: QWebEnginePage) -> None:
        """Use PAGE and remember this view on it."""
        self._page = page
        page._view = self

    def page(self) -> QWebEnginePage:
        """Return the current page."""
        return self._page

    def load(self, url: Any) -> None:
        """Remember URL as the last loaded URL."""
        self.url_value = url

    def setUrl(self, url: Any) -> None:
        """Remember URL as the last loaded URL."""
        self.url_value = url

    def url(self) -> Any:
        """Return the last URL, or an empty QUrl."""
        return self.url_value if self.url_value is not None else QUrl("")

    def setHtml(self, html: str, base_url: Any = None) -> None:
        """Remember HTML and its base URL."""
        self.html = html
        self.url_value = base_url

    def settings(self) -> QWebEngineSettings:
        """Return the settings object."""
        return self._settings

    def focusProxy(self) -> Any:
        """Return no focus proxy, like a view before one is created."""
        return None

    def setZoomFactor(self, factor: float) -> None:
        """Remember FACTOR."""
        self.zoom_factor = factor


class QWebChannel(QObject):
    """Channel that records the objects registered on it."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create an empty channel."""
        super().__init__()
        self.objects = {}

    def registerObject(self, name: str, obj: Any) -> None:
        """Remember OBJ under NAME."""
        self.objects[name] = obj


class QVBoxLayout(QObject):
    """Layout that records the widgets added to it."""

    def __init__(self, parent: Any = None) -> None:
        """Create a layout for PARENT."""
        super().__init__()
        self.parent = parent
        self.widgets: List[Any] = []
        self.margins = None

    def setContentsMargins(self, left: int, top: int, right: int, bottom: int) -> None:
        """Remember the margins as a tuple."""
        self.margins = (left, top, right, bottom)

    def addWidget(self, widget: Any) -> None:
        """Remember WIDGET."""
        self.widgets.append(widget)


class QApplication(QObject):
    """Application singleton that reports a fixed primary screen."""

    _instance: Optional["QApplication"] = None
    screen_width = 1920
    screen_height = 1080
    exit_code = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Become the singleton and ignore the arguments."""
        super().__init__()
        QApplication._instance = self

    @classmethod
    def instance(cls) -> "QApplication":
        """Return the singleton, creating a default one when needed."""
        if cls._instance is None:
            cls._instance = cls([])
        return cls._instance

    def primaryScreen(self) -> _Screen:
        """Return the primary screen."""
        return _Screen(QApplication.screen_width, QApplication.screen_height)

    def exec(self) -> int:
        """Return the stored exit code."""
        return QApplication.exit_code


class QColor:
    """Colour that stores its value."""

    def __init__(self, value: Any = None) -> None:
        """Store VALUE."""
        self.value = value


class QDateTime:
    """Date time with the one constructor popweb calls."""

    def __init__(self, seconds: int = 0) -> None:
        """Store SECONDS since the epoch."""
        self.seconds = seconds

    @classmethod
    def fromSecsSinceEpoch(cls, seconds: int) -> "QDateTime":
        """Return a date time at SECONDS since the epoch."""
        return cls(seconds)


class QTimer(QObject):
    """Timer whose single shot runs immediately, so tests stay synchronous."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a timer; the parent argument is ignored."""
        super().__init__()

    def singleShot(self, milliseconds: int, callback: Callable) -> None:
        """Call CALLBACK without waiting MILLISECONDS."""
        callback()


class _CookieName:
    """The byte container that `QNetworkCookie.name' returns."""

    def __init__(self, name: Any) -> None:
        """Store NAME as bytes."""
        if isinstance(name, bytes):
            self._bytes = name
        else:
            self._bytes = str(name).encode()

    def data(self) -> bytes:
        """Return the bytes of the name."""
        return self._bytes


class QNetworkCookie:
    """Cookie that can write and read the raw form the manager stores."""

    def __init__(self, name: Any = b"", value: Any = b"") -> None:
        """Create a cookie called NAME with VALUE."""
        self._name = name
        self._value = value
        self._domain = ""
        self._path = "/"
        self._session = False
        self._secure = False
        self.expiration: Optional[QDateTime] = None

    def name(self) -> _CookieName:
        """Return the name as a byte container."""
        return _CookieName(self._name)

    def value(self) -> _CookieName:
        """Return the value as a byte container."""
        return _CookieName(self._value)

    def domain(self) -> str:
        """Return the domain."""
        return self._domain

    def setDomain(self, domain: str) -> None:
        """Set the domain."""
        self._domain = domain

    def path(self) -> str:
        """Return the path."""
        return self._path

    def setPath(self, path: str) -> None:
        """Set the path."""
        self._path = path

    def setSecure(self, secure: bool) -> None:
        """Set whether the cookie is secure."""
        self._secure = secure

    def setExpirationDate(self, expiration: QDateTime) -> None:
        """Set the expiry date."""
        self.expiration = expiration

    def isSessionCookie(self) -> bool:
        """Return whether the cookie is a session cookie."""
        return self._session

    def setSessionCookie(self, session: bool) -> None:
        """Set whether the cookie is a session cookie."""
        self._session = session

    def toRawForm(self) -> bytes:
        """Return the raw form that `parseCookies' can read back."""
        return "{0}={1}; domain={2}; path={3}; session={4}".format(
            self._name.decode() if isinstance(self._name, bytes) else self._name,
            self._value.decode() if isinstance(self._value, bytes) else self._value,
            self._domain,
            self._path,
            int(self._session),
        ).encode()

    @classmethod
    def parseCookies(cls, raw: bytes) -> List["QNetworkCookie"]:
        """Return the cookies stored in RAW.

        Only the fields of `toRawForm' are understood, which is all the tests
        need; the real Qt parser understands every RFC 6265 attribute.
        """
        text = raw.decode()
        if "=" not in text:
            return []
        name, _, rest = text.partition("=")
        value, _, attributes = rest.partition(";")
        cookie = cls(name.encode(), value.encode())
        for attribute in attributes.split(";"):
            attribute = attribute.strip()
            key, _, val = attribute.partition("=")
            if key == "domain":
                cookie.setDomain(val)
            elif key == "path":
                cookie.setPath(val)
            elif key == "session":
                cookie.setSessionCookie(val == "1")
        return [cookie]


class _ProxyType:
    """The proxy type constants used by the application."""

    Socks5Proxy = "socks5"
    HttpProxy = "http"
    NoProxy = "none"


class QNetworkProxy:
    """Proxy that records its type, host and port."""

    ProxyType = _ProxyType
    application_proxy: Optional["QNetworkProxy"] = None

    def __init__(self) -> None:
        """Create a proxy without a type."""
        self.proxy_type = None
        self.host = ""
        self.port = 0

    def setType(self, proxy_type: Any) -> None:
        """Remember PROXY_TYPE."""
        self.proxy_type = proxy_type

    def setHostName(self, host: str) -> None:
        """Remember HOST."""
        self.host = host

    def setPort(self, port: int) -> None:
        """Remember PORT."""
        self.port = port

    @classmethod
    def setApplicationProxy(cls, proxy: "QNetworkProxy") -> None:
        """Remember PROXY as the application proxy."""
        cls.application_proxy = proxy


class QNetworkProxyFactory:
    """Factory that remembers whether the system proxy is used."""

    use_system_configuration = True

    @classmethod
    def setUseSystemConfiguration(cls, use: bool) -> None:
        """Remember USE."""
        cls.use_system_configuration = use


class _Qt:
    """Namespace for the Qt constants, grouped as the real module groups them."""

    class WindowType:
        """Window flags; the values only have to be combinable."""

        FramelessWindowHint = 1
        WindowStaysOnTopHint = 2
        Tool = 4
        WindowDoesNotAcceptFocus = 8
        ToolTip = 16

    class MouseButton:
        """The mouse buttons the window filter compares against."""

        LeftButton = "left"
        RightButton = "right"

    class CursorShape:
        """The cursor shapes used for the resize edges."""

        ArrowCursor = "arrow"
        SizeHorCursor = "size-horizontal"
        SizeVerCursor = "size-vertical"
        SizeFDiagCursor = "size-diagonal"
        SizeBDiagCursor = "size-back-diagonal"


class QEvent:
    """Event types the window filter reacts to."""

    class Type:
        """The subset of event types popweb handles."""

        MouseButtonPress = "mouse-press"
        MouseButtonRelease = "mouse-release"
        MouseButtonDblClick = "mouse-double-click"
        MouseMove = "mouse-move"


def _module(name: str, **attributes: Any) -> types.ModuleType:
    """Create a module called NAME with ATTRIBUTES."""
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def install() -> None:
    """Register the stand-in modules under the PyQt6 names.

    Importing this function twice is harmless, and a real PyQt6 installation is
    left alone: the fake only fills in names that are not already present.
    """
    existing = sys.modules.get("PyQt6")
    if existing is not None:
        if getattr(existing, "__is_fake__", False):
            return
        raise RuntimeError("call fake_qt.install() before importing the real PyQt6")

    qtcore = _module(
        "PyQt6.QtCore",
        QObject=QObject,
        pyqtSignal=pyqtSignal,
        pyqtSlot=pyqtSlot,
        QVariant=QVariant,
        QEventLoop=QEventLoop,
        QUrl=QUrl,
        Qt=_Qt,
        QEvent=QEvent,
        QDateTime=QDateTime,
        QTimer=QTimer,
    )
    qtgui = _module("PyQt6.QtGui", QColor=QColor)
    qtnetwork = _module(
        "PyQt6.QtNetwork",
        QNetworkCookie=QNetworkCookie,
        QNetworkProxy=QNetworkProxy,
        QNetworkProxyFactory=QNetworkProxyFactory,
    )
    qtwebenginecore = _module(
        "PyQt6.QtWebEngineCore",
        QWebEnginePage=QWebEnginePage,
        QWebEngineSettings=QWebEngineSettings,
        QWebEngineProfile=QWebEngineProfile,
    )
    qtwidgets = _module(
        "PyQt6.QtWidgets",
        QWidget=QWidget,
        QApplication=QApplication,
        QVBoxLayout=QVBoxLayout,
    )
    qtwebchannel = _module("PyQt6.QtWebChannel", QWebChannel=QWebChannel)
    qtwebenginewidgets = _module("PyQt6.QtWebEngineWidgets", QWebEngineView=QWebEngineView)

    pyqt6 = _module(
        "PyQt6",
        QtCore=qtcore,
        QtGui=qtgui,
        QtNetwork=qtnetwork,
        QtWebEngineCore=qtwebenginecore,
        QtWidgets=qtwidgets,
        QtWebChannel=qtwebchannel,
        QtWebEngineWidgets=qtwebenginewidgets,
    )
    pyqt6.__is_fake__ = True

    sys.modules.update(
        {
            "PyQt6": pyqt6,
            "PyQt6.QtCore": qtcore,
            "PyQt6.QtGui": qtgui,
            "PyQt6.QtNetwork": qtnetwork,
            "PyQt6.QtWebEngineCore": qtwebenginecore,
            "PyQt6.QtWidgets": qtwidgets,
            "PyQt6.QtWebChannel": qtwebchannel,
            "PyQt6.QtWebEngineWidgets": qtwebenginewidgets,
        }
    )


def uninstall() -> None:
    """Remove the stand-in modules, for a test that wants the real ones."""
    for name in list(sys.modules):
        if name == "PyQt6" or name.startswith("PyQt6."):
            del sys.modules[name]
