#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Show the Anki cards that match a query in a popup window.

The window loads `index.html', which embeds `tooltip.js'; that script draws
the cards as tooltips over the page and sends commands back over QWebChannel.
`CallHandler' receives those commands and turns them into AnkiConnect requests
and Emacs calls.

Anki must be running with the AnkiConnect add-on installed, listening on
``127.0.0.1:8765``.  A missing Anki is not fatal: the error is reported in the
popup, and the rest of popweb keeps working.
"""

import json
import os
import re
import urllib.request
from typing import Any, Tuple

from PyQt6.QtCore import QObject, QUrl, QVariant, pyqtSlot

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
"""URL of the AnkiConnect endpoint that the review popup talks to."""


def get_tooltip_script(script_file):
    """Return the HTML and JavaScript that the review page embeds.

    SCRIPT_FILE is `tooltip.js'; its content is placed inside a script tag,
    together with the stylesheet and the QWebChannel bootstrap that the page
    needs.  A missing file is reported and replaced by an empty script, so the
    page still loads and shows the error.
    """
    if os.path.exists(script_file):
        with open(script_file, encoding="utf-8") as file:
            tooltip_script = file.read()
    else:
        print("Script file not found: %s\n" % script_file)
        return ""

    web_content = f"""
        <style>
            :root {{
                --rev-search-tooltip-fontsize: inherit;
            }}
        </style>
        <style>
            .rev-tooltip {{
                position: absolute;
                box-shadow: 2px 2px 5px black;
                border-radius: 5px;
                padding: 10px 5px 0 10px;
                overflow: hidden;
                background: white !important;
                border: 1px solid #b7b7b7 !important;
                box-shadow: 2px 2px 5px #9e9e9e;
                max-width: 1850px;
                max-height: 1500px;
                display: flex;
                flex-direction: column;
                box-sizing: border-box;
                overflow: hidden;
            }}
            .night_mode .rev-tooltip {{
                background: #2f2f31 !important;
                border: 1px solid #383838 !important;
                box-shadow: 2px 2px 5px black;
            }}
            .rev-tooltip__scroll {{
                display: flex;
                overflow-y: auto;
                padding-right: 8px;
                flex: 1;
                justify-content: start;
                flex-wrap: wrap;
                align-items: baseline;
            }}
            .rev-tooltip__scroll .sr {{
                width: auto;
                flex: 1 1 200px;
                text-align: left;
                margin: 5px;
                border-radius: 5px;
                padding: 10px;
                overflow: hidden;
                font-size: var(--rev-search-tooltip-fontsize) !important;
                border: 1px solid #eaeaea;
                border-color: #eaeaea !important;
                background: #f9f9f9 !important;
                position: relative;
            }}
            .rev-tooltip__scroll > .sr:first-child {{
                margin-top: 0;
            }}
            .rev-tooltip__scroll > .sr:last-child {{
                margin-bottom: 0;
            }}
            .rev-tooltip__scroll .sr hr {{
                border-top: 1px solid #e8e8e8 !important;
                border-bottom: none !important;
                border-left: none !important;
                border-right: none !important;
                border-color: #e8e8e8 !important;
            }}
            .night_mode .rev-tooltip__scroll .sr hr {{
                border-top: 1px solid #484848 !important;
                border-color: #484848 !important;
            }}
            .rev-tooltip__search {{
                border-bottom: 1px solid #e4e4e4;
                margin-bottom: 10px !important;
                display: flex;
                justify-content: center;
                padding-bottom: 8px;
            }}
            .night_mode .rev-tooltip__search {{
                border-bottom: 1px solid #383838 !important;
            }}
            .rev-tooltip__search_icn {{
                color: #333;
            }}
            .night_mode .rev-tooltip__search_icn {{
                color: #8a8a8a;
            }}
            .rev-tooltip__search > input {{
                flex: 1;
                border-color: transparent !important;
                border: none;
                background: transparent !important;
                font-size: 20px !important;
                margin-left: 10px;
            }}
            .night_mode .rev-tooltip__search > input {{
                color: lightgrey !important;
            }}
            .rev-tooltip__search > input:focus {{
                outline: none !important;
            }}
            .night_mode .rev-tooltip .sr {{
                border: 1px solid #484848;
                border-color: #484848 !important;
                background: #383838 !important;
            }}
            .rev-tooltip__bottom {{
                padding: 4px 0;
                user-select: none;
                display: flex;
                justify-content: flex-end;
                align-items: center;
            }}
            .rev-tooltip__resize, .rev-tooltip__zoom, .rev-tooltip__edit {{
                height: 15px;
                width: 15px;
                opacity: 0.5;
                margin-left: 5px;
                cursor: pointer;
            }}
            .rev-tooltip__playsound {{
                border-bottom: 1px solid #e4e4e4;
                margin-bottom: 10px !important;
                display: flex;
                justify-content: center;
            }}
            .rev-tooltip__edit {{
                position: absolute;
                bottom: 5px;
                right: 5px;
                display: none;
            }}
            .rev-tooltip__edit:hover {{
                filter: brightness(1.4);
            }}
            .sr:hover .rev-tooltip__edit {{
                display: block;
            }}
            .night_mode .rev-tooltip__resize, .night_mode .rev-tooltip__zoom {{
                color: #8a8a8a;
            }}
            .night_mode .rev-tooltip__edit {{
                fill: #8a8a8a;
            }}
            .rev-tooltip__resize:hover, .rev-tooltip__zoom:hover {{
                opacity: 1.0;
            }}
            center.no-results {{
                user-select: none;
                margin: 20px 0;
                width: 100%;
            }}
            .rev-tooltip ::-webkit-scrollbar {{
                background-color: white;
            }}
            .rev-tooltip ::-webkit-scrollbar-corner {{
                background-color: white;
            }}
            .rev-tooltip ::-webkit-scrollbar-thumb {{
                background: #e8e8e8;
                border-radius: 8px;
            }}
            .night_mode .rev-tooltip ::-webkit-scrollbar {{
                background-color: #2f2f31;
            }}
            .night_mode .rev-tooltip ::-webkit-scrollbar-corner {{
                background-color: #2f2f31;
            }}
            .night_mode .rev-tooltip ::-webkit-scrollbar-thumb {{
                background: #656565;
                border-radius: 8px;
            }}
            #anki-review {{
                font-size: 3.6rem;
            }}
        </style>
        <script type='text/javascript'>
            window.REV_SEARCH_MAX_QUERY_LENGTH = 300;
            window.REV_SEARCH_SHOULD_BLUR = true;
            {tooltip_script}
        </script>
        <script language='JavaScript'>
            new QWebChannel(qt.webChannelTransport, function (channel) {{
                window.handler = channel.objects.handler;
            }});
        </script>
    """

    return web_content

class CallHandler(QObject):
    """The Python object that JavaScript calls through QWebChannel.

    It is constructed with the `WebWindow' that owns the page, the Anki media
    directory, and the name of the Emacs function to call for a dictionary
    search.  The command format is a string that starts with a verb and
    continues with its arguments, which is what `tooltip.js' sends.
    """

    def __init__(self, web_window, *args):
        """Attach the handler to WEB_WINDOW, with ARGS as its settings."""
        super().__init__()
        self.web_window = web_window
        self.media_directory = args[0]
        self.eval_in_emacs_func = args[1]

    def request(self, action, **params):
        """Return the AnkiConnect request object for ACTION and PARAMS."""
        return {"action": action, "params": params, "version": 6}

    def invoke(self, action, **params):
        """Run the AnkiConnect ACTION with PARAMS and return its result.

        The reply is validated before it is used: an unexpected shape or a
        non-null ``error`` field is raised, which the caller sees as a Python
        exception rather than as a card with a missing field.
        """
        request_json = json.dumps(self.request(action, **params)).encode("utf-8")
        response = json.load(urllib.request.urlopen(urllib.request.Request(ANKI_CONNECT_URL, request_json)))
        if len(response) != 2:
            raise Exception("response has an unexpected number of fields")
        if "error" not in response:
            raise Exception("response is missing required error field")
        if "result" not in response:
            raise Exception("response is missing required result field")
        if response["error"] is not None:
            raise Exception(response["error"])
        return response["result"]

    def get_nids(self, query):
        """Return the Anki note ids that match QUERY."""
        return self.invoke("findNotes", query=query)

    def get_notes(self, query):
        """Return the cards that match QUERY, each with its fields highlighted.

        Every card is a pair of its note id and the HTML of its non-empty
        fields, with the matches of QUERY wrapped in a ``mark`` element.  The
        highlighting is case insensitive, which is how the search itself
        behaves.
        """
        nids = self.get_nids(query)
        notes = self.invoke("notesInfo", notes=nids)
        return [
            [
                note.get("noteId"),
                re.sub(
                    r"%s" % re.escape(query),
                    f"<mark>{query}</mark>",
                    "<hr/>".join(
                        list(filter(None, map(lambda value: value.get("value"), note.get("fields").values())))
                    ),
                    flags=re.I,
                ),
            ]
            for note in notes
        ]

    @pyqtSlot(QVariant, result=QVariant)
    def expanded_on_bridge_cmd(self, cmd: str) -> Tuple[bool, Any]:
        """Run the command CMD that the page sent, and return its result.

        The commands are ``rev-search`` (search Anki), ``rev-tt-edit`` (open
        the note in Anki's editor), ``rev-tt-playsound`` (play the note's
        sound file) and ``rev-tt-dictionary`` (send the word to the Emacs
        callback named by `popweb-anki-review-callback').
        """
        if cmd.startswith("rev-search "):
            tooltip_id = int(cmd.split()[1])
            query = " ".join(cmd.split()[2:])
            if (query.isascii() and len(query) >= 3) or (not query.isascii() and len(query) >= 2):
                notes = self.get_notes(query)
                self.web_window.webview.page().runJavaScript(
                    f"setTooltipSearchResults({tooltip_id}, {json.dumps(notes)})"
                )
            return (True, None)

        elif cmd.startswith("rev-tt-edit "):
            self.invoke("guiEditNote", note=int(cmd.split()[1]))
            return (True, None)

        elif cmd.startswith("rev-tt-playsound "):
            from playsound import playsound

            tooltip_id = int(cmd.split()[1])
            note = self.invoke("notesInfo", notes=[tooltip_id])
            results = re.findall(r"\[sound:(.+?\..+?)\]", str(note))

            if not results:
                return (True, None)
            if len(results) == 1:
                playsound(os.path.expanduser(os.path.join(self.media_directory, results[0])))
                return (True, None)
            for result in results:
                playsound(os.path.expanduser(os.path.join(self.media_directory, result)))
            return (True, None)

        elif cmd.startswith("rev-tt-dictionary "):
            query = cmd.split()[1:]
            self.web_window.eval_in_emacs(self.eval_in_emacs_func, query)


def pop_anki_review_window(
    popweb,
    module_path,
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
    width_scale,
    height_scale,
    show_window,
    script_file,
    media_directory,
    new_query_p,
    emacs_query,
    eval_in_emacs_func,
):
    """Show the review window of MODULE_NAME for EMACS_QUERY.

    MODULE_PATH is the file that defines `CallHandler', and SCRIPT_FILE and
    INDEX_FILE are the assets of the page.  NEW_QUERY_P says whether the page
    has to be rebuilt for a new query; the window is created and its web
    channel built on the first call only.  The remaining arguments are the
    geometry that Emacs sent, passed to POPWEB for placement.
    """
    web_window = popweb.get_web_window(module_name)

    if not hasattr(web_window.webview, "channel") and not hasattr(web_window.webview, "handler"):
        popweb.build_web_channel(
            module_path,
            module_name,
            "handler",
            "CallHandler",
            "expanded_on_bridge_cmd",
            media_directory,
            eval_in_emacs_func,
        )

    window_width = int(frame_w * width_scale)
    window_height = int(frame_h * height_scale)

    # A dragged size wins inside `resize', so place the window that will
    # actually be shown.
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

    with open(index_file, encoding="utf-8") as index:
        index_html = (
            index.read()
            .replace("QUERY_PLACEHOLD", emacs_query)
            .replace("HEAD-PLACEHOLD", get_tooltip_script(script_file))
        )
    web_window.webview.setHtml(index_html, QUrl("file://"))
    web_window.loading_js_code = ""

    web_window.update_theme_mode()
    web_window.move(int(window_x), int(window_y))
    web_window.popup()
