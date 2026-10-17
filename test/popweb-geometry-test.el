;;; popweb-geometry-test.el --- Tests for popweb-geometry  -*- lexical-binding: t; -*-

;;; Commentary:
;; The geometry module only reads the selected frame, so every function can be
;; tested by binding the two primitives it uses.  The colour arithmetic is
;; checked separately, including the frame that cannot resolve a colour.

;;; Code:

(require 'ert)
(require 'popweb-geometry)

(ert-deftest popweb-geometry-test-cursor-coordinate-in-eaf ()
  "In an EAF buffer the mouse position is the anchor."
  (cl-letf (((symbol-function 'derived-mode-p) (lambda (&rest _) t))
            ((symbol-function 'mouse-absolute-pixel-position) (lambda () '(10 . 20)))
            ((symbol-function 'window-absolute-pixel-position) (lambda () '(30 . 40))))
    (should (equal (popweb-get-cursor-coordinate) '(10 . 20)))))

(ert-deftest popweb-geometry-test-cursor-coordinate-in-a-text-buffer ()
  "In any other buffer the window's text cursor is the anchor."
  (cl-letf (((symbol-function 'derived-mode-p) (lambda (&rest _) nil))
            ((symbol-function 'mouse-absolute-pixel-position) (lambda () '(10 . 20)))
            ((symbol-function 'window-absolute-pixel-position) (lambda () '(30 . 40))))
    (should (equal (popweb-get-cursor-coordinate) '(30 . 40)))))

(ert-deftest popweb-geometry-test-cursor-offsets-in-eaf ()
  "EAF popups sit 30 pixels right and below the anchor."
  (cl-letf (((symbol-function 'derived-mode-p) (lambda (&rest _) t))
            ((symbol-function 'line-pixel-height) (lambda () 17)))
    (should (= (popweb-get-cursor-x-offset) 30))
    (should (= (popweb-get-cursor-y-offset) 30))))

(ert-deftest popweb-geometry-test-cursor-offsets-in-a-text-buffer ()
  "A text popup starts at the cursor and one line below it."
  (cl-letf (((symbol-function 'derived-mode-p) (lambda (&rest _) nil))
            ((symbol-function 'line-pixel-height) (lambda () 17)))
    (should (= (popweb-get-cursor-x-offset) 0))
    (should (= (popweb-get-cursor-y-offset) 17))))

(ert-deftest popweb-geometry-test-theme-mode-is-a-string ()
  "The mode is reported as a string, which is what Python compares against."
  (cl-letf (((symbol-function 'frame-parameter) (lambda (&rest _) 'dark)))
    (should (equal (popweb-get-theme-mode) "dark"))))

(ert-deftest popweb-geometry-test-colour-component-is-truncated ()
  "Only the low byte of a 16-bit Emacs component reaches the web page."
  (should (equal (popweb-color-int-to-hex 0) "00"))
  (should (equal (popweb-color-int-to-hex 65535) "FF"))
  (should (equal (popweb-color-int-to-hex 291) "23")))

(ert-deftest popweb-geometry-test-colour-name-becomes-hex ()
  "The three components become one #RRGGBB string."
  (cl-letf (((symbol-function 'color-values) (lambda (_colour) '(65535 32896 0))))
    (should (equal (popweb-color-name-to-hex "anything") "#FF8000"))))

(ert-deftest popweb-geometry-test-unresolvable-colour-is-black ()
  "A frame without colour support yields black rather than an error."
  (cl-letf (((symbol-function 'color-values) (lambda (_colour) nil)))
    (should (equal (popweb-color-name-to-hex "anything") "#000000"))))

(ert-deftest popweb-geometry-test-theme-background-reads-the-default-face ()
  "The background of the default face is converted to the page colour."
  (cl-letf (((symbol-function 'face-attribute) (lambda (_face _attribute) "#123456"))
            ((symbol-function 'color-values) (lambda (_colour) '(4660 4660 4660))))
    (should (equal (popweb-get-theme-background) "#343434"))))

(provide 'popweb-geometry-test)
;;; popweb-geometry-test.el ends here
