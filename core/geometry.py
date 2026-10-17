"""Where a popup window goes, as pure arithmetic.

Emacs sends the cursor coordinate and the frame rectangle with every popup
request; the configured `popweb-popup-pos' decides which corner of that
rectangle the window is anchored to.  Nothing here touches Qt, which is what
makes all eight positions testable without a screen.
"""

from __future__ import annotations

from typing import Tuple

POPUP_POSITIONS = (
    "point-bottom",
    "point-bottom-right",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "middle",
)
"""The values `popweb-popup-pos' accepts."""


def adjust_render_pos(
    popup_pos: str,
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
    """Return the window position for POPUP_POS and the given geometry.

    RENDER_X and RENDER_Y are the cursor's absolute pixel position, X_OFFSET
    and Y_OFFSET the shift away from it that Emacs asks for, RENDER_W and
    RENDER_H the popup size, and FRAME_X, FRAME_Y, FRAME_W, FRAME_H the Emacs
    frame rectangle.  The result is clamped to the screen origin, so a popup
    never gets a negative coordinate.

    The `point-*' positions flip above or left of the cursor when the popup
    would leave the frame, which keeps a long definition visible instead of
    cutting it off at the bottom.
    """
    if popup_pos == "top-left":
        render_x = frame_x
        render_y = frame_y
    elif popup_pos == "top-right":
        render_x = frame_x + frame_w - render_w - x_offset
        render_y = frame_y
    elif popup_pos == "bottom-left":
        render_x = frame_x
        render_y = frame_y + frame_h - render_h - y_offset
    elif popup_pos == "bottom-right":
        render_x = frame_x + frame_w - render_w - x_offset
        render_y = frame_y + frame_h - render_h - y_offset
    elif popup_pos == "point-bottom":
        render_x = max(int(render_x - render_w / 2), 0)
        render_y = max(render_y, 0)
        if render_x + render_w > frame_x + frame_w:
            render_x = frame_x + frame_w - render_w - x_offset
        if render_y + render_h > frame_y + frame_h:
            render_y = render_y - render_h - y_offset
    elif popup_pos == "point-bottom-right":
        render_x = max(render_x, 0)
        render_y = max(render_y, 0)
        if render_x + render_w > frame_x + frame_w:
            render_x = frame_x + frame_w - render_w - x_offset
        if render_y + render_h > frame_y + frame_h:
            render_y = render_y - render_h - y_offset
    elif popup_pos == "middle":
        render_x = frame_x + (frame_w - render_w) / 2 - x_offset
        render_y = frame_y + (frame_h - render_h) / 2 - y_offset
    else:
        raise Exception("Cannot recognize Emacs variable popweb-popup-pos!")
    render_x = max(render_x, 0)
    render_y = max(render_y, 0)
    return render_x, render_y
