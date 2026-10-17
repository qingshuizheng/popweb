"""Show a URL preview in a popup window.

The window is an ordinary web view: Emacs sends the URL and the geometry, and
the size is either a fraction of the Emacs frame or a fixed pixel size,
depending on `popweb-url-web-window-size-use-absolute'.
"""

from PyQt6.QtCore import QUrl


def pop_url_window(
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
    width_absolute,
    height_absolute,
    use_absolute,
    url,
):
    """Show URL in the popup called MODULE_NAME.

    USE_ABSOLUTE selects the size source: the fixed WIDTH_ABSOLUTE and
    HEIGHT_ABSOLUTE in pixels when it is true, or FRAME_W and FRAME_H scaled by
    WIDTH_SCALE and HEIGHT_SCALE when it is false.  The remaining arguments are
    the geometry that Emacs sent, passed to POPWEB for placement.
    """
    web_window = popweb.get_web_window(module_name)
    if not use_absolute:
        window_width = frame_w * width_scale
        window_height = frame_h * height_scale
    else:
        window_width = width_absolute
        window_height = height_absolute
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

    web_window.webview.setUrl(QUrl(url))
    web_window.update_theme_mode()
    web_window.resize(int(window_width), int(window_height))
    web_window.move(int(window_x), int(window_y))
    web_window.popup()
