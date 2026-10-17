"""Persist the popup sizes the user dragged, one JSON file per config directory.

The file is read once when the process starts and rewritten after every drag,
so a size survives an Emacs restart.  A missing, unreadable or malformed file
is treated as "no saved sizes": a popup must still open, and a stale file must
never be a reason to fail.  The write goes through a temporary file and
`os.replace', so an interrupted write cannot leave half a JSON document
behind.
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Any, Dict, Optional, Tuple

Size = Tuple[int, int]


class WindowSizes:
    """The sizes dragged for each extension module, backed by PATH.

    The keys are the module names used by `popweb-get-web-window' (the same
    names Emacs passes to `call_module_method'), and the values are
    ``[width, height]`` in pixels.  Nothing here touches Qt.
    """

    def __init__(self, path: str) -> None:
        """Load the sizes stored at PATH, or start empty when there are none."""
        self.path = path
        self.sizes: Dict[str, Size] = {}
        self.load()

    def load(self) -> None:
        """Replace the in-memory sizes with the ones stored at `path'.

        A file that does not exist is normal; a file that cannot be read or
        parsed is reported and ignored, because a broken cache must not stop
        popweb from starting.
        """
        try:
            with open(self.path, encoding="utf-8") as sizes_file:
                data = json.load(sizes_file)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            traceback.print_exc()
            return

        if not isinstance(data, dict):
            return
        for module_name, value in data.items():
            size = self._valid_size(value)
            if isinstance(module_name, str) and size is not None:
                self.sizes[module_name] = size

    @staticmethod
    def _valid_size(value: Any) -> Optional[Size]:
        """Return VALUE as a positive (WIDTH, HEIGHT) pair, or nil."""
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        width, height = value
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in (width, height)):
            return None
        if width <= 0 or height <= 0:
            return None
        return int(width), int(height)

    def get(self, module_name: Optional[str]) -> Optional[Size]:
        """Return the saved size of MODULE-NAME, or nil when there is none."""
        if not module_name:
            return None
        return self.sizes.get(module_name)

    def set(self, module_name: Optional[str], width: int, height: int) -> None:
        """Remember WIDTH by HEIGHT for MODULE-NAME and write the file."""
        if not module_name:
            return
        self.sizes[module_name] = (int(width), int(height))
        self.save()

    def clear(self, module_name: Optional[str] = None) -> None:
        """Forget MODULE-NAME, or every module when it is nil, and write.

        Forgetting the last size removes the file instead of leaving an empty
        document behind.
        """
        if module_name in (None, ""):
            self.sizes.clear()
        else:
            self.sizes.pop(module_name, None)

        if self.sizes:
            self.save()
            return
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        except OSError:
            traceback.print_exc()

    def save(self) -> None:
        """Write the sizes to `path' atomically.

        A failure (read-only directory, full disk) is reported and otherwise
        ignored: the popup keeps the size for this session.
        """
        directory = os.path.dirname(self.path)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as sizes_file:
                json.dump(self.sizes, sizes_file, ensure_ascii=False, sort_keys=True)
                sizes_file.write("\n")
            os.replace(temporary, self.path)
        except OSError:
            traceback.print_exc()
