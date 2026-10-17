;;; popweb-geometry.el --- Where a popup goes and what colour it gets  -*- lexical-binding: t; -*-

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
;; The values an extension needs before it can ask Python for a popup: where
;; the cursor is, how far to shift the window from it, and what the current
;; theme looks like.  All of them are pure reads of the selected frame, which
;; is why they can be tested without starting a process.
;;
;; The final placement of the window is decided on the Python side
;; (`core/geometry.py'), from these values and the configured position; this
;; file only reports the facts.

;;; Code:

(defun popweb-get-cursor-coordinate ()
  "Return the absolute pixel coordinate of the cursor as (X . Y).
Inside an EAF buffer the mouse position is the only reliable anchor, because
EAF draws its own cursor; everywhere else the window's text cursor is."
  (if (derived-mode-p 'eaf-mode)
      (mouse-absolute-pixel-position)
    (window-absolute-pixel-position)))

(defun popweb-get-cursor-x-offset ()
  "Return how far a popup is shifted to the right of the cursor anchor.
EAF pages are full-window buffers, so their popups start 30 pixels in; an
ordinary Emacs buffer starts at the text cursor itself."
  (if (derived-mode-p 'eaf-mode)
      30
    0))

(defun popweb-get-cursor-y-offset ()
  "Return how far a popup is shifted below the cursor anchor.
The offset is one line for a text buffer, so the popup does not cover the
line the point is on, and 30 pixels inside an EAF buffer."
  (if (derived-mode-p 'eaf-mode)
      30
    (line-pixel-height)))

(defun popweb-get-theme-mode ()
  "Return the background mode of the selected frame, as a string.
The result is \"dark\" or \"light\"; Python uses it to decide whether to run
Dark Reader on the page."
  (format "%s" (frame-parameter nil 'background-mode)))

(defun popweb-get-theme-background ()
  "Return the background colour of the default face as \"#RRGGBB\".
Python paints the page with it before the first frame is shown, which is what
keeps a slow page load from flashing white in a dark theme."
  (popweb-color-name-to-hex (face-attribute 'default :background)))

(defun popweb-color-int-to-hex (int)
  "Return the low two hexadecimal digits of the colour component INT.
Emacs reports colour components on a 16-bit scale, while the web pages use
8-bit channels, so only the low byte is meaningful here; see
`popweb-color-name-to-hex' for how it is used."
  (substring (format (concat "%0" (int-to-string 4) "X") int) (- 2)))

(defun popweb-color-name-to-hex (color)
  "Return the colour named COLOR as a \"#RRGGBB\" string.
COLOR is anything `color-values' accepts, such as a face attribute value or a
colour name.  A frame that cannot resolve the colour yields \"#000000\"."
  (let ((components (color-values color)))
    (if components
        (concat "#"
                (popweb-color-int-to-hex (nth 0 components))
                (popweb-color-int-to-hex (nth 1 components))
                (popweb-color-int-to-hex (nth 2 components)))
      "#000000")))

(provide 'popweb-geometry)
;;; popweb-geometry.el ends here
