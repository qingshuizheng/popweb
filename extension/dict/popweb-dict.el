;;; popweb-dict.el --- Translation popups for popweb  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2021-11-21
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
;; Four translation sites are wrapped as popups: Bing, Youdao, YouGlish
;; (pronunciation videos) and Dict.cn.  They all load a real page in the Qt
;; window and then run a small JavaScript snippet that hides everything except
;; the part worth reading, which is why `popweb-dict-create' takes both the
;; URL template and that snippet.
;;
;; Each site gets four commands, named after it:
;;
;; - `popweb-dict-SITE-pointer' translates the word or active region at point.
;; - `popweb-dict-SITE-input' asks for a word first, defaulting to that word.
;; - `popweb-dict-SITE-translate' is the internal entry point the other two use.
;; - `popweb-dict-SITE-web-window-hide-after-move' closes the popup on the
;;   next command, one second after it appeared.
;;
;; The popup also speaks the word when `popweb-dict-say-word-p' is non-nil.

;;; Code:

(require 'cl-lib)
(require 'url-util)

(require 'popweb)

(defgroup popweb-dict nil
  "Translation popups shown by popweb."
  :group 'popweb
  :prefix "popweb-dict-")

(defvar popweb-dict-module-path
  (expand-file-name "popweb-dict.py" (file-name-directory (or load-file-name
                                                              buffer-file-name)))
  "Absolute file name of the Python module of the dictionary popups.")

(defvar popweb-dict-audio-process nil
  "Process that plays the pronunciation of the last word, or nil.")

(defcustom popweb-dict-say-word-p t
  "Whether to play the pronunciation of a word when a translation is shown.
The word is spoken by `say' on macOS and by mpv, mplayer or mpg123 on the
other systems, whichever of them is installed first."
  :type 'boolean
  :group 'popweb-dict)

(defcustom popweb-dict-web-window-width-scale 0.3
  "Width of a dictionary popup as a fraction of the Emacs frame width.
The value is read when a popup is requested, so changing it affects the
next translation without restarting the Python process."
  :type 'number
  :group 'popweb-dict)

(defcustom popweb-dict-web-window-height-scale 0.5
  "Height of a dictionary popup as a fraction of the Emacs frame height.
The value is read when a popup is requested, so changing it affects the
next translation without restarting the Python process."
  :type 'number
  :group 'popweb-dict)

(defun popweb-dict-say-word (&optional word)
  "Play the pronunciation of WORD, or of the word at point when WORD is nil.
Return the process that plays it, which can be nil when the platform command
is not available."
  (interactive)
  (unless word
    (setq word (popweb-dict-region-or-word))
    (message "Saying %s ..." word))
  (if (featurep 'cocoa)
      (call-process-shell-command
       (format "say %s" word) nil 0)
    (let ((player (or (executable-find "mpv")
                      (executable-find "mplayer")
                      (executable-find "mpg123"))))
      (if player
          (setq popweb-dict-audio-process
                (start-process
                 player
                 nil
                 player
                 (format "http://dict.youdao.com/dictvoice?type=2&audio=%s"
                         (url-hexify-string word))))
        (message "mpv, mplayer or mpg123 is needed to play word voice")))))

(defun popweb-dict-prompt-input (prompt)
  "Read a word from the minibuffer, using PROMPT as the label.
The word at point is offered as the initial value of the input."
  (read-string (format "%s(%s): " prompt (or (popweb-dict-region-or-word) ""))
               nil nil
               (popweb-dict-region-or-word)))

(defun popweb-dict-region-or-word ()
  "Return the active region, or the word around point when there is none.
The returned string has no text properties, so it is safe to put into a URL
and to pass to a shell command."
  (if mark-active
      (buffer-substring-no-properties (region-beginning)
                                      (region-end))
    (thing-at-point 'word t)))

(cl-defmacro popweb-dict-create (name url js-code &optional js-file)
  "Define a dictionary popup called NAME that loads URL and runs JS-CODE.
URL is a format string with one %s for the word.  JS-CODE is the snippet
that trims the loaded page to the part worth showing; it is wrapped in a
try/catch because every site changes its DOM eventually.  JS-FILE is an
optional file with more JavaScript, read by the Python side at popup time.
The macro defines `popweb-dict-NAME-pointer', `popweb-dict-NAME-input',
`popweb-dict-NAME-translate' and the two window state functions named after
NAME.  The popup covers 30% of the frame width and 50% of its height."
  (let* ((var-visible-p (intern (format "popweb-dict-%s-web-window-visible-p" name)))
         (var-say-word-process (intern (format "popweb-dict-%s-say-word-process" name)))
         (func-hide-after-move (intern (format "popweb-dict-%s-web-window-hide-after-move" name)))
         (func-can-hide (intern (format "popweb-dict-%s-web-window-can-hide" name)))
         (func-pointer (intern (format "popweb-dict-%s-pointer" name)))
         (func-input (intern (format "popweb-dict-%s-input" name)))
         (func-translate (intern (format "popweb-dict-%s-translate" name))))
    `(progn
       (defvar ,var-visible-p nil
         ,(format "Whether the %s popup may be hidden by the next command." name))
       (defvar ,var-say-word-process nil
         ,(format "Process that plays the pronunciation of the last %s word." name))

       (defun ,func-hide-after-move ()
         ,(format "Close the %s popup if it may be hidden, and stop speaking." name)
         (when (and ,var-visible-p (popweb-epc-live-p popweb-epc-process))
           (popweb-call-async "hide_web_window" (format "dict_%s" ,name))
           (setq ,var-visible-p nil)
           (when (and popweb-dict-say-word-p (process-live-p ,var-say-word-process))
             (kill-process ,var-say-word-process))
           (remove-hook 'post-command-hook #',func-hide-after-move)))

       (defun ,func-can-hide ()
         ,(format "Allow the %s popup to be hidden one second from now." name)
         (run-with-timer 1 nil (lambda () (setq ,var-visible-p t))))

       (defun ,func-translate (info)
         ,(format "Show the %s translation of the word in INFO.
INFO is a list whose first element is the word to translate." name)
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
                (width-scale popweb-dict-web-window-width-scale)
                (height-scale popweb-dict-web-window-height-scale)
                (word (nth 0 info))
                (url (format ,url word))
                (js-code (format "try { %s } catch (err) { console.log(err.message) }"
                                 ,js-code))
                (js-file (format "%s" ,js-file))
                (args (nth 0 (cdr info))))
           (if popweb-dict-say-word-p
               (setq ,var-say-word-process (popweb-dict-say-word word)))
           (popweb-call-async "call_module_method" popweb-dict-module-path
                              "pop_translate_window"
                              (list
                               (format "dict_%s" ,name)
                               x y x-offset y-offset
                               frame-x frame-y frame-w frame-h
                               width-scale height-scale
                               url js-code
                               js-file args))
           (funcall #',func-can-hide)))

       (defun ,func-pointer ()
         ,(format "Translate the word or active region at point with %s." name)
         (interactive)
         (,func-hide-after-move)
         (popweb-start #',func-translate (list (popweb-dict-region-or-word)))
         (add-hook 'post-command-hook #',func-hide-after-move))

       (defun ,func-input (&optional word &rest args)
         ,(format "Translate WORD, or a word read from the minibuffer, with %s.
ARGS are passed to the Python module after the word." name)
         (interactive)
         (,func-hide-after-move)
         (popweb-start #',func-translate
                       (list (or word
                                 (popweb-dict-prompt-input
                                  (format "%s dict: " (capitalize ,name))))
                             args))
         (add-hook 'post-command-hook #',func-hide-after-move)))))

(popweb-dict-create "bing"
                    "http://www.bing.com/dict/search?mkt=zh-cn&q=%s"
                    (concat
                     "window.scrollTo(0, 0); "
                     "document.getElementsByTagName('html')[0].style.visibility = 'hidden'; "
                     "document.getElementsByClassName('lf_area')[0].style.visibility = 'visible' ; "
                     "document.getElementsByTagName('header')[0].style.display = 'none'; "
                     "document.getElementsByClassName('contentPadding')[0].style.padding = '10px';"))

(popweb-dict-create "youdao"
                    "https://www.youdao.com/w/eng/%s"
                    (concat
                     "window.scrollTo(0, 0); "
                     "document.getElementsByTagName('html')[0].style.visibility = 'hidden'; "
                     "document.getElementById('results').style.visibility = 'visible'; "
                     "document.getElementById('scontainer').style.margin = '0'; "
                     "document.getElementById('scontainer').style.padding = '0'; "
                     "document.getElementById('result_navigator').style.display = 'none'; "
                     "document.getElementById('container').style.padding = '0'; "
                     "document.getElementById('container').style.paddingLeft = '10px'; "
                     "document.getElementById('container').style.margin = '0'; "
                     "document.getElementById('topImgAd').style.display = 'none';"))

(popweb-dict-create "youglish"
                    "https://youglish.com/pronounce/%s/english?"
                    (concat
                     "window.scrollTo(0, 0); "
                     "document.getElementsByTagName('body')[0].style.margin = '0'; "
                     "document.getElementsByTagName('header')[0].style.display = 'none'; "
                     "document.getElementsByTagName('footer')[0].style.display = 'none'; "
                     "document.getElementsByClassName('search')[0].style.display = 'none'; "
                     "document.querySelectorAll('div .g_pr_ad_network')[1].style.display = 'none' ; "
                     "document.querySelectorAll('div .g_pr_ad_network')[3].style.margin = '0' ; "
                     "Array.from(document.querySelectorAll('ins')).forEach(e => { e.style.display = 'none' }); "
                     "Array.from(document.querySelectorAll('iframe:not(#player)')).forEach(e => { e.style.display = 'none' });"))

(popweb-dict-create "dictcn"
                    "http://dict.cn/%s"
                    (concat
                     "window.scrollTo(0, 0); "
                     "document.getElementsByTagName('html')[0].style.visibility = 'hidden'; "
                     "document.getElementsByClassName('main')[0].style.visibility = 'visible' ; "
                     "document.getElementsByClassName('main')[0].style.margin = '0' ; "
                     "document.getElementById('dshared').style.display = 'none';"
                     "document.getElementById('aswift_0_host').style.display = 'none';"
                     "document.getElementById('aswift_1_host').style.display = 'none';"
                     "document.getElementById('aswift_2_host').style.display = 'none';"
                     "document.getElementById('aswift_3_host').style.display = 'none';"
                     "document.getElementById('content').style.padding = '0';"
                     "document.getElementById('content').style.margin = '0';"
                     "document.getElementById('footer').style.display = 'none';"
                     "document.getElementsByClassName('copyright')[0].style.display = 'none';"
                     "Array.from(document.querySelectorAll('iframe')).forEach(e => { e.style.display = 'none' })"))

(provide 'popweb-dict)
;;; popweb-dict.el ends here
