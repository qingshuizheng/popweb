;;; popweb-anki-review-test.el --- Tests for popweb-anki-review  -*- lexical-binding: t; -*-

;;; Commentary:
;; The review popup takes its query from the region, the sentence at point or
;; the minibuffer.  The sentence finder has an eww-specific implementation
;; because eww lays text out in its own way; both paths are tested here.

;;; Code:

(require 'ert)
(require 'eww)

(require 'popweb-anki-review)

(setq popweb-start-python-process-when-require nil)

(ert-deftest popweb-anki-review-test-string-ends-with-any ()
  "An abbreviation at the end of a string is recognised, ignoring case."
  (should (popweb-anki-review--string-ends-with-any "This is etc." '("i.e." "etc.")))
  (should (popweb-anki-review--string-ends-with-any "This is ETC." '("i.e." "etc.")))
  (should-not (popweb-anki-review--string-ends-with-any "This is fine" '("i.e." "etc.")))
  (should-not (popweb-anki-review--string-ends-with-any "anything" nil)))

(ert-deftest popweb-anki-review-test-eww-sentence ()
  "A sentence in an eww buffer ends at the sentence punctuation."
  (with-temp-buffer
    (insert "First sentence. Second sentence! Third one.")
    (eww-mode)
    (goto-char 22)
    (should (equal (popweb-anki-review--eww-sentence) "Second sentence!"))))

(ert-deftest popweb-anki-review-test-eww-sentence-keeps-an-abbreviation ()
  "An abbreviation does not end the sentence."
  (with-temp-buffer
    (insert "Use etc. in the middle. Next one.")
    (eww-mode)
    (goto-char 10)
    (should (equal (popweb-anki-review--eww-sentence) "Use etc. in the middle."))))

(ert-deftest popweb-anki-review-test-sentence-in-a-text-buffer ()
  "Outside eww the sentence comes from `thing-at-point'."
  (with-temp-buffer
    (insert "Hello world")
    (text-mode)
    (goto-char 6)
    (should (equal (popweb-anki-review--sentence) "Hello world"))))

(ert-deftest popweb-anki-review-test-region-or-sentence ()
  "The active region wins over the sentence."
  (with-temp-buffer
    (insert "one two three")
    (text-mode)
    (set-mark 1)
    (goto-char 4)
    (let ((mark-active t))
      (should (equal (popweb-anki-review-region-or-sentence) "one")))))

(ert-deftest popweb-anki-review-test-show-reads-the-minibuffer ()
  "Without a region or a prefix argument the query is read from the minibuffer."
  (let ((started nil)
        (popweb-anki-review-sentence nil)
        (popweb-anki-review-preview--previous-query nil)
        (popweb-anki-review-preview-window-visible-p nil))
    (cl-letf (((symbol-function 'read-string) (lambda (&rest _) "word"))
              ((symbol-function 'popweb-start)
               (lambda (callback args) (setq started (list callback args))))
              ((symbol-function 'add-hook) (lambda (&rest _) nil)))
      (popweb-anki-review-show))
    (should (eq (nth 0 started) #'popweb-anki-review-preview))
    (should (equal (nth 1 started) '(t "word")))))

(ert-deftest popweb-anki-review-test-show-uses-the-sentence-with-a-prefix ()
  "With a prefix argument the sentence at point is used without prompting."
  (let ((started nil)
        (popweb-anki-review-sentence nil)
        (popweb-anki-review-preview--previous-query nil)
        (popweb-anki-review-preview-window-visible-p nil))
    (cl-letf (((symbol-function 'popweb-start)
               (lambda (callback args) (setq started (list callback args))))
              ((symbol-function 'add-hook) (lambda (&rest _) nil)))
      (with-temp-buffer
        (insert "Hello world")
        (text-mode)
        (goto-char 6)
        (popweb-anki-review-show t)))
    (should (equal (nth 1 started) '(t "Hello world")))))

(ert-deftest popweb-anki-review-test-preview-sends-the-query ()
  "The preview request carries the query, the assets and the callback."
  (let ((calls nil)
        (popweb-anki-review-preview--previous-query nil)
        (popweb-anki-review-preview-window-visible-p nil)
        (popweb-anki-review-media-directory nil)
        (popweb-anki-review-callback nil))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(10 . 20)))
              ((symbol-function 'window-inside-pixel-edges) (lambda (&optional _w) '(0 30 800 600)))
              ((symbol-function 'window-absolute-pixel-edges) (lambda (&optional _w) '(0 0 800 600)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 17))
              ((symbol-function 'frame-position) (lambda (&optional _f) '(5 . 6)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _f) 1000))
              ((symbol-function 'frame-outer-height) (lambda (&optional _f) 800))
              ((symbol-function 'popweb-call-sync)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'run-with-timer) (lambda (&rest _) nil)))
      (popweb-anki-review-preview '(t "word")))
    (let* ((call (car calls))
           (args (cdr call))
           (payload (nth 2 args)))
      (should (equal (car call) "call_module_method"))
      (should (equal (nth 0 args) popweb-anki-review-module-path))
      (should (equal (nth 1 args) "pop_anki_review_window"))
      (should (equal (nth 1 payload) "anki_review"))
      (should (equal (nth 13 payload) t))
      (should (eq (nth 16 payload) t))
      (should (equal (nth 17 payload) "word"))
      (should (null (nth 18 payload))))))

(ert-deftest popweb-anki-review-test-preview-detects-an-unchanged-query ()
  "When the query is the same as the previous one, the page is not rebuilt."
  (let ((calls nil)
        (popweb-anki-review-preview--previous-query "word"))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(0 . 0)))
              ((symbol-function 'window-inside-pixel-edges) (lambda (&optional _w) '(0 0 10 10)))
              ((symbol-function 'window-absolute-pixel-edges) (lambda (&optional _w) '(0 0 10 10)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 0))
              ((symbol-function 'frame-position) (lambda (&optional _f) '(0 . 0)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _f) 10))
              ((symbol-function 'frame-outer-height) (lambda (&optional _f) 10))
              ((symbol-function 'popweb-call-sync)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'run-with-timer) (lambda (&rest _) nil)))
      (popweb-anki-review-preview '(t "word")))
    (should-not (nth 16 (nth 2 (cdar calls))))))

(ert-deftest popweb-anki-review-test-hide-after-move ()
  "Hiding clears the query and removes the hook."
  (let ((popweb-anki-review-preview-window-visible-p t)
        (popweb-anki-review-preview--previous-query "word")
        (calls nil)
        (removed nil))
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) t))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'remove-hook)
               (lambda (hook function) (setq removed (list hook function)))))
      (popweb-anki-review-preview-window-hide-after-move))
    (should (equal calls '(("hide_web_window" "anki_review"))))
    (should-not popweb-anki-review-preview-window-visible-p)
    (should-not popweb-anki-review-preview--previous-query)
    (should (equal removed
                   '(post-command-hook popweb-anki-review-preview-window-hide-after-move)))))

(provide 'popweb-anki-review-test)
;;; popweb-anki-review-test.el ends here
