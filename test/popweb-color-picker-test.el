;;; popweb-color-picker-test.el --- Tests for popweb-color-picker  -*- lexical-binding: t; -*-

;;; Commentary:
;; The three spellings of a colour are recognised separately, so each detector
;; is tested on its own.  The command is tested with the frame primitives
;; replaced, which shows the exact arguments that reach the Python side.

;;; Code:

(require 'ert)

(require 'popweb-color-picker)

(setq popweb-start-python-process-when-require nil)

(ert-deftest popweb-color-picker-test-hex-at-point ()
  "A long hex literal is found and its bounds returned."
  (with-temp-buffer
    (insert "color: #ff00ff;")
    (goto-char 10)
    (should (equal (popweb-color-picker--get-hex-color-at-point) '("#ff00ff" 8 . 15)))))

(ert-deftest popweb-color-picker-test-short-hex-at-point ()
  "A short hex literal is accepted as well."
  (with-temp-buffer
    (insert "color: #abc;")
    (goto-char 10)
    (should (equal (car (popweb-color-picker--get-hex-color-at-point)) "#abc"))))

(ert-deftest popweb-color-picker-test-no-hex-at-point ()
  "A word without a hash sign is not a colour."
  (with-temp-buffer
    (insert "color: red;")
    (goto-char 10)
    (should-not (popweb-color-picker--get-hex-color-at-point))))

(ert-deftest popweb-color-picker-test-named-colour-at-point ()
  "A CSS colour name is found through `css--color-map'."
  (with-temp-buffer
    (insert "color: rebeccapurple;")
    (goto-char 10)
    (should (equal (car (popweb-color-picker--get-named-color-at-point)) "rebeccapurple"))))

(ert-deftest popweb-color-picker-test-unknown-name-is-not-a-colour ()
  "A word that is not a CSS colour name is not recognised."
  (with-temp-buffer
    (insert "color: notacolour;")
    (goto-char 10)
    (should-not (popweb-color-picker--get-named-color-at-point))))

(ert-deftest popweb-color-picker-test-rgb-function-at-point ()
  "An rgb() call is found as one colour, not as a word."
  (with-temp-buffer
    (css-mode)
    (insert "color: rgb(1, 2, 3);")
    (goto-char 18)
    (should (equal (car (popweb-color-picker--get-rgb-or-hsl-color-at-point)) "rgb(1, 2, 3)"))))

(ert-deftest popweb-color-picker-test-hsl-function-at-point ()
  "An hsla() call with an alpha channel is recognised."
  (with-temp-buffer
    (css-mode)
    (insert "color: hsla(1, 2%, 3%, 0.5);")
    (goto-char 15)
    (should (string-prefix-p "hsla(" (car (popweb-color-picker--get-rgb-or-hsl-color-at-point))))))

(ert-deftest popweb-color-picker-test-plain-word-is-no-function ()
  "A word without a function call is not a colour function."
  (with-temp-buffer
    (css-mode)
    (insert "color: red;")
    (goto-char 10)
    (should-not (popweb-color-picker--get-rgb-or-hsl-color-at-point))))

(ert-deftest popweb-color-picker-test-show-sends-the-colour ()
  "The command sends the colour at point with the popup geometry."
  (let ((calls nil)
        (popweb-color-picker-web-window-visible-p nil))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(10 . 20)))
              ((symbol-function 'window-inside-pixel-edges)
               (lambda (&optional _window) '(0 30 800 600)))
              ((symbol-function 'window-absolute-pixel-edges)
               (lambda (&optional _window) '(0 0 800 600)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 17))
              ((symbol-function 'frame-position) (lambda (&optional _frame) '(5 . 6)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _frame) 1000))
              ((symbol-function 'frame-outer-height) (lambda (&optional _frame) 800))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'popweb-color-picker-web-window-can-hide) #'ignore)
              ((symbol-function 'add-hook) (lambda (&rest _) nil)))
      (with-temp-buffer
        (insert "color: #123456;")
        (goto-char 10)
        (popweb-color-picker-show)))
    (let* ((call (car calls))
           (args (cdr call))
           (payload (nth 2 args)))
      (should (equal (car call) "call_module_method"))
      (should (equal (nth 0 args) popweb-color-picker-module-path))
      (should (equal (nth 1 args) "pop_color_picker_window"))
      (should (equal (nth 0 payload) "color-picker"))
      (should (equal (nth 10 payload) "#123456")))))

(ert-deftest popweb-color-picker-test-show-without-a-colour-sends-an-empty-string ()
  "Point not on a colour still opens a picker, with an empty initial value."
  (let ((calls nil)
        (popweb-color-picker-web-window-visible-p nil))
    (cl-letf (((symbol-function 'popweb-get-cursor-coordinate) (lambda () '(0 . 0)))
              ((symbol-function 'window-inside-pixel-edges) (lambda (&optional _window) '(0 0 10 10)))
              ((symbol-function 'window-absolute-pixel-edges) (lambda (&optional _window) '(0 0 10 10)))
              ((symbol-function 'popweb-get-cursor-x-offset) (lambda () 0))
              ((symbol-function 'popweb-get-cursor-y-offset) (lambda () 0))
              ((symbol-function 'frame-position) (lambda (&optional _frame) '(0 . 0)))
              ((symbol-function 'frame-outer-width) (lambda (&optional _frame) 10))
              ((symbol-function 'frame-outer-height) (lambda (&optional _frame) 10))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'popweb-color-picker-web-window-can-hide) #'ignore)
              ((symbol-function 'add-hook) (lambda (&rest _) nil)))
      (with-temp-buffer
        (insert "nothing here")
        (popweb-color-picker-show)))
    (should (equal (nth 10 (nth 2 (cdar calls))) ""))))

(ert-deftest popweb-color-picker-test-hide-after-move ()
  "Hiding sends the module name and removes the hook."
  (let ((popweb-color-picker-web-window-visible-p t)
        (calls nil)
        (removed nil))
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) t))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'remove-hook)
               (lambda (hook function) (setq removed (list hook function)))))
      (popweb-color-picker-web-window-hide-after-move))
    (should (equal calls '(("hide_web_window" "color-picker"))))
    (should-not popweb-color-picker-web-window-visible-p)
    (should (equal removed
                   '(post-command-hook popweb-color-picker-web-window-hide-after-move)))))

(provide 'popweb-color-picker-test)
;;; popweb-color-picker-test.el ends here
