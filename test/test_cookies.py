#!/usr/bin/env python3
"""Tests for the cookie persistence of the popup browser.

The Qt classes come from `test/fake_qt.py'; the fake cookie can round trip
through the raw form, so the disk format is exercised as well as the file
names.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test import fake_qt  # noqa: E402  (installs PyQt6 substitutes)

fake_qt.install()

from core import cookies  # noqa: E402  (import after the substitutes)
from test.fake_qt import QNetworkCookie, QUrl  # noqa: E402


class FakeView:
    """The part of a `WebView` that the cookie manager uses."""

    def __init__(self, url="http://example.com/page"):
        """Create a view whose current URL is URL."""
        self._url = QUrl(url)
        self._page = fake_qt.QWebEnginePage()
        self.loadStarted = fake_qt._Signal()

    def page(self):
        """Return the page with the profile and cookie store."""
        return self._page

    def url(self):
        """Return the current URL."""
        return self._url


def make_cookie(name="session", value="abc", domain="example.com", path="/"):
    """Return a non-session cookie with the given fields."""
    cookie = QNetworkCookie(name.encode(), value.encode())
    cookie.setDomain(domain)
    cookie.setPath(path)
    return cookie


class CookiesManagerTest(unittest.TestCase):
    """Reading, writing and deleting the stored cookies."""

    def setUp(self):
        """Point the configuration directory at a temporary directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_dir = self.tmp.name + "/"
        patcher = mock.patch.object(cookies, "get_emacs_config_dir", return_value=self.config_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def manager(self, url="http://example.com/page"):
        """Return a cookie manager attached to a fake view."""
        return cookies.CookiesManager(FakeView(url))

    def cookie_dir(self, domain="example.com"):
        """Return (and create) the directory that holds the cookies of DOMAIN."""
        path = Path(self.config_dir) / "browser" / "cookies" / domain
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_cookies_dir_lives_under_the_configuration_directory(self):
        """The manager keeps its files in browser/cookies."""
        self.assertEqual(
            cookies.CookiesManager.get_cookies_dir(),
            str(Path(self.config_dir) / "browser" / "cookies"),
        )

    def test_file_name_encodes_the_path_with_pipes(self):
        """A slash in the cookie path cannot become a directory separator."""
        cookie = make_cookie(path="/foo/bar")
        self.assertEqual(
            cookies.CookiesManager._generate_cookie_filename(cookie),
            "session+example.com+|foo|bar",
        )

    def test_file_name_hex_encodes_the_path_on_windows(self):
        """On Windows the path is hex encoded, because it may contain a colon."""
        cookie = make_cookie(path="/foo")
        with mock.patch.object(os, "name", "nt"):
            self.assertEqual(
                cookies.CookiesManager._generate_cookie_filename(cookie),
                "session+example.com+" + "/foo".encode().hex(),
            )

    def test_add_cookie_writes_the_raw_form(self):
        """A persistent cookie is stored as the bytes Qt can read back."""
        cookie = make_cookie()
        cookies.CookiesManager.add_cookie(cookie)
        stored = Path(self.config_dir) / "browser" / "cookies" / "example.com" / "session+example.com+|"
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), cookie.toRawForm())

    def test_add_cookie_skips_session_cookies(self):
        """A session cookie only lives in memory, so no file is created."""
        cookie = make_cookie()
        cookie.setSessionCookie(True)
        cookies.CookiesManager.add_cookie(cookie)
        self.assertFalse((Path(self.config_dir) / "browser" / "cookies").exists())

    def test_remove_cookie_deletes_the_file(self):
        """Removing a cookie removes the file that stored it."""
        manager = self.manager()
        cookie = make_cookie()
        cookies.CookiesManager.add_cookie(cookie)
        manager.remove_cookie(cookie)
        self.assertFalse(
            (Path(self.config_dir) / "browser" / "cookies" / "example.com" / "session+example.com+|").exists()
        )

    def test_remove_cookie_tolerates_a_missing_file(self):
        """A cookie that was never written is not an error."""
        self.manager().remove_cookie(make_cookie())

    def test_load_cookie_restores_a_host_only_cookie_with_the_page_url(self):
        """A host-only cookie is set with the page URL and an empty domain."""
        domain_dir = self.cookie_dir()
        cookie = make_cookie()
        (domain_dir / "stored").write_bytes(cookie.toRawForm())

        manager = self.manager()
        manager.load_cookie()

        self.assertEqual(len(manager.cookie_store.cookies), 1)
        restored, url = manager.cookie_store.cookies[0]
        self.assertEqual(restored.domain(), "")
        self.assertEqual(str(url), "http://example.com/page")

    def test_load_cookie_restores_a_domain_cookie_without_a_url(self):
        """A cookie for a parent domain is set without a page URL."""
        domain_dir = self.cookie_dir(".example.com")
        cookie = make_cookie(domain=".example.com")
        (domain_dir / "stored").write_bytes(cookie.toRawForm())

        manager = self.manager()
        manager.load_cookie()

        self.assertEqual(len(manager.cookie_store.cookies), 1)
        restored, url = manager.cookie_store.cookies[0]
        self.assertEqual(restored.domain(), ".example.com")
        self.assertIsNone(url)

    def test_load_cookie_without_a_directory_does_nothing(self):
        """The first run has no stored cookies and must not fail."""
        manager = self.manager()
        manager.load_cookie()
        self.assertEqual(manager.cookie_store.cookies, [])

    def test_delete_all_cookies_removes_the_directory(self):
        """Deleting everything clears memory and disk."""
        self.cookie_dir()
        manager = self.manager()
        manager.delete_all_cookies()
        self.assertFalse((Path(self.config_dir) / "browser" / "cookies").exists())

    def test_domain_matching_keeps_the_effective_upstream_behaviour(self):
        """Every stored domain is loaded, which is what upstream ended up doing."""
        manager = self.manager()
        self.assertTrue(manager.domain_matching("anything.example"))
        self.assertTrue(manager.domain_matching(".example.com"))

    def test_touch_creates_missing_parents(self):
        """A cookie file deep in a new tree can be created directly."""
        target = Path(self.config_dir) / "a" / "b" / "c"
        cookies.touch(str(target))
        self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
