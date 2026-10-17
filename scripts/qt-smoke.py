#!/usr/bin/env python3
"""Exercise the Qt window against a real PyQt6 installation.

The automatic test suite uses `test/fake_qt.py', because installing a browser
engine on every test machine is not reasonable.  This script is the manual
counterpart: it constructs a real `WebWindow`, shows it, loads a page and runs
JavaScript in it, so a change that only breaks the real Qt constructors is
still caught before a release.

    python3 scripts/qt-smoke.py          # needs PyQt6 and PyQt6-WebEngine

It uses the offscreen platform by default, so it can run over SSH; set
`QT_QPA_PLATFORM' to something else to watch the window instead.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    # Imported before QApplication on purpose: QtWebEngine refuses to be loaded
    # after the application object exists.  `core.window' performs that import.
    from core import cookies, window
except ImportError as error:
    print("PyQt6 is not available: %s" % error, file=sys.stderr)
    sys.exit(2)

from PyQt6.QtCore import QUrl  # noqa: E402  (after the engine import above)
from PyQt6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    """Build a window, load a page, run JavaScript and report what happened."""
    app = QApplication(sys.argv)

    # Replace the Emacs side: the smoke test must not need a running Emacs.
    window.get_emacs_var = lambda name: 1
    window.get_emacs_func_result = lambda name, args: (
        "#000000" if name == "popweb-get-theme-background" else "light"
    )
    with tempfile.TemporaryDirectory() as config_dir:
        cookies.get_emacs_config_dir = lambda: config_dir + "/"

        popup = window.WebWindow(app.primaryScreen().size())
        print("constructed: zoom=%s page-attached=%s"
              % (popup.zoom_factor, popup.webview.page() is popup.web_page))

        popup.show()
        app.processEvents()
        print("visible:", popup.isVisible())

        popup.web_page.setHtml(
            "<html><body style='margin:0'><div id='katex-preview'>x^2</div></body></html>",
            QUrl("file://"),
        )
        for _ in range(100):
            app.processEvents()
            time.sleep(0.01)

        width = popup.web_page.execute_javascript(
            "document.getElementById('katex-preview').offsetWidth;"
        )
        height = popup.web_page.execute_javascript(
            "document.getElementById('katex-preview').offsetHeight;"
        )
        print("javascript: width=%s height=%s" % (width, height))

        popup.hide()
        app.processEvents()

    print("qt smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
