;;; popweb-config-test.el --- Tests for popweb-config  -*- lexical-binding: t; -*-

;;; Commentary:
;; The options are the contract with Python: their names and defaults are read
;; from the other side by name, so a renamed or retyped option is a protocol
;; change.  These tests pin the defaults and the types Customize promises.

;;; Code:

(require 'ert)
(require 'popweb-config)

(ert-deftest popweb-config-test-defaults ()
  "The defaults are the values the README documents."
  (should (equal popweb-name "*popweb*"))
  (should (stringp popweb-python-command))
  (should (equal popweb-proxy-host ""))
  (should (equal popweb-proxy-port ""))
  (should (equal popweb-proxy-type ""))
  (should (equal popweb-popup-pos "point-bottom-right"))
  (should-not popweb-enable-debug)
  (should-not popweb-enable-developer-tools)
  (should popweb-start-python-process-when-require))

(ert-deftest popweb-config-test-tuning-defaults ()
  "The zoom factor is one and the config directory ends with a separator."
  (should (= popweb-zoom-factor 1))
  (should (string-suffix-p "/" popweb-config-location))
  (should (file-name-absolute-p popweb-config-location)))

(ert-deftest popweb-config-test-popup-positions ()
  "Every position the Python side knows is offered by the option."
  (dolist (position '("point-bottom" "point-bottom-right" "top-left" "top-right"
                      "bottom-left" "bottom-right" "middle"))
    (should (equal (get-text-property 0 'choice position) nil))
    (should (member position (mapcar #'cadr (cdr (get 'popweb-popup-pos 'custom-type)))))))

(ert-deftest popweb-config-test-group ()
  "All options share the popweb group, so Customize shows one page."
  (let ((members (get 'popweb 'custom-group)))
    (dolist (option '(popweb-name popweb-python-command popweb-popup-pos
                      popweb-enable-debug popweb-zoom-factor popweb-config-location))
      (should (assq option members)))))

(provide 'popweb-config-test)
;;; popweb-config-test.el ends here
