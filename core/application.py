"""The object Emacs talks to, and the state one popweb process owns.

`POPWEB` is registered as the EPC instance of the Python side, so every
`call_module_method', `hide_web_window', `import_browser_cookies' and
`cleanup' request lands on one of its methods.  It also owns the two caches
that make a popup cheap after the first time: one web window per module name,
and one loaded module per file path.

Qt requires widget work to happen on the GUI thread, while EPC serves calls on
a worker thread.  The methods that touch windows therefore carry `@PostGui()`
and do their work through a signal; the returned value of such a method is
`None`, which is why the Emacs side calls them asynchronously.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Dict, List, Tuple

from epc.server import ThreadingEPCServer
from PyQt6 import QtCore
from PyQt6.QtCore import QDateTime, QUrl
from PyQt6.QtNetwork import QNetworkCookie, QNetworkProxy, QNetworkProxyFactory
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWidgets import QApplication

from . import extension
from .bridge import (
    close_epc_client,
    eval_in_emacs,
    get_emacs_func_result,
    get_emacs_var,
    get_emacs_vars,
    init_epc_client,
)
from .cookies import CookiesManager
from .geometry import adjust_render_pos as compute_render_pos
from .window import PostGui, WebWindow


class POPWEB:
    """The EPC instance of popweb: one per Emacs session.

    Construction starts the EPC server, tells Emacs the port of that server,
    and applies the proxy settings.  ARGS is the command line of `popweb.py',
    whose first element is the port of the EPC server that Emacs opened.
    """

    def __init__(self, args: List[str], screen_size: Any = None) -> None:
        """Start the EPC server and finish the handshake with Emacs."""
        init_epc_client(int(args[0]))

        self.server = ThreadingEPCServer(("127.0.0.1", 0), log_traceback=True)
        self.server.allow_reuse_address = True

        self.server.register_instance(self)

        # Serve EPC in a worker thread so that the Qt main loop keeps running.
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.start()

        self.web_window_dict: Dict[str, WebWindow] = {}
        self.module_dict: Dict[str, Any] = {}

        self.get_emacs_func_result = get_emacs_func_result

        if screen_size is None:
            screen_size = QApplication.instance().primaryScreen().size()
        self.screen_size = screen_size

        eval_in_emacs("popweb--first-start", [self.server.server_address[1]])

        # Do not use the system proxy: a page would otherwise wait for a proxy
        # that is not reachable, which makes every popup slow.
        QNetworkProxyFactory.setUseSystemConfiguration(False)

        (proxy_host, proxy_port, proxy_type) = get_emacs_vars(
            ["popweb-proxy-host", "popweb-proxy-port", "popweb-proxy-type"]
        )

        self.proxy: Tuple[Any, Any, Any] = (proxy_type, proxy_host, proxy_port)
        self.is_proxy = False

        if proxy_type != "" and proxy_host != "" and proxy_port != "":
            self.enable_proxy()

    def enable_proxy(self) -> None:
        """Apply the proxy settings that were read from Emacs."""
        proxy = QNetworkProxy()
        if self.proxy[0] == "socks5":
            proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
        elif self.proxy[0] == "http":
            proxy.setType(QNetworkProxy.ProxyType.HttpProxy)
        proxy.setHostName(self.proxy[1])
        proxy.setPort(int(self.proxy[2]))

        self.is_proxy = True
        QNetworkProxy.setApplicationProxy(proxy)

    def disable_proxy(self) -> None:
        """Stop using any proxy for the popup pages."""
        proxy = QNetworkProxy()
        proxy.setType(QNetworkProxy.ProxyType.NoProxy)

        self.is_proxy = False
        QNetworkProxy.setApplicationProxy(proxy)

    def toggle_proxy(self) -> None:
        """Enable the configured proxy when it is off, and disable it when it is on."""
        if self.is_proxy:
            self.disable_proxy()
        else:
            self.enable_proxy()

    def get_web_window(self, module_name: str) -> WebWindow:
        """Return the web window of MODULE_NAME, creating it on first use."""
        if module_name not in self.web_window_dict:
            self.web_window_dict[module_name] = WebWindow(self.screen_size)

        return self.web_window_dict[module_name]

    def get_module(self, module_path: str) -> Any:
        """Return the Python module at MODULE_PATH, loading it on first use."""
        if module_path not in self.module_dict:
            self.module_dict[module_path] = extension.load_module(module_path)

        return self.module_dict[module_path]

    def adjust_render_pos(
        self,
        render_x: float,
        render_y: float,
        x_offset: float,
        y_offset: float,
        render_w: float,
        render_h: float,
        frame_x: float,
        frame_y: float,
        frame_w: float,
        frame_h: float,
    ) -> Tuple[float, float]:
        """Return the window position for the configured `popweb-popup-pos'.

        The arguments are the cursor coordinate, the offsets Emacs asks for,
        the window size and the frame rectangle; the arithmetic lives in
        `core.geometry.adjust_render_pos', which is pure and tested on its own.
        """
        popup_pos = get_emacs_var("popweb-popup-pos")
        return compute_render_pos(
            popup_pos,
            render_x,
            render_y,
            x_offset,
            y_offset,
            render_w,
            render_h,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
        )

    @PostGui()
    def call_module_method(self, module_path: str, method_name: str, method_args: List[Any]) -> None:
        """Call METHOD_NAME of the module at MODULE_PATH with METHOD_ARGS.

        The application object itself is prepended to METHOD_ARGS, which is the
        extension protocol: an extension function receives `popweb' first and
        the Emacs arguments after it.
        """
        module = self.get_module(module_path)
        method_args.insert(0, self)
        getattr(module, method_name)(*method_args)

    @PostGui()
    def hide_web_window(self, module_name: str) -> None:
        """Hide the window of MODULE_NAME and load a blank page into it."""
        if module_name in self.web_window_dict:
            web_window = self.web_window_dict[module_name]
            web_window.hide()
            web_window.webview.load(QUrl(""))

            if hasattr(web_window, "developer_tools_view"):
                web_window.developer_tools_view.hide()

    @PostGui()
    def build_web_channel(
        self,
        module_path: str,
        module_name: str,
        expose_to_js_handler_name: str,
        slot_class_name: str,
        slot_method_name: str,
        *slot_method_args: Any,
    ) -> None:
        """Expose a Python object to the page of MODULE_NAME over QWebChannel.

        The class named SLOT_CLASS_NAME in the module at MODULE_PATH is
        instantiated as (web_window, *SLOT_METHOD_ARGS), and its
        SLOT_METHOD_NAME method is registered on the object that JavaScript
        sees as EXPOSE_TO_JS_HANDLER_NAME.
        """
        module = self.get_module(module_path)
        slot_class = getattr(module, slot_class_name)
        slot_method = getattr(slot_class, slot_method_name)
        setattr(
            slot_class,
            slot_method_name,
            QtCore.pyqtSlot(QtCore.QVariant, result=QtCore.QVariant)(slot_method),
        )
        web_window = self.get_web_window(module_name)
        web_window.webview.channel = QWebChannel()
        web_window.webview.handler = slot_class(web_window, *slot_method_args)
        web_window.webview.channel.registerObject(expose_to_js_handler_name, web_window.webview.handler)
        web_window.webview.page().setWebChannel(web_window.webview.channel)

    def import_browser_cookies(self, browser: str, domain_name: str) -> None:
        """Import the cookies of BROWSER for DOMAIN_NAME into the cookie store.

        BROWSER names a function of `browser_cookie3'; a missing module, an
        unknown browser or a browser that refuses to be read is reported with
        its traceback and otherwise ignored, because importing cookies is a
        convenience and must never take the process down.
        """
        try:
            import browser_cookie3

            cookiejar = getattr(browser_cookie3, browser)(domain_name=domain_name)
            if cookiejar is None:
                print("Import cookie failed!")
                return

            for cookie in cookiejar:
                qt_cookie = QNetworkCookie(cookie.name.encode(), cookie.value.encode())
                qt_cookie.setDomain(cookie.domain)
                qt_cookie.setSecure(cookie.secure)
                qt_cookie.setPath(cookie.path)
                qt_cookie.setExpirationDate(
                    QDateTime.fromSecsSinceEpoch(0 if cookie.expires is None else cookie.expires)
                )
                CookiesManager.add_cookie(qt_cookie)
        except Exception:
            traceback.print_exc()

    def cleanup(self) -> None:
        """Close the EPC client before the process exits."""
        close_epc_client()
