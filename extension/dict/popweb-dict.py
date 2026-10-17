#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Show a translation page in a popup window.

The Emacs half of the dictionary extension sends the URL of a translation
site, a JavaScript snippet that trims the page down to the part worth
reading, and optionally the path of a JavaScript file to run once the page has
finished loading.
"""

from PyQt6.QtCore import QUrl


def pop_translate_window(
    popweb,
    module_name,
    x,
    y,
    x_offset,
    y_offset,
    frame_x,
    frame_y,
    frame_w,
    frame_h,
    width_scale,
    height_scale,
    url,
    loading_js_code,
    js_file="",
    js_file_code_args=None,
):
    """Show the translation page of URL in the popup called MODULE_NAME.

    POPWEB is the application object; MODULE_NAME, X, Y, X_OFFSET, Y_OFFSET,
    FRAME_X, FRAME_Y, FRAME_W and FRAME_H are the window identity and geometry
    that Emacs sent.  WIDTH_SCALE and HEIGHT_SCALE size the window as a fraction
    of the Emacs frame.  LOADING_JS_CODE runs on every load progress event,
    JS_FILE is an optional JavaScript file whose content runs after the load,
    and JS_FILE_CODE_ARGS is passed to that content as its argument list.
    """
    web_window = popweb.get_web_window(module_name)
    window_width = int(frame_w * width_scale)
    window_height = int(frame_h * height_scale)

    # Resize first: a size the user dragged wins inside `resize', and the
    # placement has to clamp the window that will actually be shown.
    web_window.resize(window_width, window_height)
    window_width, window_height = web_window.width(), web_window.height()
    window_x, window_y = popweb.adjust_render_pos(
        x + x_offset,
        y + y_offset,
        x_offset,
        y_offset,
        window_width,
        window_height,
        frame_x,
        frame_y,
        frame_w,
        frame_h,
    )

    web_window.loading_js_code = loading_js_code
    web_window.js_file_code = read_js_content(js_file)
    web_window.js_file_code_args = js_file_code_args
    web_window.webview.setUrl(QUrl(url))
    web_window.update_theme_mode()
    web_window.move(int(window_x), int(window_y))
    web_window.popup()


def read_js_content(js_file):
    """Return the content of JS_FILE, or an empty string when it does not exist.

    A missing file is not an error: the dictionary sites work without the
    optional snippet, and a popup that shows the page is better than no popup.
    """
    import os

    if os.path.exists(js_file):
        with open(js_file, encoding="utf-8") as fp:
            return fp.read()
    else:
        print("File not found: %s\n" % js_file)
        return ""
