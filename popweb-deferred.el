;;; popweb-deferred.el --- Deferred objects for asynchronous chains  -*- lexical-binding: t; -*-

;; Copyright (C) 2011,2012,2013 Masashi Sakurai
;;
;; Author: Masashi Sakurai <m.sakurai at kiwanami.net>
;; Keywords: lisp
;; URL: https://github.com/kiwanami/emacs-deferred
;; Package-Requires: ((emacs "24.4"))

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
;; along with this program.  If not, see <http://www.gnu.org/licenses/>.

;;; Commentary:
;;
;; A copy of the `deferred' library by Masashi Sakurai, with every symbol
;; prefixed `popweb-'.  Popweb needs exactly one thing from it: an object that
;; EPC can hand back as the promise of a method call, and that callers who do
;; not care about the answer can ignore.
;;
;; The semantics are unchanged from the original; only the docstrings were
;; rewritten for this tree.  Start from `popweb-deferred-new'.

;;; Code:

(require 'cl-lib)
(require 'subr-x)

;; deferred
(defmacro popweb-deferred-chain (&rest elements)
  "Evaluation helper for deferred chains.
ELEMENTS are forms evaluated in order, each one available to the next as
`it'; the value of the last form is returned."
  (declare (debug (&rest form))
           (indent 0))
  `(let (it)
     ,@(cl-loop for i in elements
                collect
                `(setq it ,i))
     it))

;; Debug
(defvar popweb-deferred-debug nil
  "Whether to write a trace of the deferred queue to a log buffer.")

(defvar popweb-deferred-debug-count 0
  "Number of lines written by `popweb-deferred-log' so far.")

(defun popweb-deferred-log (&rest args)
  "Write a line made from ARGS to the debug buffer.
Nothing happens unless `popweb-deferred-debug' is non-nil."
  (when popweb-deferred-debug
    (with-current-buffer (get-buffer-create "*popweb-deferred-log*")
      (save-excursion
        (goto-char (point-max))
        (insert (format "%5i %s\n\n\n" popweb-deferred-debug-count (apply #'format args)))))
    (cl-incf popweb-deferred-debug-count)))

(defvar popweb-deferred-debug-on-signal nil
  "Whether the debugger should catch errors inside asynchronous tasks.
When non-nil, it is bound to `debug-on-signal' around every task, so a
backtrace appears instead of the error being swallowed by the queue.")

(defmacro popweb-deferred-condition-case (var protected-form &rest handlers)
  "Run PROTECTED-FORM, binding the error to VAR and running HANDLERS.
The difference from `condition-case' is that `debug-on-signal' is bound from
`popweb-deferred-debug-on-signal' first, so a debugger can break inside a
task that the queue would otherwise handle silently."
  (declare (debug condition-case)
           (indent 1))
  `(let ((debug-on-signal
          (or debug-on-signal popweb-deferred-debug-on-signal)))
     (condition-case ,var
         ,protected-form
       ,@handlers)))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Back end functions of deferred tasks

(defvar popweb-deferred-tick-time 0.001
  "Seconds between two runs of the deferred queue.
A shorter time makes tasks start sooner and loads Emacs more; applications
should leave it alone, because the value has to suit every environment.")

(defvar popweb-deferred-queue nil
  "Tasks waiting for `popweb-deferred-worker', newest first.
Each element is a list of the deferred object, the status symbol `ok' or
`ng', and the value to run it with.")

(defun popweb-deferred-post-task (d which &optional arg)
  "Queue deferred object D for execution with status WHICH and value ARG.
WHICH is `ok' or `ng'.  The queue is consumed by
`popweb-deferred-worker' one item per `popweb-deferred-tick-time', so a
chain cannot block redisplay."
  (let ((pack `(,d ,which . ,arg)))
    (push pack popweb-deferred-queue)
    (popweb-deferred-log "QUEUE-POST [%s]: %s" (length popweb-deferred-queue) pack)
    (run-at-time popweb-deferred-tick-time nil 'popweb-deferred-worker)
    d))

(defun popweb-deferred-worker ()
  "Run the oldest task in `popweb-deferred-queue'.
This is the timer callback scheduled by `popweb-deferred-post-task'.  An
error in the task is logged and reported with a message, never signaled to
the timer."
  (when popweb-deferred-queue
    (let* ((pack (car (last popweb-deferred-queue)))
           (d (car pack))
           (which (cadr pack))
           (arg (cddr pack)) value)
      (setq popweb-deferred-queue (nbutlast popweb-deferred-queue))
      (condition-case err
          (setq value (popweb-deferred-exec-task d which arg))
        (error
         (popweb-deferred-log "ERROR : %s" err)
         (message "deferred error : %s" err)))
      value)))

;; Struct: popweb-deferred-object
(cl-defstruct popweb-deferred-object
  "Object that carries one asynchronous task and its continuation.

callback  is called with the value when the task succeeds, and defaults to
          `identity'.
errorback is called with the error when the task fails, and defaults to
          `popweb-deferred-resignal'.
cancel    resets the object, and defaults to
          `popweb-deferred-default-cancel'.
next      is the deferred object that follows this one.
status    is `ok' or `ng' once a value or an error has been stored.
value     is that stored value or error."
  (callback 'identity)
  (errorback 'popweb-deferred-resignal)
  (cancel 'popweb-deferred-default-cancel)
  next status value)

(defun popweb-deferred-resignal (err)
  "Signal ERR again as the Emacs condition it stands for.
If ERR is a cons whose car has `error-conditions', it is signaled unchanged.
A string is signaled as a plain `error', and anything else is printed with
`%S' before being signaled."
  (cond ((and (listp err)
              (symbolp (car err))
              (get (car err) 'error-conditions))
         (signal (car err) (cdr err)))
        ((stringp err)
         (error "%s" err))
        (t
         (error "%S" err))))

(defun popweb-deferred-default-cancel (d)
  "Disarm deferred object D and drop the chain that follows it.
D still exists, but it no longer calls a callback, resignals errors, and has
no `next' object; the value of D is kept."
  (popweb-deferred-log "CANCEL : %s" d)
  (setf (popweb-deferred-object-callback d) 'identity)
  (setf (popweb-deferred-object-errorback d) 'popweb-deferred-resignal)
  (setf (popweb-deferred-object-next d) nil)
  d)

(defun popweb-deferred-exec-task (d which &optional arg)
  "Run task D with status WHICH and value ARG.
WHICH is `ok' to call the callback or `ng' to call the errorback.  A task
that returns another deferred object has that object chained in front of D's
continuation, which is how one asynchronous call starts another.  Return the
value of the task, or the deferred object that now continues after it."
  (popweb-deferred-log "EXEC : %s / %s / %s" d which arg)
  (when (null d) (error "Got nil in `popweb-deferred-exec-task'"))
  (let ((callback (if (eq which 'ok)
                      (popweb-deferred-object-callback d)
                    (popweb-deferred-object-errorback d)))
        (next-deferred (popweb-deferred-object-next d)))
    (cond
     (callback
      (popweb-deferred-condition-case err
                                      (let ((value (funcall callback arg)))
                                        (cond
                                         ((popweb-deferred-object-p value)
                                          (popweb-deferred-log "WAIT NEST : %s" value)
                                          (if next-deferred
                                              (popweb-deferred-set-next value next-deferred)
                                            value))
                                         (t
                                          (if next-deferred
                                              (popweb-deferred-post-task next-deferred 'ok value)
                                            (setf (popweb-deferred-object-status d) 'ok)
                                            (setf (popweb-deferred-object-value d) value)
                                            value))))
                                      (error
                                       (cond
                                        (next-deferred
                                         (popweb-deferred-post-task next-deferred 'ng err))
                                        (t
                                         (popweb-deferred-log "ERROR : %S" err)
                                         (message "deferred error : %S" err)
                                         (setf (popweb-deferred-object-status d) 'ng)
                                         (setf (popweb-deferred-object-value d) err)
                                         err)))))
     (t                                 ; <= (null callback)
      (cond
       (next-deferred
        (popweb-deferred-exec-task next-deferred which arg))
       ((eq which 'ok) arg)
       (t                               ; (eq which 'ng)
        (popweb-deferred-resignal arg)))))))

(defun popweb-deferred-set-next (prev next)
  "Make NEXT the object that follows PREV.
If PREV already produced a value, NEXT runs at once with it; otherwise NEXT
waits for PREV to finish.  Return the object that a caller should keep."
  (setf (popweb-deferred-object-next prev) next)
  (cond
   ((eq 'ok (popweb-deferred-object-status prev))
    (setf (popweb-deferred-object-status prev) nil)
    (let ((ret (popweb-deferred-exec-task
                next 'ok (popweb-deferred-object-value prev))))
      (if (popweb-deferred-object-p ret) ret
        next)))
   ((eq 'ng (popweb-deferred-object-status prev))
    (setf (popweb-deferred-object-status prev) nil)
    (let ((ret (popweb-deferred-exec-task next 'ng (popweb-deferred-object-value prev))))
      (if (popweb-deferred-object-p ret) ret
        next)))
   (t
    next)))

(defun popweb-deferred-new (&optional callback)
  "Create a deferred object whose callback is CALLBACK.
CALLBACK defaults to `identity', which makes the object useful as a place
holder for a result that is only passed through."
  (if callback
      (make-popweb-deferred-object :callback callback)
    (make-popweb-deferred-object)))

(defun popweb-deferred-callback (d &optional arg)
  "Start deferred object D with a successful value ARG."
  (popweb-deferred-exec-task d 'ok arg))

(defun popweb-deferred-errorback (d &optional arg)
  "Start deferred object D with the error value ARG."
  (declare (indent 1))
  (popweb-deferred-exec-task d 'ng arg))

(defun popweb-deferred-callback-post (d &optional arg)
  "Queue deferred object D to run with the successful value ARG."
  (declare (indent 1))
  (popweb-deferred-post-task d 'ok arg))

(defun popweb-deferred-next (&optional callback arg)
  "Create and queue a deferred object with CALLBACK, passing it ARG.
This is `popweb-deferred-callback-post' applied to
`popweb-deferred-new', and exists so that call sites read as one step."
  (let ((d (if callback
               (make-popweb-deferred-object :callback callback)
             (make-popweb-deferred-object))))
    (popweb-deferred-callback-post d arg)
    d))

(defun popweb-deferred-nextc (d callback)
  "Attach CALLBACK to deferred object D as its success continuation.
Return the new deferred object that holds CALLBACK."
  (declare (indent 1))
  (let ((nd (make-popweb-deferred-object :callback callback)))
    (popweb-deferred-set-next d nd)))

(defun popweb-deferred-error (d callback)
  "Create a deferred object with errorback CALLBACK after D.
When D fails, CALLBACK is called with its error value; when D succeeds, the
errorback of the new object is never reached."
  (declare (indent 1))
  (let ((nd (make-popweb-deferred-object :errorback callback)))
    (popweb-deferred-set-next d nd)))

(provide 'popweb-deferred)
;;; popweb-deferred.el ends here
