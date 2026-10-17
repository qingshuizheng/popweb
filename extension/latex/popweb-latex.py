#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the LaTeX formula at point in a popup window.

The page is `index.html' next to this file; KaTeX is vendored there, so the
preview works offline.  The formula is substituted into the page as text and
the window is sized from the rendered element, which is why the page has to be
laid out before the size is known.
"""

import os

from PyQt6.QtCore import QTimer, QUrl

SIZE_DELAY_MS = 100
"""Milliseconds to wait for the page to lay out before measuring it."""


def adjust_latex_window(
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
    show_window,
    new_latex,
):
    """Measure, place and show WEB_WINDOW after the formula page has loaded.

    NEW_LATEX says whether the page was reloaded with a new formula; only then
    is the rendered element measured again and the window resized.  SHOW_WINDOW
    controls whether the window becomes visible.  The remaining arguments are
    the geometry that Emacs sent, passed to POPWEB for placement.
    """
    if new_latex is True:
        render_width = web_window.web_page.execute_javascript(
            "document.getElementById('katex-preview').offsetWidth;"
        )
        render_height = web_window.web_page.execute_javascript(
            "document.getElementById('katex-preview').offsetHeight;"
        )
        if render_width is None or render_height is None:
            render_width = 0
            render_height = 0

        render_width = int(render_width * web_window.zoom_factor * 1.2)
        render_height = int(render_height * web_window.zoom_factor)

        web_window.update_theme_mode()
        # A formula that needs more room grows the window even after the user
        # dragged it; a smaller one keeps the dragged size instead of
        # clipping the formula.
        web_window.resize_to_fit(render_width, render_height)
        web_window.render_width = web_window.width()
        web_window.render_height = web_window.height()

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

    if show_window:
        web_window.popup()


def pop_latex_window(
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
    show_window,
    new_latex,
    latex_string,
):
    """Show LATEX_STRING in the popup called MODULE_NAME.

    INDEX_FILE is the KaTeX page; its BACKGROUND, INDEX_DIR and LATEX markers
    are replaced with the Emacs theme background, the page directory and the
    formula.  NEW_LATEX decides whether the page is reloaded at all, so moving
    the cursor inside one formula does not re-render it.  The window is sized
    after SIZE_DELAY_MS, once the page has laid the formula out.
    """
    web_window = popweb.get_web_window(module_name)
    with open(index_file, encoding="utf-8") as index:
        index_html = (
            index.read()
            .replace("BACKGROUND", popweb.get_emacs_func_result("popweb-get-theme-background", []))
            .replace("INDEX_DIR", os.path.dirname(index_file))
            .replace("LATEX", latex_string)
        )
    web_window.loading_js_code = ""
    if new_latex is True:
        web_window.webview.setHtml(index_html, QUrl("file://"))

    QTimer().singleShot(
        SIZE_DELAY_MS,
        lambda: adjust_latex_window(
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
            show_window,
            new_latex,
        ),
    )
