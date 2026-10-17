;;; check-bodies.el --- Every definition has a body  -*- lexical-binding: t; -*-

;;; Commentary:
;; A definition whose body was lost reads fine and compiles cleanly: a
;; `defun' that is only a docstring returns nil, so it is a command the user
;; can invoke that does nothing at all.  `blink-search-recent-file-update'
;; was exactly that for one commit -- an idle timer that ticked and pushed
;; nothing -- and neither the byte compiler nor checkdoc has anything to say
;; about it.
;;
;; This script reads every top level form and fails on a definition that has
;; a docstring and nothing after it.  It is the second half of
;; `check-forms.el': that one makes sure a form reads, this one makes sure it
;; does something.
;;
;; Usage: Emacs -Q --batch -l scripts/check-bodies.el --eval '(z/check-bodies "a.el" ...)'

;;; Code:

(defconst z/definition-heads
  '(defun defsubst defmacro cl-defun cl-defmacro define-minor-mode
    define-derived-mode define-globalized-minor-mode)
  "The forms that hold a body after their docstring.")

;; Index of the docstring inside a definition, by the head of the form.
(defconst z/docstring-index
  '((defun . 3) (defsubst . 3) (defmacro . 3) (cl-defun . 3) (cl-defmacro . 3)
    (define-minor-mode . 2) (define-derived-mode . 4)
    (define-globalized-minor-mode . 2))
  "The position of the docstring and of the body in each definition.")

(defun z/check-bodies (&rest files)
  "Report every definition in FILES that has no body, and exit non-zero.

A definition whose docstring is its last element is reported with its name
and line; a `define-minor-mode' with keywords but no body counts as having
a body, because the keywords are what it does."
  (let ((failures 0))
    (dolist (file files)
      (with-temp-buffer
        (set-syntax-table emacs-lisp-mode-syntax-table)
        (setq-local parse-sexp-ignore-comments t)
        (insert-file-contents file)
        (goto-char (point-min))
        (condition-case nil
            (while t
              (let* ((form (read (current-buffer)))
                     (head (and (consp form) (car form)))
                     (index (and head (cdr (assq head z/docstring-index)))))
                (when (and index
                           (stringp (nth index form))
                           (null (nthcdr (1+ index) form)))
                  (setq failures (1+ failures))
                  (princ (format "%s:%d: %s has no body\n"
                                 file (line-number-at-pos) (nth 1 form))))))
          (end-of-file nil)
          (error nil))))
    (when (> failures 0)
      (kill-emacs 1))))

(provide 'check-bodies)
;;; check-bodies.el ends here
