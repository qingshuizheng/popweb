;;; popweb-color-picker.el --- Colour picker popup for popweb  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2021-11-15
;; Keywords: tools, faces
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
;; `popweb-color-picker-show' looks at point for a colour in one of the three
;; spellings CSS uses -- a hex literal such as #1e90ff, a colour name such as
;; "rebeccapurple", or a function such as rgb(30 144 255) -- and opens a Qt
;; colour picker initialised with it.  The picker is a web page (coloris.js),
;; so it can be used from any buffer, not just CSS.
;;
;; The popup closes on the next command, one second after it appeared; the
;; delay is what keeps the command that opened it from closing it again.

;;; Code:

(require 'css-mode)

(require 'popweb)

(defvar popweb-color-picker-index-path
  (expand-file-name "index.html" (file-name-directory (or load-file-name
                                                          buffer-file-name)))
  "Absolute file name of the HTML page of the colour picker.")

(defvar popweb-color-picker-module-path
  (expand-file-name "color-picker.py" (file-name-directory (or load-file-name
                                                               buffer-file-name)))
  "Absolute file name of the Python module of the colour picker.")

(defvar popweb-color-picker-web-window-visible-p nil
  "Whether the colour picker popup may be hidden by the next command.")

(defvar popweb-color-picker--hex-color-regexp
  (concat
   ;; Short hex.  css-color-4 adds alpha.
   "\\(#[0-9a-fA-F]\\{3,4\\}\\b\\)"
   "\\|"
   ;; Long hex.  css-color-4 adds alpha.
   "\\(#\\(?:[0-9a-fA-F][0-9a-fA-F]\\)\\{3,4\\}\\b\\)")
  "Regexp that matches a three, four, six or eight digit hex colour.")

;;;###autoload
(defun popweb-color-picker-show ()
  "Show a colour picker initialised with the colour at point.
The colour may be a hex literal, a CSS colour name, or an rgb()/hsl()
function; an empty picker is shown when point is not on a colour."
  (interactive)
  (let* ((position (popweb-get-cursor-coordinate))
         (window-header-height (- (nth 1 (window-inside-pixel-edges))
                                  (nth 1 (window-absolute-pixel-edges))))
         (x (car position))
         (y (- (cdr position) window-header-height))
         (x-offset (popweb-get-cursor-x-offset))
         (y-offset (popweb-get-cursor-y-offset))
         (frame-x (car (frame-position)))
         (frame-y (cdr (frame-position)))
         (frame-w (frame-outer-width))
         (frame-h (frame-outer-height))
         (color-info (or (popweb-color-picker--get-hex-color-at-point)
                         (popweb-color-picker--get-named-color-at-point)
                         (popweb-color-picker--get-rgb-or-hsl-color-at-point))))
    (popweb-call-async "call_module_method" popweb-color-picker-module-path
                       "pop_color_picker_window"
                       (list
                        "color-picker" popweb-color-picker-index-path
                        x y x-offset y-offset
                        frame-x frame-y frame-w frame-h
                        (if color-info (car color-info) "")))

    (popweb-color-picker-web-window-can-hide)

    (add-hook 'post-command-hook #'popweb-color-picker-web-window-hide-after-move)))

(defun popweb-color-picker--get-named-color-at-point ()
  "Return the CSS colour name at point, as (NAME . BOUNDS), or nil.
The name is looked up in `css--color-map', so only names the browser knows
are recognised; the match is case insensitive."
  (when-let* ((word (word-at-point t))
              (color (assoc (downcase word) css--color-map)))
    (cons word (bounds-of-thing-at-point 'word))))

(defun popweb-color-picker--get-rgb-or-hsl-color-at-point ()
  "Return the rgb()/hsl() colour at point, as (TEXT . BOUNDS), or nil.
Both the modern space separated form and the legacy comma separated form are
accepted, with or without an alpha channel."
  (save-excursion
    (when-let* ((open-paren-pos (nth 1 (syntax-ppss))))
      (when (save-excursion
              (goto-char open-paren-pos)
              (looking-back "\\(?:hsl\\|rgb\\)a?" (- (point) 4)))
        (goto-char (nth 1 (syntax-ppss)))))
    (when (eq (char-before) ?\))
      (backward-sexp))
    (skip-chars-backward "rgbhslaRGBHSLA")
    (when (looking-at "\\(\\_<\\(?:hsl\\|rgb\\)a?(\\)")
      (when-let* ((start (point))
                  (end (search-forward ")" nil t)))
        (cons (buffer-substring-no-properties start end) (cons start end))))))

(defun popweb-color-picker--get-hex-color-at-point ()
  "Return the hex colour at point, as (TEXT . BOUNDS), or nil.
Short and long forms, with or without an alpha channel, are recognised."
  (with-syntax-table (copy-syntax-table (syntax-table))
    (modify-syntax-entry ?# "w")        ; Make `#' a word constituent.
    (when-let* ((word (thing-at-point 'word t))
                (bounds (bounds-of-thing-at-point 'word)))
      (when (string-match popweb-color-picker--hex-color-regexp word)
        (cons word bounds)))))

(defun popweb-color-picker-web-window-hide-after-move ()
  "Close the colour picker popup if it is allowed to close.
It is also removed from `post-command-hook', so a closed popup never costs
another hook run."
  (when (and popweb-color-picker-web-window-visible-p
             (popweb-epc-live-p popweb-epc-process))
    (popweb-call-async "hide_web_window" "color-picker")
    (setq popweb-color-picker-web-window-visible-p nil)
    (remove-hook 'post-command-hook
                 #'popweb-color-picker-web-window-hide-after-move)))

(defun popweb-color-picker-web-window-can-hide ()
  "Allow the colour picker popup to be hidden one second from now.
The delay lets the command that opened the popup finish before the popup
becomes closable."
  (run-with-timer 1 nil (lambda ()
                          (setq popweb-color-picker-web-window-visible-p t))))

(provide 'popweb-color-picker)
;;; popweb-color-picker.el ends here
