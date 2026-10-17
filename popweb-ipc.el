;;; popweb-ipc.el --- Calls between Emacs and the popweb Python process  -*- lexical-binding: t; -*-

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
;; The two directions of the conversation, and nothing else:
;;
;; - Emacs calls a Python method through `popweb-call-async' or
;;   `popweb-call-sync', which hide the deferred object and the EPC session
;;   bookkeeping behind a plain function call.
;; - Python calls back through the `eval-in-emacs', `get-emacs-var' and
;;   `get-emacs-vars' methods that `popweb-process' registers on the EPC
;;   server.
;;
;; Strings cross the wire Base64 encoded.  That is not decoration: the EPC
;; layer reads back Lisp forms, so a page title or a translation containing a
;; quote, a parenthesis or a newline would otherwise be read as code.

;;; Code:

(require 'base64)
(require 'subr-x)

(require 'popweb-epc)

(defvar popweb-epc-process nil
  "EPC manager of the Python process.
The value is nil until `popweb--first-start' has received the port of the
Python side, and `popweb-epc-live-p' is the supported way to test it.")

(defun popweb-call-async (method &rest args)
  "Call the Python method named METHOD with ARGS, without waiting.
METHOD is a string, read as the Lisp symbol that EPC expects; ARGS are sent
as one Lisp list.  The return value is the deferred object of the call, which
callers are free to ignore."
  (popweb-deferred-chain
    (popweb-epc-call-deferred popweb-epc-process (read method) args)))

(defun popweb-call-sync (method &rest args)
  "Call the Python method named METHOD with ARGS and return its result.
METHOD is a string, read as the Lisp symbol that EPC expects; ARGS are sent
as one Lisp list.  Emacs waits for the answer, so this must not be used from
the middle of a process filter or a timer that the answer depends on."
  (popweb-epc-call-sync popweb-epc-process (read method) args))

(defun popweb--decode-string (str)
  "Decode STR from the Base64 encoded UTF-8 that Python sends."
  (decode-coding-string (base64-decode-string str) 'utf-8))

(defun popweb--encode-string (str)
  "Encode STR as Base64 of its UTF-8 bytes, for sending to Python."
  (base64-encode-string (encode-coding-string str 'utf-8)))

(defun popweb--decode-argument (arg)
  "Turn one Base64 encoded ARG from Python into the value Emacs should use.
An argument starting with a single quote is read as a Lisp form, so Python
can pass symbols and numbers; a parenthesized argument is split on spaces
into a list.  Everything else stays a string."
  (let ((arg (popweb--decode-string arg)))
    (cond
     ((string-prefix-p "'" arg)
      (read (substring arg 1)))
     ((and (string-prefix-p "(" arg)
           (string-suffix-p ")" arg))
      (let ((elements (substring arg 1 -1)))
        (if (string-empty-p elements)
            nil
          (split-string elements " "))))
     (t arg))))

(defun popweb--eval-in-emacs-func (&rest args)
  "Apply the Emacs function named by the first element of ARGS to the rest.
Python sends the function name first, then one Base64 encoded argument per
parameter; see `popweb--decode-argument' for how each of them is decoded.
The result of the function is returned to Python as the EPC reply."
  (apply (read (car args))
         (mapcar #'popweb--decode-argument (cdr args))))

(defun popweb--get-emacs-var-func (var-name)
  "Return the value of the Emacs variable named VAR-NAME.
The reply is a list of the value and a string that says whether the value is
a boolean.  Python needs that second element because EPC turns a Lisp nil
into an empty list, which cannot be told apart from \"false\" otherwise."
  (let* ((var-symbol (intern var-name))
         (var-value (symbol-value var-symbol))
         (var-is-bool (prin1-to-string (booleanp var-value))))
    (list var-value var-is-bool)))

(defun popweb--get-emacs-vars-func (&rest vars)
  "Return a list of the values of the Emacs variables named in VARS.
Each element has the shape returned by `popweb--get-emacs-var-func'."
  (mapcar #'popweb--get-emacs-var-func vars))

(provide 'popweb-ipc)
;;; popweb-ipc.el ends here
