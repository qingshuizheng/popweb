;;; popweb-latex.el --- KaTeX preview of the math at point  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2021-11-15
;; Keywords: tools, tex
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
;; `popweb-latex-mode' keeps a small Qt window next to the cursor that shows
;; the formula at point, rendered by KaTeX.  The window follows point while
;; the mode is on: the post-command hook re-renders only when the formula
;; changes, and the window hides when point leaves math, when the buffer
;; changes, or when the frame loses focus.
;;
;; Two input paths exist, both from `math-at-point.el': AUCTeX's `texmathp'
;; in latex-mode, and Org's element API in org-mode (fragments, environments
;; and latex source blocks).  The HTML page is `index.html' in this directory;
;; KaTeX itself is vendored next to it, so no network access is needed.

;;; Code:

(require 'popweb)
(require 'math-at-point)

(defgroup popweb-latex nil
  "KaTeX previews shown by popweb."
  :group 'popweb
  :prefix "popweb-latex-")

(defvar popweb-latex-index-path
  (expand-file-name "index.html" (file-name-directory (or load-file-name
                                                          buffer-file-name)))
  "Absolute file name of the HTML page that renders the formula.")

(defvar popweb-latex-module-path
  (expand-file-name "popweb-latex.py" (file-name-directory (or load-file-name
                                                              buffer-file-name)))
  "Absolute file name of the Python module of the LaTeX preview.")

(defvar popweb-latex-popup-foreground nil
  "Whether the LaTeX popup is currently shown.
It is the guard that keeps `popweb-latex-hide' from sending a hide request
for a window that is already hidden.")

(defun popweb-latex-preview (info)
  "Show the LaTeX preview described by INFO.
INFO is a list of the visibility flag and the TeX source; it is what the
first-start callback of `popweb-start' receives."
  (setq popweb-latex-popup-foreground t)
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
         (latex-string (nth 1 info))
         (new-latex (not (string= latex-string
                                  webkit-katex-render--previous-math))))
    (popweb-call-async "call_module_method" popweb-latex-module-path
                       "pop_latex_window"
                       (list
                        "latex" popweb-latex-index-path
                        x y x-offset y-offset
                        frame-x frame-y frame-w frame-h
                        show-window new-latex latex-string))))

;;;###autoload
(defun popweb-latex-show ()
  "Show the formula at point and start following point.
When point is not on a formula, a placeholder formula is shown instead, which
keeps the window geometry stable while the user moves into one."
  (interactive)
  (let* ((math-at-point (webkit-katex-render--math-at-point))
         (latex-string (nth 1 math-at-point)))
    (if latex-string
        (if (not (eq latex-string webkit-katex-render--previous-math))
            (progn
              (popweb-start #'popweb-latex-preview
                            (list t
                                  (replace-regexp-in-string
                                   "\\\\" "\\\\" latex-string t t)))
              (setq webkit-katex-render--previous-math latex-string)))
      (popweb-start #'popweb-latex-preview (list nil "e^{i\\\\pi}+1=0"))))
  (add-hook 'post-command-hook #'popweb-latex-update nil t))

;;;###autoload
(defun popweb-latex-update ()
  "Re-render the formula at point, or hide the popup when there is none.
The request is skipped when the formula did not change since the last
render, which is what keeps the popup from flickering on every command."
  (interactive)
  (when (popweb-epc-live-p popweb-epc-process)
    (setq popweb-latex-popup-foreground t)
    (let* ((math-at-point (webkit-katex-render--math-at-point))
           (latex-string (nth 1 math-at-point))
           (position (popweb-get-cursor-coordinate))
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
           (new-latex (not (string= latex-string
                                    webkit-katex-render--previous-math))))
      (if (and position latex-string)
          (progn
            (let* ((no-label (replace-regexp-in-string
                              "\\\\label{.*}" "" latex-string t t))
                   (escaped (replace-regexp-in-string "\\\\" "\\\\" no-label t t))
                   (single-line (replace-regexp-in-string "\n" "" escaped t t)))
              (popweb-call-async "call_module_method" popweb-latex-module-path
                                 "pop_latex_window"
                                 (list
                                  "latex" popweb-latex-index-path
                                  x y x-offset y-offset
                                  frame-x frame-y frame-w frame-h
                                  t
                                  new-latex
                                  single-line)))
            (setq webkit-katex-render--previous-math latex-string))
        (popweb-latex-hide)))))

;;;###autoload
(defun popweb-latex-hide ()
  "Hide the LaTeX popup if it is shown."
  (interactive)
  (when popweb-latex-popup-foreground
    (setq webkit-katex-render--previous-math nil)
    (setq popweb-latex-popup-foreground nil)
    (ignore-errors
      (popweb-call-async "hide_web_window" "latex"))))

(defun popweb-latex-hide-after-switch-buffer ()
  "Hide the LaTeX popup after a window state change.
The popup is only hidden when `popweb-latex-mode' is no longer on for the
current buffer, so moving between windows of the same buffer keeps it."
  (when (not (bound-and-true-p popweb-latex-mode))
    (popweb-latex-hide)))

(defun popweb-latex-hide-after-lose-focus ()
  "Update the LaTeX popup when the frame regains focus, hide it when it loses it."
  (if (frame-focus-state)
      (popweb-latex-update)
    (popweb-latex-hide)))

;;;###autoload
(define-minor-mode popweb-latex-mode
  "Show the LaTeX formula at point in a popup, and keep it in sync.
The popup follows point with `popweb-latex-update', hides when point leaves
math, and hides when the frame loses focus.  It needs AUCTeX in `latex-mode'
and is built into Org's own math support in `org-mode'."
  :group 'popweb-latex
  (if popweb-latex-mode
      (progn
        (popweb-latex-show)
        (add-hook 'window-state-change-hook
                  #'popweb-latex-hide-after-switch-buffer)
        (add-function :after after-focus-change-function
                      #'popweb-latex-hide-after-lose-focus))
    (remove-hook 'window-state-change-hook
                 #'popweb-latex-hide-after-switch-buffer)
    (remove-hook 'post-command-hook #'popweb-latex-update t)
    (remove-function after-focus-change-function
                     #'popweb-latex-hide-after-lose-focus)
    (popweb-latex-hide)))

(provide 'popweb-latex)
;;; popweb-latex.el ends here
