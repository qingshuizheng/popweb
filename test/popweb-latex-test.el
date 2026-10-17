;;; popweb-latex-test.el --- Tests for popweb-latex  -*- lexical-binding: t; -*-

;;; Commentary:
;; The TeX extraction is tested in Org buffers, where the element API is
;; available and does not need AUCTeX.  The preview request and the minor mode
;; are tested with the frame primitives and the process replaced.

;;; Code:

(require 'ert)

(require 'popweb-latex)
(require 'math-at-point)

(setq popweb-start-python-process-when-require nil)

(ert-deftest popweb-latex-test-preprocess-fragment ()
  "A single-dollar fragment loses both dollars."
  (should (equal (webkit-katex-render--org-math-preprocess "$x^2$" 'latex-fragment) "x^2")))

(ert-deftest popweb-latex-test-preprocess-display-fragment ()
  "A double-dollar fragment loses both pairs of dollars."
  (should (equal (webkit-katex-render--org-math-preprocess "$$x^2$$" 'latex-fragment) "x^2")))

(ert-deftest popweb-latex-test-preprocess-environment ()
  "An equation environment becomes the aligned form KaTeX understands."
  (let ((result (webkit-katex-render--org-math-preprocess
                 "\\begin{equation}\nx=1\n\\end{equation}" 'latex-environment)))
    (should (string-match-p "\\\\begin{aligned}" result))
    (should (string-match-p "\\\\end{aligned}" result))
    (should-not (string-match-p "equation" result))))

(ert-deftest popweb-latex-test-org-fragment-at-point ()
  "A fragment in an Org buffer is returned as its TeX source."
  (with-temp-buffer
    (org-mode)
    (insert "Text $x^2$ end")
    (goto-char 8)
    (let ((result (webkit-katex-render--org-math-at-point)))
      (should (equal (nth 1 result) "x^2"))
      (should (= (nth 0 result) 11)))))

(ert-deftest popweb-latex-test-org-environment-at-point ()
  "An environment in an Org buffer is converted to aligned."
  (with-temp-buffer
    (org-mode)
    (insert "\\begin{equation}\nx=1\n\\end{equation}")
    (goto-char 20)
    (let ((result (webkit-katex-render--org-math-at-point)))
      (should (string-match-p "begin{aligned}" (nth 1 result)))
      (should (string-match-p "x=1" (nth 1 result))))))

(ert-deftest popweb-latex-test-org-without-math ()
  "Plain text in an Org buffer has no formula."
  (with-temp-buffer
    (org-mode)
    (insert "just text")
    (should-not (webkit-katex-render--org-math-at-point))))

(ert-deftest popweb-latex-test-math-at-point-uses-the-major-mode ()
  "The dispatcher only looks for math in `latex-mode' and `org-mode'."
  (with-temp-buffer
    (text-mode)
    (insert "$x$")
    (goto-char 3)
    (should-not (webkit-katex-render--math-at-point)))
  (with-temp-buffer
    (org-mode)
    (insert "$x$")
    (goto-char 3)
    (should (equal (nth 1 (webkit-katex-render--math-at-point)) "x"))))

(ert-deftest popweb-latex-test-preview-sends-the-formula ()
  "The preview request carries the visibility flag, the cache flag and the TeX."
  (let ((calls nil)
        (webkit-katex-render--previous-math nil))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(10 . 20)))
              ((symbol-function 'window-inside-pixel-edges) (lambda (&optional _w) '(0 30 800 600)))
              ((symbol-function 'window-absolute-pixel-edges) (lambda (&optional _w) '(0 0 800 600)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 17))
              ((symbol-function 'frame-position) (lambda (&optional _f) '(5 . 6)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _f) 1000))
              ((symbol-function 'frame-outer-height) (lambda (&optional _f) 800))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls))))
      (popweb-latex-preview '(t "x^2")))
    (let* ((call (car calls))
           (args (cdr call))
           (payload (nth 2 args)))
      (should (equal (car call) "call_module_method"))
      (should (equal (nth 0 args) popweb-latex-module-path))
      (should (equal (nth 1 args) "pop_latex_window"))
      (should (equal (nth 0 payload) "latex"))
      (should (equal (nth 2 payload) 10))
      (should (equal (nth 3 payload) -10))
      (should (eq (nth 10 payload) t))
      (should (eq (nth 11 payload) t))
      (should (equal (nth 12 payload) "x^2")))))

(ert-deftest popweb-latex-test-preview-does-not-mark-an-unchanged-formula-new ()
  "When the formula is already rendered, `new-latex' is nil."
  (let ((calls nil)
        (webkit-katex-render--previous-math "x^2"))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(0 . 0)))
              ((symbol-function 'window-inside-pixel-edges) (lambda (&optional _w) '(0 0 10 10)))
              ((symbol-function 'window-absolute-pixel-edges) (lambda (&optional _w) '(0 0 10 10)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 0))
              ((symbol-function 'frame-position) (lambda (&optional _f) '(0 . 0)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _f) 10))
              ((symbol-function 'frame-outer-height) (lambda (&optional _f) 10))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls))))
      (popweb-latex-preview '(t "x^2")))
    (should-not (nth 11 (nth 2 (cdar calls))))))

(ert-deftest popweb-latex-test-hide-is-idempotent ()
  "Hiding twice sends the request only once."
  (let ((popweb-latex-popup-foreground t)
        (webkit-katex-render--previous-math "x^2")
        (calls nil))
    (cl-letf (((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls))))
      (popweb-latex-hide)
      (popweb-latex-hide))
    (should (equal calls '(("hide_web_window" "latex"))))
    (should-not popweb-latex-popup-foreground)
    (should-not webkit-katex-render--previous-math)))

(ert-deftest popweb-latex-test-mode-installs-and-removes-the-hooks ()
  "Turning the mode on follows point; turning it off unhooks and hides."
  (with-temp-buffer
    (org-mode)
    (let ((shown 0)
          (hidden 0))
      (cl-letf (((symbol-function 'popweb-latex-show) (lambda () (cl-incf shown)))
                ((symbol-function 'popweb-latex-hide) (lambda () (cl-incf hidden))))
        (popweb-latex-mode 1)
        (should popweb-latex-mode)
        (should (= shown 1))
        (should (memq #'popweb-latex-hide-after-switch-buffer window-state-change-hook))
        (popweb-latex-mode -1)
        (should-not popweb-latex-mode)
        (should (= hidden 1))
        (should-not (memq #'popweb-latex-hide-after-switch-buffer window-state-change-hook))
        (should-not (memq #'popweb-latex-update post-command-hook))))))

(provide 'popweb-latex-test)
;;; popweb-latex-test.el ends here
