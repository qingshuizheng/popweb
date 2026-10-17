;;; popweb-config.el --- User options of popweb  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2021-11-13
;; Keywords: tools
;; URL: https://github.com/manateelazycat/popweb
;; Package-Requires: ((emacs "27.1"))

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
;; Every user option of popweb lives in this file, and nowhere else, so that
;; the modules that act on them never have to guess where a variable is
;; defined.  Nothing here starts a process or touches a window.

;;; Code:

(defgroup popweb nil
  "Popup web windows rendered by a separate Python process.
The Emacs side owns the position and the lifetime of a popup, the Python side
owns the Qt window and the web page it shows."
  :group 'applications
  :prefix "popweb-"
  :link '(url-link "https://github.com/manateelazycat/popweb"))

(defcustom popweb-name "*popweb*"
  "Name of the buffer that collects the output of the Python process.
The buffer also holds the process itself, so `popweb-kill-process' can find
and delete it without knowing any other name."
  :type 'string
  :group 'popweb)

(defcustom popweb-python-command
  (if (memq system-type '(cygwin windows-nt ms-dos)) "python.exe" "python3")
  "Python interpreter used to run popweb.py.
The interpreter must be able to `import PyQt6' and `import epc'.  A Nix build
of popweb writes this option to point at the interpreter that carries those
dependencies instead of the one that happens to be on PATH."
  :type 'string
  :group 'popweb)

(defcustom popweb-proxy-host ""
  "Host name of the proxy the popup pages go through.
An empty string, together with an empty `popweb-proxy-port', disables the
proxy entirely."
  :type 'string
  :group 'popweb)

(defcustom popweb-proxy-port ""
  "Port of the proxy the popup pages go through, as a string.
The value is converted to an integer by the Python side before it reaches Qt,
so a port number is accepted both with and without surrounding spaces."
  :type 'string
  :group 'popweb)

(defcustom popweb-proxy-type ""
  "Type of the proxy the popup pages go through.
The value is either \"http\" or \"socks5\".  Any other value leaves the proxy
off, because the Python side only knows how to map those two names to Qt."
  :type '(choice (const :tag "No proxy" "")
                 (const "http")
                 (const "socks5"))
  :group 'popweb)

(defcustom popweb-popup-pos "point-bottom-right"
  "Where a popup is placed on the screen.
The position is computed by the Python side from the cursor coordinate and
the frame geometry that Emacs sends with every popup request.  Available
values are:

- \"point-bottom\": centered below the cursor.
- \"point-bottom-right\": below the cursor, growing to the right.
- \"top-left\": the top left corner of the Emacs frame.
- \"top-right\": the top right corner of the Emacs frame.
- \"bottom-left\": the bottom left corner of the Emacs frame.
- \"bottom-right\": the bottom right corner of the Emacs frame.
- \"middle\": the center of the Emacs frame."
  :type '(choice (const "point-bottom")
                 (const "point-bottom-right")
                 (const "top-left")
                 (const "top-right")
                 (const "bottom-left")
                 (const "bottom-right")
                 (const "middle"))
  :group 'popweb)

(defcustom popweb-enable-debug nil
  "Whether to start the Python process under gdb.
Turn this on only when the process crashes: popweb then runs gdb in batch
mode, prints a backtrace after the crash, and leaves the full output in the
`popweb-name' buffer for the bug report."
  :type 'boolean
  :group 'popweb)

(defcustom popweb-enable-developer-tools nil
  "Whether to open the Qt web developer tools next to every popup.
The tools window is created for every popup regardless; this option only
decides whether it is shown and attached to the page."
  :type 'boolean
  :group 'popweb)

(defcustom popweb-start-python-process-when-require t
  "Whether to start the Python process when popweb is loaded.
Starting it one second after load moves the interpreter and Qt startup cost
out of the first popup, at the price of one idle process per Emacs session.
Set this to nil when the process is only needed rarely, or in tests."
  :type 'boolean
  :group 'popweb)

(defcustom popweb-zoom-factor 1
  "Zoom factor applied to the web page of every popup.
The Python side multiplies it by two on screens wider than 3000 pixels, so a
value around 1 is readable on both a laptop and a high resolution monitor."
  :type 'number
  :group 'popweb)

(defcustom popweb-config-location (expand-file-name (locate-user-emacs-file "popweb/"))
  "Directory where popweb stores its configuration files.
The Python side creates it on demand and keeps imported cookies in a
`browser/cookies' subdirectory.  The value must be absolute: it is passed to
Python verbatim."
  :type 'directory
  :group 'popweb)

(provide 'popweb-config)
;;; popweb-config.el ends here
