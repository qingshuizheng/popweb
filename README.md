# popweb

Popup web windows for Emacs.  A small Python/Qt process renders a frameless
window next to the cursor; Emacs decides what to show and when to hide it.
The same mechanism displays translations, LaTeX formulas, a colour picker, a
URL preview and Anki cards.

This is the `refactor/full` branch of the fork: same features as
[upstream](https://github.com/manateelazycat/popweb), with the Elisp and Python
halves split into modules, every definition documented, and a test suite that
runs without a display or a real Anki.  The differences are listed in
[CORRECTIONS.org](./CORRECTIONS.org); the plan and its measurements are in
[REFACTOR.org](./REFACTOR.org).

## Extensions

| Extension | What it shows | Entry point |
| --- | --- | --- |
| dict | Bing, Youdao, YouGlish and Dict.cn translations | `popweb-dict-<site>-pointer` / `-input` |
| latex | KaTeX rendering of the math at point | `popweb-latex-mode` |
| color-picker | A colour picker seeded with the colour at point | `popweb-color-picker-show` |
| url-preview | A URL opened in a popup browser | `popweb-url-preview-pointer` / `popweb-url-input` |
| anki-review | Anki cards matching a word or sentence | `popweb-anki-review-show` |

The org-roam link previewer of upstream is **not** part of this branch.

## Requirements

- Emacs 27.1 or newer.
- Python 3.9 or newer with PyQt6 and python-epc:

  ```sh
  python3 -m pip install PyQt6 PyQt6-WebEngine PyQt6-Qt6 PyQt6-sip epc sexpdata
  ```

  macOS also needs `pyobjc`, because the process marks itself as a background
  application there.

- Optional: `browser_cookie3` for `popweb-import-browser-cookies`, `playsound`
  for Anki pronunciation, and AUCTeX for LaTeX previews in `latex-mode`.
- Anki with the [AnkiConnect](https://foosoft.net/projects/anki-connect/) add-on
  for `popweb-anki-review-show`; it listens on `127.0.0.1:8765`.

The author's Nix configuration installs the Elisp and Python sources from
this branch and points `popweb-python-command` at a pip venv
(`~/.cache/popweb/venv`): PyQt6-WebEngine is not practical to build with Nix
on aarch64-darwin, so the interpreter stays a one-time local install.  The
same `pip install` line above creates it:

```sh
python3 -m venv ~/.cache/popweb/venv
~/.cache/popweb/venv/bin/pip install PyQt6 PyQt6-WebEngine PyQt6-Qt6 PyQt6-sip epc sexpdata pyobjc
```

## Installation

```elisp
(add-to-list 'load-path "<path-to-popweb>")

;; LaTeX preview: KaTeX is vendored in extension/latex.
(add-to-list 'load-path "<path-to-popweb>/extension/latex")
(require 'popweb-latex)
(add-hook 'org-mode-hook #'popweb-latex-mode)

;; Translation popups.
(add-to-list 'load-path "<path-to-popweb>/extension/dict")
(require 'popweb-dict)

;; Colour picker.
(add-to-list 'load-path "<path-to-popweb>/extension/color-picker")
(require 'popweb-color-picker)

;; URL preview.
(add-to-list 'load-path "<path-to-popweb>/extension/url-preview")
(require 'popweb-url)

;; Anki review.
(add-to-list 'load-path "<path-to-popweb>/extension/anki-review")
(require 'popweb-anki-review)
```

Only the extensions that are required start their own window; the Python
process itself starts once, one second after `popweb` is loaded, so the first
popup is fast.  Set `popweb-start-python-process-when-require` to nil to start
it on the first popup instead.

## Usage

- `popweb-dict-bing-pointer`, `-input` (and the same pair for `youdao`,
  `youglish` and `dictcn`): translate the word or region at point, or a word
  read from the minibuffer.  The popup also speaks the word when
  `popweb-dict-say-word-p` is non-nil.
- `popweb-latex-mode`: show the formula at point and follow point with it.
  Works in `org-mode` (fragments, environments and latex source blocks) and in
  `latex-mode` (through AUCTeX's `texmathp`).
- `popweb-color-picker-show`: open a picker seeded with the hex colour, CSS
  colour name or `rgb()`/`hsl()` call at point, or with black when there is
  none.
- `popweb-url-preview-pointer`, `popweb-url-input`: preview the URL at point or
  one read from the minibuffer.  `file:` URLs are resolved against the current
  buffer's directory.
- `popweb-anki-review-show`: query Anki.  With a prefix argument start from the
  sentence at point; with an active region use the region; otherwise read the
  query from the minibuffer.  Selecting a word inside the popup searches for
  it.
- `M-x popweb-import-browser-cookies`: copy the cookies of a browser for one
  domain into popweb, so pages that need a login load correctly.
- `M-x popweb-restart-process`, `M-x popweb-kill-process`: restart or stop the
  Python process.  Extensions can clean up first through
  `popweb-stop-process-hook`.

## Screenshots

### LaTeX preview

![LaTeX preview](./img/latex-preview.gif)

### Bing and Youdao translations

![Bing](./img/dict-bing.png)
![Youdao](./img/dict-youdao.png)

### YouGlish pronunciation

![YouGlish](./img/dict-youglish.png)

### Developer tools

![Developer tools](./img/developer-tools.png)

## Customization

### Popup position

`popweb-popup-pos` decides where the window goes:

- `"point-bottom"`: centred below the cursor.
- `"point-bottom-right"`: below the cursor, growing to the right (the default).
- `"top-left"`, `"top-right"`, `"bottom-left"`, `"bottom-right"`: the corners of
  the Emacs frame.
- `"middle"`: the centre of the frame.

The `point-*` positions flip above or to the left of the cursor when the popup
would leave the frame.

### Proxy

```elisp
(setq popweb-proxy-type "http")
(setq popweb-proxy-host "127.0.0.1")
(setq popweb-proxy-port "1080")
```

`popweb-proxy-type` is either `"http"` or `"socks5"`; leave all three empty to
use no proxy.

### Font size

`popweb-zoom-factor` scales the page.  On screens wider than 3000 pixels the
Python side doubles it automatically.

```elisp
(setq popweb-zoom-factor 1.5)
```

### URL preview size

The URL preview is either scaled to the Emacs frame or sized in pixels:

```elisp
(setq popweb-url-web-window-size-use-absolute t)
(setq popweb-url-web-window-width-absolute 480)
(setq popweb-url-web-window-height-absolute 270)

;; Or, with the absolute mode off:
(setq popweb-url-web-window-width-scale 0.8)
(setq popweb-url-web-window-height-scale 0.45)
```

### Anki media and callback

To play the `[sound:...]` tags of a card, point the option at the Anki media
directory and install `playsound`:

```elisp
(setq popweb-anki-review-media-directory "<path-to-Anki-media>")
```

```sh
python3 -m pip install playsound
```

The dictionary lookup inside the popup calls the Emacs function named by
`popweb-anki-review-callback`:

```elisp
(setq popweb-anki-review-callback "popweb-dict-eudic-dicts-input")
```

### Developer tools

Set `popweb-enable-developer-tools` to t to open the Qt web developer tools
next to every popup.  It is useful when a site changes its layout and the
JavaScript snippet of an extension stops trimming the page.

## Development

The two halves have the same shape: a front door, a few modules, and the
extensions.

```text
popweb.el             public surface and autoloaded commands
popweb-config.el      every defcustom
popweb-ipc.el         calls in both directions, Base64 encoding
popweb-process.el     process lifecycle, EPC server, Qt environment
popweb-geometry.el    cursor, frame and theme reads
popweb-deferred.el    vendored deferred.el
popweb-epc.el         vendored epcs.el

popweb.py             entry point
core/bridge.py        Emacs access: variables, functions, EPC client
core/geometry.py      pure placement arithmetic
core/cookies.py       cookie persistence
core/window.py        Qt window, page, dark mode, GUI thread bridge
core/application.py   the EPC instance Emacs calls
core/extension.py     load an extension module by path

extension/<name>/     one Elisp and one Python file per popup, plus assets
test/                 ERT suites (*-test.el) and unittest suites (test_*.py)
scripts/              the gates
```

An extension receives the application object as the first argument of its
Python entry point and may use exactly three methods: `get_web_window`,
`adjust_render_pos` and `build_web_channel`.  A new popup therefore needs no
change in `core/`.

### Tests and gates

```sh
scripts/check-test.sh     # ERT + the Python suites, no display needed
scripts/check-elisp.sh    # forms read, definitions have bodies, zero warnings, checkdoc
scripts/check-python.sh   # py_compile, docstrings, coverage, protocol, ruff
```

`scripts/check-python.sh` uses `uv run --frozen` when `uv` is available, which
is what provides `epc`, `sexpdata` and `ruff`.  The Python tests import a
stand-in for PyQt6 (`test/fake_qt.py`), so they run on a machine without Qt;
the Elisp tests replace the frame primitives and the process functions they
need.

The gates are also the definition of done for this branch:

- every definition has a docstring (Elisp and Python);
- byte-compiling every Elisp file produces zero warnings;
- checkdoc reports nothing;
- every source file is named by a test;
- the names shared by the two halves still exist on both sides.

## Report a bug

Try to reproduce it with `emacs -q` and only popweb loaded.  If it still
happens, open an issue with the content of the `*popweb*` buffer, which holds
the output of the Python process.  A segfault is easier to report with
`popweb-enable-debug` on: the process then runs under gdb and prints a
backtrace into the same buffer after the crash.

## License

GPLv3, like upstream.  The vendored `deferred.el` and `epcs.el` keep their
original copyright and license headers.
