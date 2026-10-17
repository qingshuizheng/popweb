;;; popweb-url.el --- URL preview popup for popweb  -*- lexical-binding: t; -*-

;; Copyright (C) 2022 Qiqi Jin
;;
;; Author: Qiqi Jin <ginqi7@gmail.com>
;; Maintainer: Qiqi Jin <ginqi7@gmail.com>
;; Created: 2022-01-25
;; Keywords: tools, hypermedia
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
;; `popweb-url-preview-pointer' shows the URL at point in a Qt window without
;; leaving Emacs, and `popweb-url-input' does the same for a URL read from the
;; minibuffer.  The window is an ordinary web view, so it can be scrolled and
;; followed like a browser tab; the next command closes it.
;;
;; A local file URL such as file:notes.html is resolved against the directory
;; of the current buffer before it is loaded, which makes previews work from
;; an Org file that links to its exported HTML.

;;; Code:

(require 'popweb)

(defvar popweb-url-module-path
  (expand-file-name "popweb-url.py" (file-name-directory (or load-file-name
                                                             buffer-file-name)))
  "Absolute file name of the Python module of the URL preview.")

(defvar popweb-url-web-window-visible-p nil
  "Whether the URL preview popup may be hidden by the next command.")

(defvar popweb-url-regexp
  "\\b\\(\\(www\\.\\|\\(s?https?\\|ftp\\|file\\|gopher\\|gemini\\|nntp\\|news\\|telnet\\|wais\\|mailto\\|info\\):\\)\\(//[-a-z0-9_.]+:[0-9]*\\)?\\(?:[-a-z0-9_=#$@~%&*+\\/[:word:]!?:;.,]+([-a-z0-9_=#$@~%&*+\\/[:word:]!?:;.,]+)\\(?:[-a-z0-9_=#$@~%&*+\\/[:word:]!?:;.,]+[-a-z0-9_=#$@~%&*+\\/[:word:]]\\)?\\|[-a-z0-9_=#$@~%&*+\\/[:word:]!?:;.,]+[-a-z0-9_=#$@~%&*+\\/[:word:]]\\)\\)"
  "Regexp that matches the URLs this previewer knows how to open.")

(defcustom popweb-url-web-window-width-scale 0.8
  "Width of the URL preview as a fraction of the Emacs frame's width.
Used only when `popweb-url-web-window-size-use-absolute' is nil."
  :type 'number
  :group 'popweb)

(defcustom popweb-url-web-window-height-scale 0.45
  "Height of the URL preview as a fraction of the Emacs frame's height.
Used only when `popweb-url-web-window-size-use-absolute' is nil."
  :type 'number
  :group 'popweb)

(defcustom popweb-url-web-window-width-absolute 480
  "Width of the URL preview in pixels.
Used only when `popweb-url-web-window-size-use-absolute' is non-nil."
  :type 'integer
  :group 'popweb)

(defcustom popweb-url-web-window-height-absolute 270
  "Height of the URL preview in pixels.
Used only when `popweb-url-web-window-size-use-absolute' is non-nil."
  :type 'integer
  :group 'popweb)

(defcustom popweb-url-web-window-size-use-absolute t
  "Whether the URL preview uses absolute pixel sizes.
When this is nil the window scales with the Emacs frame instead; see
`popweb-url-web-window-width-scale' and
`popweb-url-web-window-height-scale'."
  :type 'boolean
  :group 'popweb)

(defun popweb-url-local-file-url-completion (url)
  "Turn the relative local file URL URL into an absolute one.
A URL that does not start with \"file:\", and a buffer without a file name,
are returned unchanged."
  (let ((current-path
         (when (buffer-file-name)
           (file-name-directory (buffer-file-name)))))
    (replace-regexp-in-string "^file:"
                              (concat "file:" current-path)
                              url)))

(defun popweb-get-url ()
  "Return the URL at point, or the first URL on the current line, or nil.
The URL is completed against the buffer's directory when it is a local file.
This function keeps its upstream name, without the double dash, because
users and extensions call it directly."
  (let* ((url (thing-at-point 'url))
         (url
          (if url url
            (popweb-current-line-url
             (- (point) (line-beginning-position)))))
         (url (if url url (popweb-current-line-url 0))))
    (when url (popweb-url-local-file-url-completion url))))

(defun popweb-current-line-url (start)
  "Return the first URL on the current line that starts at or after START.
START is a column in the current line, not a buffer position."
  (let* ((current-line (thing-at-point 'line t)))
    (when (string-match popweb-url-regexp current-line start)
      (match-string 0 current-line))))

(defun popweb-url-prompt-input (prompt)
  "Read a URL from the minibuffer, using PROMPT as the label.
The URL at point, when there is one, is offered as the initial value."
  (read-string
   (format "%s(%s): " prompt (or (popweb-get-url) ""))
   nil nil
   (popweb-get-url)))

(defun popweb-url-web-window-hide-after-move ()
  "Close the URL preview popup if it is allowed to close.
It is also removed from `post-command-hook'."
  (when (and popweb-url-web-window-visible-p
             (popweb-epc-live-p popweb-epc-process))
    (popweb-call-async "hide_web_window" "url-preview")
    (setq popweb-url-web-window-visible-p nil)
    (remove-hook 'post-command-hook #'popweb-url-web-window-hide-after-move)))

(defun popweb-url (info)
  "Show the URL preview for INFO.
INFO is a list whose first element is the URL to load; the rest of the popup
request is built from the cursor and frame geometry."
  (let* ((position (popweb-get-cursor-coordinate))
         (window-header-height
          (-
           (nth 1 (window-inside-pixel-edges))
           (nth 1 (window-absolute-pixel-edges))))
         (x (car position))
         (y (- (cdr position) window-header-height))
         (x-offset (popweb-get-cursor-x-offset))
         (y-offset (popweb-get-cursor-y-offset))
         (frame-x (car (frame-position)))
         (frame-y (cdr (frame-position)))
         (frame-w (frame-outer-width))
         (frame-h (frame-outer-height))
         (url (nth 0 info)))
    (popweb-call-async "call_module_method" popweb-url-module-path
                       "pop_url_window"
                       (list
                        "url-preview"
                        x y x-offset y-offset
                        frame-x frame-y frame-w frame-h
                        popweb-url-web-window-width-scale
                        popweb-url-web-window-height-scale
                        popweb-url-web-window-width-absolute
                        popweb-url-web-window-height-absolute
                        popweb-url-web-window-size-use-absolute
                        url))
    (popweb-url-web-window-can-hide)))

;;;###autoload
(defun popweb-url-input (&optional url)
  "Read a URL from the minibuffer and preview it.
When URL is non-nil it is previewed directly and the minibuffer is skipped."
  (interactive)
  (popweb-start #'popweb-url
                (list
                 (or url (popweb-url-prompt-input "preview url: "))))
  (add-hook 'post-command-hook #'popweb-url-web-window-hide-after-move))

;;;###autoload
(defun popweb-url-preview-pointer ()
  "Preview the URL at point."
  (interactive)
  (popweb-start #'popweb-url (list (popweb-get-url)))
  (add-hook 'post-command-hook #'popweb-url-web-window-hide-after-move))

(defun popweb-url-web-window-can-hide ()
  "Allow the URL preview popup to be hidden one second from now.
The delay lets the command that opened the popup finish first."
  (run-with-timer 1 nil
                  (lambda ()
                    (setq popweb-url-web-window-visible-p t))))

(provide 'popweb-url)
;;; popweb-url.el ends here
