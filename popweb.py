#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point of the popweb Python process.

Emacs starts this file with one argument: the TCP port of the EPC server it
just opened.  The process then creates a Qt application, connects back to
Emacs, and runs the Qt event loop until Emacs closes the connection.

The import order matters.  `PyQt6.QtWebEngineWidgets` must be imported before
a `QCoreApplication` exists, so it is imported by `core.window`, which this
file imports before constructing the application.  On macOS the process also
marks itself as a background-only application, so it never owns a Dock icon or
a menu bar.
"""

import platform
import signal
import sys

from PyQt6.QtWidgets import QApplication

from core.application import POPWEB


def main() -> int:
    """Create the Qt application and run popweb until Emacs closes it.

    Return the exit status of the Qt event loop.
    """
    if platform.system() == "Darwin":
        import AppKit

        info = AppKit.NSBundle.mainBundle().infoDictionary()
        info["LSBackgroundOnly"] = "1"

    # Ask for GPU rasterization explicitly: the popup is a single composited
    # surface, and the software path is noticeably slower on a 4K screen.
    hardware_acceleration_args = []
    if platform.system() != "Windows":
        hardware_acceleration_args += [
            "--ignore-gpu-blocklist",
            "--enable-gpu-rasterization",
            "--enable-native-gpu-memory-buffers",
        ]

    app = QApplication(sys.argv + hardware_acceleration_args)
    screen_size = app.primaryScreen().size()

    POPWEB(sys.argv[1:], screen_size)

    # Let C-c and SIGTERM stop the process the way they stop a normal program,
    # instead of leaving it to Qt's own event loop policy.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
