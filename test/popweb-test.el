;;; popweb-test.el --- Tests for the public surface of popweb  -*- lexical-binding: t; -*-

;;; Commentary:
;; `popweb.el' is the front door: it loads the other modules and keeps the
;; commands that do not belong to one extension.  The cookie import is the one
;; command with logic, so it is checked here.

;;; Code:

(require 'ert)
(require 'popweb)

(setq popweb-start-python-process-when-require nil)

(ert-deftest popweb-test-import-browser-cookies-calls-python ()
  "The command starts popweb and forwards the browser and the domain."
  (let ((started nil)
        (calls nil))
    (cl-letf (((symbol-function 'popweb-start)
               (lambda (callback args) (setq started (list callback args))))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls))))
      (popweb-import-browser-cookies "chrome" "example.com")
      (should started)
      (should (null (nth 1 started)))
      (funcall (nth 0 started) nil))
    (should (equal calls '(("import_browser_cookies" "chrome" "example.com"))))))

(ert-deftest popweb-test-import-browser-cookies-is-interactive ()
  "The command is callable interactively, so it must have an interactive form."
  (should (commandp #'popweb-import-browser-cookies))
  (should (interactive-form #'popweb-import-browser-cookies)))

(ert-deftest popweb-test-forget-window-sizes-calls-python ()
  "The reset command starts popweb and calls the Python method."
  (let ((started nil)
        (calls nil))
    (cl-letf (((symbol-function 'popweb-start)
               (lambda (callback args) (setq started (list callback args))))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls))))
      (popweb-forget-window-sizes)
      (should started)
      (should (null (nth 1 started)))
      (funcall (nth 0 started) nil))
    (should (equal calls '(("forget_window_sizes"))))))

(ert-deftest popweb-test-process-commands-are-commands ()
  "Restarting and stopping are user commands."
  (should (commandp #'popweb-restart-process))
  (should (commandp #'popweb-kill-process))
  (should (commandp #'popweb--kill-python-process))
  (should (commandp #'popweb-forget-window-sizes)))

(provide 'popweb-test)
;;; popweb-test.el ends here
