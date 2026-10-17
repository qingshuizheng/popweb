"""Read and write the cookies of the popup browser.

Qt keeps cookies in memory only: the profile is explicitly set to
`NoPersistentCookies', and every cookie that is not a session cookie is
written to one file per cookie under the popweb configuration directory.  The
files are plain `QNetworkCookie` raw forms, which is the format Qt can read
back without a browser database.

A cookie file lives at ``<config>/browser/cookies/<domain>/<name>+<domain>+<path>``.
The domain directory is what a browser would call the cookie's host; the popup
loads every directory it finds when a page starts loading, which is the
behaviour the original implementation ended up with (see `domain_matching').
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWebEngineCore import QWebEngineProfile

from .bridge import get_emacs_config_dir


def touch(path: str) -> None:
    """Create the file at PATH, and its parent directories, when missing."""
    if not os.path.exists(path):
        basedir = os.path.dirname(path)

        if not os.path.exists(basedir):
            os.makedirs(basedir)

        with open(path, "a"):
            os.utime(path)


class CookiesManager:
    """Persist the cookies of one `WebView' and load them back.

    The manager is attached to the view at construction time: it connects the
    cookie store signals, writes a file for every non-session cookie, and
    restores the stored cookies each time a page starts loading.
    """

    def __init__(self, browser_view: Any) -> None:
        """Attach the manager to BROWSER_VIEW and connect its cookie signals."""
        self.browser_view = browser_view

        self.cookies_dir = self.get_cookies_dir()

        # Both session and persistent cookies are stored in memory.
        self.browser_view.page().profile().setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )

        self.cookie_store = self.browser_view.page().profile().cookieStore()

        # Save a cookie to disk when it is added, delete the file when it is
        # removed, and load the disk cookies when a page starts loading.
        self.cookie_store.cookieAdded.connect(self.add_cookie)
        self.cookie_store.cookieRemoved.connect(self.remove_cookie)
        self.browser_view.loadStarted.connect(self.load_cookie)

    @classmethod
    def get_cookies_dir(cls) -> str:
        """Return the directory that holds one subdirectory per cookie domain."""
        return os.path.join(get_emacs_config_dir(), "browser", "cookies")

    @classmethod
    def add_cookie(cls, cookie: QNetworkCookie) -> None:
        """Store COOKIE on disk, unless it is a session cookie.

        The raw form keeps every attribute of the cookie, including the expiry
        date, so loading it back restores the same cookie rather than a copy
        without a lifetime.
        """
        cookie_domain = cookie.domain()
        if not cookie.isSessionCookie():
            cookie_file = os.path.join(
                cls.get_cookies_dir(), cookie_domain, cls._generate_cookie_filename(cookie)
            )
            touch(cookie_file)

            with open(cookie_file, "wb") as f:
                f.write(cookie.toRawForm())

    def load_cookie(self) -> None:
        """Restore every cookie stored on disk into the memory cookie store."""
        if not os.path.exists(self.cookies_dir):
            return

        all_cookies_domain = os.listdir(self.cookies_dir)
        for domain in filter(self.domain_matching, all_cookies_domain):
            domain_dir = os.path.join(self.cookies_dir, domain)

            for cookie_file in os.listdir(domain_dir):
                with open(os.path.join(domain_dir, cookie_file), "rb") as f:
                    for cookie in QNetworkCookie.parseCookies(f.read()):
                        if not domain.startswith("."):
                            if self.browser_view.url().host() == domain:
                                # Restore a host-only cookie.
                                cookie.setDomain("")
                                self.cookie_store.setCookie(cookie, self.browser_view.url())
                        else:
                            self.cookie_store.setCookie(cookie)

    def remove_cookie(self, cookie: QNetworkCookie) -> None:
        """Delete the file of COOKIE when it is removed from the cookie store."""
        if not cookie.isSessionCookie():
            cookie_file = os.path.join(
                self.cookies_dir, cookie.domain(), self._generate_cookie_filename(cookie)
            )

            if os.path.exists(cookie_file):
                os.remove(cookie_file)

    def delete_all_cookies(self) -> None:
        """Delete every cookie, in memory and on disk."""
        self.cookie_store.deleteAllCookies()
        if os.path.exists(self.cookies_dir):
            shutil.rmtree(self.cookies_dir)

    def delete_cookie(self) -> None:
        """Delete the stored cookies of the current site, except session cookies."""
        cookies_domain = os.listdir(self.cookies_dir)

        for domain in filter(self.get_relate_domains, cookies_domain):
            domain_dir = os.path.join(self.cookies_dir, domain)

            for cookie_file in os.listdir(domain_dir):
                with open(os.path.join(domain_dir, cookie_file), "rb") as f:
                    for cookie in QNetworkCookie.parseCookies(f.read()):
                        self.cookie_store.deleteCookie(cookie)
            shutil.rmtree(domain_dir)

    def domain_matching(self, cookie_domain: str) -> bool:
        """Return whether COOKIE_DOMAIN may be loaded for the current page.

        The upstream implementation returned True from its first statement and
        left the domain comparison unreachable, so the effective behaviour has
        always been "load every stored domain".  This keeps that behaviour and
        says so, instead of carrying dead branches.
        """
        return True

    def get_relate_domains(self, cookie_domain: str) -> bool:
        """Return whether COOKIE_DOMAIN shares a registrable domain with the page.

        The check uses the public suffix list when the optional `tld' module is
        installed.  Without it, the last two labels of the host stand in for
        the registrable domain, which is right for the common cases and only
        wrong for suffixes such as ``co.uk``.
        """
        import re

        host_string = self.browser_view.url().host()

        if cookie_domain.startswith("."):
            cookie_domain = cookie_domain[1:]

        try:
            import tld
        except ImportError:
            tld = None

        if tld is not None:
            base_domain = tld.get_fld(host_string, fix_protocol=True, fail_silently=True)
        else:
            base_domain = ".".join(host_string.split(".")[-2:])

        if not base_domain:
            # Check whether the host string is an IP address.
            if (
                re.compile(
                    r"^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)$"
                ).match(host_string)
                and host_string == cookie_domain
            ):
                return True
            return False

        if cookie_domain == base_domain:
            return True

        if cookie_domain.endswith(base_domain) and cookie_domain[: -len(base_domain)][-1] == ".":
            return True

        return False

    @classmethod
    def _generate_cookie_filename(cls, cookie: QNetworkCookie) -> str:
        """Return the file name that stores COOKIE on disk.

        The name consists of the cookie name, its domain and its path, joined
        by plus signs.  The path separator is replaced by a pipe so that the
        file stays inside its domain directory; on Windows the path is hex
        encoded instead, because a drive letter would contain a colon.
        """
        name = cookie.name().data().decode("utf-8")
        domain = cookie.domain()
        if os.name == "nt":
            encode_path = cookie.path().encode("utf-8").hex()
        else:
            encode_path = cookie.path().replace("/", "|")

        return name + "+" + domain + "+" + encode_path
