#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Show the colour picker page and size it to its content.

The picker is a fixed-size web page (200 by 309 pixels before zoom), so unlike
the LaTeX preview it does not need to ask the page for its size.
"""

import os

from PyQt6.QtCore import QTimer, QUrl

PICKER_WIDTH = 200
"""Width of the colour picker page in pixels, before the zoom factor."""

PICKER_HEIGHT = 309
"""Height of the colour picker page in pixels, before the zoom factor."""


def adjust_color_picker_window(
    popweb,
    web_window,
    window_x,
    window_y,
    x_offset,
    y_offset,
    frame_x,
    frame_y,
    frame_w,
    frame_h,
):
    """Size, place and show WEB_WINDOW for the geometry that Emacs sent.

    POPWEB computes the final position from the configured
    `popweb-popup-pos'; WINDOW_X, WINDOW_Y, X_OFFSET, Y_OFFSET, FRAME_X,
    FRAME_Y, FRAME_W and FRAME_H are that geometry.
    """
    render_width = PICKER_WIDTH
    render_height = PICKER_HEIGHT

    render_width = int(render_width * web_window.zoom_factor)
    render_height = int(render_height * web_window.zoom_factor)

    web_window.update_theme_mode()
    web_window.resize(render_width, render_height)
    render_width = web_window.width()
    render_height = web_window.height()
    web_window.render_width = render_width
    web_window.render_height = render_height

    window_x, window_y = popweb.adjust_render_pos(
        window_x,
        window_y,
        x_offset,
        y_offset,
        web_window.render_width,
        web_window.render_height,
        frame_x,
        frame_y,
        frame_w,
        frame_h,
    )
    web_window.move(window_x, window_y)

    web_window.popup()


def pop_color_picker_window(
    popweb,
    module_name,
    index_file,
    x,
    y,
    x_offset,
    y_offset,
    frame_x,
    frame_y,
    frame_w,
    frame_h,
    init_color,
):
    """Show the colour picker of MODULE_NAME, initialised with INIT_COLOR.

    INDEX_FILE is the picker's HTML page; the empty string in it is replaced
    with the colour at point, or with black when Emacs did not find one.  The
    window is adjusted after a short timer, because the page has to lay itself
    out before the theme background can be applied.
    """
    web_window = popweb.get_web_window(module_name)
    with open(index_file, encoding="utf-8") as index:
        index_html = (
            index.read()
            .replace("INDEX_DIR", os.path.dirname(index_file))
            .replace("DEFAULT_COLOR", init_color if init_color != "" else "#000000")
        )

    web_window.loading_js_code = ""
    web_window.webview.setHtml(index_html, QUrl("file://"))

    QTimer().singleShot(
        100,
        lambda: adjust_color_picker_window(
            popweb,
            web_window,
            x + x_offset,
            y + y_offset,
            x_offset,
            y_offset,
            frame_x,
            frame_y,
            frame_w,
            frame_h,
        ),
    )
