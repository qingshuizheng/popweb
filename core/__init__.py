"""Implementation modules of the popweb Python process.

`popweb.py` is the entry point; this package holds the parts it is made of:

- `bridge` talks to Emacs over EPC.
- `geometry` computes where a popup window goes.
- `cookies` reads and writes the cookies imported from a browser.
- `sizes` persists the sizes the user dragged, one JSON file per session.
- `window` owns the Qt window and the web page in it.
- `application` is the object Emacs calls into, and owns the module cache.
- `extension` loads the Python half of an extension by file name.

The extension modules under `extension/' do not import this package: they
receive the application object and use only its three public methods, which is
what keeps an extension independent of the internals here.
"""
