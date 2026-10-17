;;; popweb.el --- Popup web windows inside Emacs  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2021-11-13
;; Keywords: tools, multimedia
;; URL: https://github.com/manateelazycat/popweb
;; Package-Requires: ((emacs "27.1"))
;; Version: 0.5

;; This file is not part of GNU Emacs.

;;; License:
;;
;; This program is free software; you can redistribute it and/or modify
;; it under the terms of the GNU General Public License as published by
;; the Free Software Foundation, either version 3 of the License, or
;; (at your option) any later version.
;;
;; This program is distributed in the hope that it will be useful,
;; but WITHOUT ANY WARRANTY; without even the implied warranty of
;; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;; GNU General Public License for more details.
;;
;; You should have received a copy of the GNU General Public License
;; along with this program; see the file COPYING.  If not, write to the
;; Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor,
;; Boston, MA 02110-1301, USA.

;;; Commentary:
;;
;; Popweb shows a frameless Qt window, rendered by a separate Python process,
;; next to the cursor.  The window can display anything a web page can:
;; translations, LaTeX, a colour picker, a URL preview, an Anki card.  Each of
;; those is an extension under `extension/', and this file is the public
;; surface they share.
;;
;; The public entry points are:
;;
;; - `popweb-start', which takes a callback and its arguments and guarantees
;;   that the Python process exists before the callback runs.
;; - `popweb-call-async' and `popweb-call-sync', which call a Python method.
;; - `popweb-restart-process', `popweb-kill-process', and
;;   `popweb-import-browser-cookies' for the process and cookie lifecycle.
;;
;; Options live in `popweb-config.el', the process in `popweb-process.el', the
;; wire format in `popweb-ipc.el', and the geometry helpers in
;; `popweb-geometry.el'.  This file only loads them and keeps the autoloaded
;; commands in one place.

;;; Code:

(require 'popweb-config)
(require 'popweb-ipc)
(require 'popweb-process)
(require 'popweb-geometry)

;;;###autoload
(defun popweb-import-browser-cookies (browser domain-name)
  "Import the cookies of BROWSER for DOMAIN-NAME into popweb.
BROWSER is one of the names that `browser_cookie3' knows; the cookies are
written to `popweb-config-location' and are loaded by the next popup that
visits the domain."
  (interactive (list (completing-read "Which browser ? "
                                      '("chrome" "chromium" "opera" "opera_gx"
                                        "brave" "edge" "vivaldi" "firefox"
                                        "safari")
                                      nil t)
                     (read-string "Domain name: ")))
  (popweb-start #'(lambda (&rest _)
                    (popweb-call-async "import_browser_cookies" browser domain-name))
                nil))

;;;###autoload
(defun popweb-forget-window-sizes ()
  "Forget popup sizes set by dragging, so extensions size them again.
The size a user drags is remembered per extension module for the rest of the
session.  This command returns the choice to the extensions; it only needs the
Python process for windows that already exist."
  (interactive)
  (popweb-start (lambda (&rest _)
                  (popweb-call-async "forget_window_sizes"))
                nil))

(provide 'popweb)
;;; popweb.el ends here
