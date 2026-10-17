;;; math-at-point.el --- Find the LaTeX math around point  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 fuxialexander
;;
;; Author: fuxialexander
;; Keywords: tools
;; URL: https://github.com/fuxialexander/emacs-webkit-katex-render
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
;; Extracted from https://github.com/fuxialexander/emacs-webkit-katex-render
;; and kept because popweb needs to know exactly which characters around point
;; form a formula before it can hand them to KaTeX.
;;
;; The result is always a list of the buffer position where the formula ends
;; and the TeX source with its delimiters removed.  Two input paths exist:
;; AUCTeX supplies `texmathp' in latex-mode, and Org's element API supplies the
;; fragment or environment in org-mode.

;;; Code:

(require 'org)

(defvar webkit-katex-render--previous-math nil
  "TeX source that was previewed last, used to skip an unchanged formula.")

(defvar webkit-katex-render--org-math-preprocess-function
  'webkit-katex-render--org-math-preprocess
  "Function that strips Org's math delimiters from a formula.
It is called with the value and the element type, and must return the TeX
source.")

(declare-function texmathp "texmathp")
(declare-function LaTeX-find-matching-end "latex")
(declare-function LaTeX-find-matching-begin "latex")
(defvar texmathp-why)
(defvar texmathp-tex-commands1)
(defvar texmathp-onoff-regexp)

(defun webkit-katex-render--tex-math-preprocess (math type)
  "Strip the delimiters of MATH according to the AUCTeX construct TYPE.
TYPE is `sw-on' for \\[ ... \\], `sw-toggle' for $ ... $ or $$ ... $$, and
`env-on' for an environment; `symbf' is renamed to `mathbf' on the way out
because KaTeX spells it differently."
  (cond ((eq type 'sw-on)
         (setq math (substring math 2 -2)))
        ((eq type 'sw-toggle)
         (if (string-prefix-p "$$" math)
             (setq math (substring math 2 -2))
           (setq math (substring math 1 -1))))
        ((eq type 'env-on)
         (setq math (replace-regexp-in-string
                     "\\\\"
                     "\\"
                     math t t))
         (setq math
               (replace-regexp-in-string
                "begin{equation}\\|begin{align}\\|begin{align\\*}"
                "begin{aligned}"
                math))
         (setq math
               (replace-regexp-in-string
                "end{equation}\\|end{align}\\|end{align\\*}"
                "end{aligned}"
                math)))
        (t math))
  (setq math
        (replace-regexp-in-string
         "symbf"
         "mathbf"
         math))
  math)

(defun webkit-katex-render--tex-math-at-point ()
  "Return the TeX math around point in a `latex-mode' buffer, or nil.
The result is a list of the end position and the TeX source, with the
delimiters of the surrounding construct removed."
  (if (texmathp)
      (let* ((string (car texmathp-why))
             (pos (cdr texmathp-why))
             (reason (assoc string texmathp-tex-commands1))
             (type (cadr reason)))
        (cond
         ((eq type 'env-on) ;; environments equation, align, etc.
          (let ((count 1)
                beg end)
            ;; Only change point and mark after beginning and end were found.
            ;; Point should not end up in the middle of nowhere if the search
            ;; fails.
            (save-excursion
              (goto-char pos)
              (forward-char 1)
              (dotimes (_ count) (LaTeX-find-matching-end))
              (setq end (line-beginning-position 2))
              (goto-char pos)
              (forward-char 1)
              (dotimes (_ count) (LaTeX-find-matching-begin))
              (setq beg (point))
              (list end
                    (webkit-katex-render--tex-math-preprocess
                     (buffer-substring-no-properties beg end) type)))))
         ((eq type 'sw-toggle) ;; $ and $$
          (save-excursion
            (let ((end (scan-sexps pos 1)))
              (list end (webkit-katex-render--tex-math-preprocess
                         (buffer-substring-no-properties pos end) type)))))
         ((eq type 'sw-on) ;; \( and \[
          (save-excursion
            (let ((end (re-search-forward texmathp-onoff-regexp)))
              (list end
                    (webkit-katex-render--tex-math-preprocess
                     (buffer-substring-no-properties pos end)
                     type)))))))
    nil))

(defun webkit-katex-render--org-math-preprocess (math type)
  "Strip Org's delimiters from MATH according to the element TYPE.
TYPE is `latex-fragment' or `latex-environment'; equation, align and align*
environments are turned into the `aligned' form KaTeX understands."
  (if (eq type 'latex-fragment)
      (if (and (string-prefix-p "$" math)
               (not (string-prefix-p "$$" math)))
          (setq math (substring math 1 -1))
        (setq math (substring math 2 -2)))
    (if (eq type 'latex-environment)
        (progn
          (setq math
                (replace-regexp-in-string
                 "begin{equation}\\|begin{align}\\|begin{align\\*}"
                 "begin{aligned}"
                 math))
          (setq math
                (replace-regexp-in-string
                 "end{equation}\\|end{align}\\|end{align\\*}"
                 "end{aligned}"
                 math)))))
  math)

(defun webkit-katex-render--org-math-at-point ()
  "Return the TeX math around point in an Org buffer, or nil.
A latex source block is handled by `webkit-katex-render--tex-math-at-point';
a fragment or environment goes through Org's element API so that only the
formula itself, without its delimiters, reaches KaTeX."
  (if (and (org-in-src-block-p t)
           (string= (upcase (or (org-element-property :language
                                                      (org-element-at-point))
                                ""))
                    "LATEX"))
      (webkit-katex-render--tex-math-at-point)
    (if (org-inside-LaTeX-fragment-p)
        (let (beg)
          (let ((datum (org-element-context)))
            (when (memq (org-element-type datum)
                        '(latex-environment latex-fragment))
              (setq beg (org-element-property :begin datum))
              (save-excursion
                (goto-char beg)
                (let* ((context (org-element-context))
                       (type (org-element-type context)))
                  (when (memq type '(latex-environment latex-fragment))
                    (let ((value (org-element-property :value context))
                          (end (save-excursion
                                 (goto-char (org-element-property :end context))
                                 (skip-chars-backward " \r\t\n")
                                 (point))))
                      (goto-char end)
                      (list end
                            (funcall
                             webkit-katex-render--org-math-preprocess-function
                             value type)))))))))
      nil)))

(defun webkit-katex-render--math-at-point ()
  "Return the TeX math around point, or nil when there is none.
The major mode decides how the formula is found: `latex-mode' goes through
AUCTeX's `texmathp', `org-mode' through the element API.  Errors are reported
with a message and swallowed, because this runs from a post-command hook."
  (interactive)
  (condition-case err
      (or (and (equal major-mode 'latex-mode)
               (webkit-katex-render--tex-math-at-point))
          (and (equal major-mode 'org-mode)
               (webkit-katex-render--org-math-at-point)))
    (error
     (message "[Error] webkit-katex-render--math-at-point, %s"
              (error-message-string err))
     nil)))

(provide 'math-at-point)
;;; math-at-point.el ends here
