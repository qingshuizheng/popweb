;;; check-forms.el --- Read every top-level form of the given files  -*- lexical-binding: t; -*-

;;; Commentary:
;; A file whose last form is missing a closing paren still lets the Lisp reader
;; read the forms before it, so a byte-compile warning count per file silently
;; drops to zero instead of failing.  Walk each file with `forward-sexp' (which
;; honours the Lisp syntax table, so strings and comments are skipped) and exit
;; non-zero on the first file that does not reach a clean end of file.
;;
;; Usage: Emacs -Q --batch -l scripts/check-forms.el --eval '(z/check-forms "a.el" "b.el")'

;;; Code:

(defun z/check-forms (&rest files)
  "Signal a failure unless every top-level form in FILES reads to the end.
Print the file and line of the first unbalanced form and kill Emacs with
status 1, which is what makes it usable as a build gate."
  (dolist (file files)
    (with-temp-buffer
      (set-syntax-table emacs-lisp-mode-syntax-table)
      ;; A comment may well contain an unbalanced paren, so comments have to be
      ;; skipped while scanning.
      (setq-local parse-sexp-ignore-comments t)
      (insert-file-contents file)
      (goto-char (point-min))
      (let ((done nil))
        (while (not done)
          (forward-comment (point-max))
          (if (eobp)
              (setq done t)
            (let ((line (line-number-at-pos)))
              (condition-case err
                  (forward-sexp 1)
                (error
                 (princ (format "%s:%d: %s\n" file line (error-message-string err)))
                 (kill-emacs 1))))))))))

(provide 'check-forms)
;;; check-forms.el ends here
