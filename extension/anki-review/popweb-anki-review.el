;;; popweb-anki-review.el --- Anki review popup for popweb  -*- lexical-binding: t; -*-

;; Copyright (C) 2022 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2022-01-25
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
;; `popweb-anki-review-show' opens a Qt window that contains the Anki cards
;; matching a word or sentence, using Anki's own search syntax.  Selecting a
;; word inside the popup searches for it, which is what makes the window
;; usable for reading a card and then looking up an unknown word without
;; leaving Emacs.
;;
;; The search itself runs through the AnkiConnect add-on on
;; http://127.0.0.1:8765; the Python side of this extension talks to it and
;; the Qt web channel carries the commands from the page back to Python.  Anki
;; must be running with AnkiConnect installed.
;;
;; The query is the active region when there is one, the sentence at point
;; when it is called with a prefix argument, or a string read from the
;; minibuffer otherwise.

;;; Code:

(require 'cl-lib)
(require 'rx)
(require 'subr-x)

(require 'popweb)

(defgroup popweb-anki-review nil
  "Anki review popups shown by popweb."
  :group 'popweb
  :prefix "popweb-anki-review-")

(defvar popweb-anki-review-sentence nil
  "Query of the review popup that is currently shown.
It is global because the popup outlives the buffer it was opened from.")

(defvar popweb-anki-review-preview--previous-query nil
  "Query that the Python side has already rendered.
It selects between refreshing an existing window and resetting it.")

(defvar popweb-anki-review-preview-window-visible-p nil
  "Whether the Anki review popup may be hidden by the next command.")

(defvar popweb-anki-review-tooltip-file
  (expand-file-name "tooltip.js" (if load-file-name
                                    (file-name-directory load-file-name)
                                  default-directory))
  "Absolute file name of the JavaScript that draws the search tooltips.")

(defvar popweb-anki-review-index-path
  (expand-file-name "index.html" (file-name-directory (or load-file-name
                                                          buffer-file-name)))
  "Absolute file name of the HTML page of the review popup.")

(defvar popweb-anki-review-module-path
  (expand-file-name "popweb-anki-review.py"
                    (file-name-directory (or load-file-name buffer-file-name)))
  "Absolute file name of the Python module of the review popup.")

(defcustom popweb-anki-review-popup-window-width-scale 0.8
  "Width of the review popup as a fraction of the Emacs frame's width."
  :type 'number
  :group 'popweb-anki-review)

(defcustom popweb-anki-review-popup-window-height-scale 0.5
  "Height of the review popup as a fraction of the Emacs frame's height."
  :type 'number
  :group 'popweb-anki-review)

(defcustom popweb-anki-review-media-directory nil
  "Directory where Anki keeps the media files of its notes.
It is used to play the [sound:...] tags of a card; leave it nil when
pronunciation inside the popup is not needed."
  :type '(choice (const :tag "Do not play sounds" nil)
                 (directory :tag "Anki media directory"))
  :group 'popweb-anki-review)

(defcustom popweb-anki-review-callback nil
  "Function name that the popup calls on a dictionary search.
The name is a string, because it is evaluated on the Emacs side by name;
see `popweb--eval-in-emacs-func'."
  :type '(choice (const :tag "No callback" nil)
                 (string :tag "Emacs function name"))
  :group 'popweb-anki-review)

(defcustom popweb-anki-review-eww-sentence-abbrevs '("i.e." "etc." "U.S.")
  "Abbreviations that must not end a sentence in `eww-mode'.
The sentence detection uses them to look further for a real full stop."
  :type '(repeat string)
  :group 'popweb-anki-review)

(defcustom popweb-anki-review-eww-sentence-ends
  (rx (or (and "." (or " " eol))
          (and "?" (or " " eol))
          (and "!" (or " " eol))
          (and ";" (or " " eol))
          "\n\n"))
  "Regexp that matches the end of a sentence in `eww-mode'.
The default covers the punctuation an English sentence can end with, plus a
blank line.  The abbreviations in
`popweb-anki-review-eww-sentence-abbrevs' are checked first."
  :type 'regexp
  :group 'popweb-anki-review)

(defun popweb-anki-review--sentence ()
  "Return the sentence around point, in `eww-mode' or in a text buffer.
In `eww-mode' the sentence is found with
`popweb-anki-review--eww-sentence', which knows about the way eww lays text
out; elsewhere `thing-at-point' does the work."
  (let (sentence)
    (cond
     ((derived-mode-p 'eww-mode)
      (setq sentence (popweb-anki-review--eww-sentence)))
     (t
      (setq sentence (thing-at-point 'sentence t))))
    sentence))

(defun popweb-anki-review--string-ends-with-any (str patterns)
  "Return non-nil when STR ends with one of PATTERNS, ignoring case.
The comparison is done with `string-suffix-p', so an empty PATTERNS list
returns nil."
  (cl-dolist (p patterns)
    (when (string-suffix-p p str t)
      (cl-return t))))

(defun popweb-anki-review--eww-sentence ()
  "Return the sentence around point in an `eww-mode' buffer.
The search walks forward to a sentence end and backward to the previous one,
skipping the ends that are really abbreviations."
  (let ((sentence-ends popweb-anki-review-eww-sentence-ends)
        (point (point))
        (stop nil)
        start end)
    (save-excursion
      (while (not stop)
        (setq end (search-forward-regexp sentence-ends nil t))
        (if (not end)
            (setq end (point-max)
                  stop t)
          (unless (popweb-anki-review--string-ends-with-any
                   (buffer-substring-no-properties point (- end 1))
                   popweb-anki-review-eww-sentence-abbrevs)
            (setq stop t))))

      (setq stop nil)
      (goto-char point)
      (while (not stop)
        (setq start (search-backward-regexp sentence-ends nil t))
        (if (not start)
            (setq start (point-min)
                  stop t)
          (unless (popweb-anki-review--string-ends-with-any
                   (buffer-substring-no-properties (line-beginning-position) (1+ start))
                   popweb-anki-review-eww-sentence-abbrevs)
            (setq stop t)
            (setq start (1+ start))))))
    (string-trim (buffer-substring-no-properties start end))))

(defun popweb-anki-review-region-or-sentence ()
  "Return the active region, or the sentence around point.
The result has no text properties, so it is safe to put into an Anki query."
  (if mark-active
      (buffer-substring-no-properties (region-beginning)
                                      (region-end))
    (popweb-anki-review--sentence)))

(defun popweb-anki-review-preview (info)
  "Show the Anki review popup for INFO.
INFO is a list of the window flag and the query: the flag says whether the
popup should become visible, and the query is the Anki search to run."
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
         (show-window (nth 0 info))
         (emacs-query (nth 1 info))
         (script-file popweb-anki-review-tooltip-file)
         (media-directory popweb-anki-review-media-directory)
         (callback popweb-anki-review-callback)
         (new-query-p (not (string= emacs-query
                                    popweb-anki-review-preview--previous-query))))
    (popweb-call-sync "call_module_method" popweb-anki-review-module-path
                      "pop_anki_review_window"
                      (list
                       popweb-anki-review-module-path
                       "anki_review"
                       popweb-anki-review-index-path
                       x y x-offset y-offset
                       frame-x frame-y frame-w frame-h
                       popweb-anki-review-popup-window-width-scale
                       popweb-anki-review-popup-window-height-scale
                       show-window script-file media-directory
                       new-query-p emacs-query
                       callback))
    (popweb-anki-review-preview-window-can-hide)))

(defun popweb-anki-review-preview-window-can-hide ()
  "Allow the review popup to be hidden one second from now.
The delay lets the command that opened the popup finish first."
  (run-with-timer 1 nil
                  (lambda ()
                    (setq popweb-anki-review-preview-window-visible-p t))))

;;;###autoload
(defun popweb-anki-review-show (&optional arg)
  "Show the Anki review popup for the current context.
With a prefix argument ARG, start from the sentence at point even when a
region is active; otherwise the active region is used when there is one, and
the sentence at point is used when ARG is given.  Without either, read the
query from the minibuffer."
  (interactive "P")

  (setq popweb-anki-review-sentence
        (if (or mark-active arg)
            (or (popweb-anki-review-region-or-sentence) "")
          ""))

  (while (string-equal popweb-anki-review-sentence "")
    (setq popweb-anki-review-sentence
          (read-string "Please input the word or sentence to review: "
                       nil nil "" nil)))

  (setq popweb-anki-review-sentence
        (replace-regexp-in-string "[\t\n\r]+" " " popweb-anki-review-sentence))

  (message "[popweb-anki-review] to review: '%s'" popweb-anki-review-sentence)

  (if popweb-anki-review-sentence
      (progn
        (setq popweb-anki-review-preview--previous-query
              popweb-anki-review-sentence)
        (if popweb-anki-review-preview-window-visible-p
            (progn
              (setq popweb-anki-review-preview-window-visible-p nil)
              (ignore-errors
                (popweb-call-async "hide_web_window" "anki_review"))))
        (popweb-start #'popweb-anki-review-preview
                      (list t popweb-anki-review-sentence)))
    (popweb-start #'popweb-anki-review-preview (list nil "Hello world")))
  (add-hook 'post-command-hook
            #'popweb-anki-review-preview-window-hide-after-move))

(defun popweb-anki-review-preview-window-hide-after-move ()
  "Close the Anki review popup if it is allowed to close.
The previous query is forgotten as well, so the next popup starts clean."
  (when (and popweb-anki-review-preview-window-visible-p
             (popweb-epc-live-p popweb-epc-process))
    (setq popweb-anki-review-preview--previous-query nil)
    (setq popweb-anki-review-preview-window-visible-p nil)
    (ignore-errors
      (popweb-call-async "hide_web_window" "anki_review"))
    (remove-hook 'post-command-hook
                 #'popweb-anki-review-preview-window-hide-after-move)))

(provide 'popweb-anki-review)
;;; popweb-anki-review.el ends here
