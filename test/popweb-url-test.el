;;; popweb-url-test.el --- Tests for popweb-url  -*- lexical-binding: t; -*-

;;; Commentary:
;; URL preview has two sources for the address (point and the line) and two
;; size modes; the tests cover both, plus the local file resolution.

;;; Code:

(require 'ert)

(require 'popweb-url)

(setq popweb-start-python-process-when-require nil)

(ert-deftest popweb-url-test-line-url-starts-at-zero ()
  "The first URL of a line is found from column zero."
  (with-temp-buffer
    (insert "see https://example.com/path now")
    (should (equal (popweb-current-line-url 0) "https://example.com/path"))))

(ert-deftest popweb-url-test-line-url-starts-at-a-column ()
  "A start column skips the URLs that begin before it."
  (with-temp-buffer
    (insert "see https://example.com/path now")
    (should (equal (popweb-current-line-url 4) "https://example.com/path"))
    (should-not (popweb-current-line-url 20))))

(ert-deftest popweb-url-test-get-url-at-point ()
  "A URL under point is returned as is."
  (with-temp-buffer
    (text-mode)
    (insert "see https://example.com/path now")
    (goto-char 12)
    (should (equal (popweb-get-url) "https://example.com/path"))))

(ert-deftest popweb-url-test-get-url-falls-back-to-the-line ()
  "When point is not on a URL, the first URL of the line is used."
  (with-temp-buffer
    (text-mode)
    (insert "see https://example.com/path now")
    (goto-char (point-min))
    (should (equal (popweb-get-url) "https://example.com/path"))))

(ert-deftest popweb-url-test-local-file-is-completed-against-the-buffer ()
  "A file: URL is resolved against the directory of the buffer."
  (with-temp-buffer
    (let ((buffer-file-name "/tmp/notes.org"))
      (should (equal (popweb-url-local-file-url-completion "file:page.html")
                     "file:/tmp/page.html")))))

(ert-deftest popweb-url-test-remote-url-is-not-completed ()
  "A URL that is not a local file is returned unchanged."
  (with-temp-buffer
    (let ((buffer-file-name "/tmp/notes.org"))
      (should (equal (popweb-url-local-file-url-completion "https://example.com")
                     "https://example.com")))))

(ert-deftest popweb-url-test-prompt-uses-the-url-at-point ()
  "The prompt shows the URL and offers it as the initial value."
  (let (captured)
    (cl-letf (((symbol-function 'read-string)
               (lambda (prompt &optional _initial _history default _inherit)
                 (setq captured (list prompt default))
                 "typed")))
      (with-temp-buffer
        (text-mode)
        (insert "https://example.com/path")
        (goto-char 10)
        (should (equal (popweb-url-prompt-input "preview") "typed"))))
    (should (equal (nth 0 captured) "preview(https://example.com/path): "))
    (should (equal (nth 1 captured) "https://example.com/path"))))

(ert-deftest popweb-url-test-absolute-size-is-sent ()
  "The absolute size and the use-absolute flag reach Python unchanged."
  (let ((calls nil)
        (popweb-url-web-window-visible-p nil))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(10 . 20)))
              ((symbol-function 'window-inside-pixel-edges) (lambda (&optional _w) '(0 30 800 600)))
              ((symbol-function 'window-absolute-pixel-edges) (lambda (&optional _w) '(0 0 800 600)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 17))
              ((symbol-function 'frame-position) (lambda (&optional _f) '(5 . 6)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _f) 1000))
              ((symbol-function 'frame-outer-height) (lambda (&optional _f) 800))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'run-with-timer) (lambda (&rest _) nil)))
      (popweb-url '("https://example.com")))
    (let* ((call (car calls))
           (args (cdr call))
           (payload (nth 2 args)))
      (should (equal (car call) "call_module_method"))
      (should (equal (nth 0 args) popweb-url-module-path))
      (should (equal (nth 1 args) "pop_url_window"))
      (should (equal (nth 1 payload) 10))
      (should (equal (nth 2 payload) -10))
      (should (equal (nth 9 payload) 0.8))
      (should (equal (nth 10 payload) 0.45))
      (should (equal (nth 11 payload) 480))
      (should (equal (nth 12 payload) 270))
      (should (eq (nth 13 payload) t))
      (should (equal (nth 14 payload) "https://example.com")))))

(ert-deftest popweb-url-test-input-and-pointer-start-the-popup ()
  "Both commands pass their URL to the same callback."
  (let ((started nil)
        (popweb-url-web-window-visible-p nil))
    (cl-letf (((symbol-function 'popweb-start)
               (lambda (callback args) (setq started (list callback args))))
              ((symbol-function 'add-hook) (lambda (&rest _) nil)))
      (popweb-url-input "https://example.com/input")
      (should (equal (nth 1 started) '("https://example.com/input")))
      (with-temp-buffer
        (text-mode)
        (insert "https://example.com/pointer")
        (goto-char 10)
        (popweb-url-preview-pointer))
      (should (equal (nth 1 started) '("https://example.com/pointer"))))))

(ert-deftest popweb-url-test-hide-after-move ()
  "Hiding sends the module name and removes the hook."
  (let ((popweb-url-web-window-visible-p t)
        (calls nil)
        (removed nil))
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) t))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'remove-hook)
               (lambda (hook function) (setq removed (list hook function)))))
      (popweb-url-web-window-hide-after-move))
    (should (equal calls '(("hide_web_window" "url-preview"))))
    (should-not popweb-url-web-window-visible-p)
    (should (equal removed '(post-command-hook popweb-url-web-window-hide-after-move)))))

(provide 'popweb-url-test)
;;; popweb-url-test.el ends here
