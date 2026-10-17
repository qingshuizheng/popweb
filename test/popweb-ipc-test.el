;;; popweb-ipc-test.el --- Tests for popweb-ipc  -*- lexical-binding: t; -*-

;;; Commentary:
;; The encoding rules of the bridge: Base64 of UTF-8 in both directions, the
;; quoting convention that lets Python pass symbols and lists, and the two
;; call wrappers that hide the deferred object.

;;; Code:

(require 'ert)
(require 'popweb-ipc)

(defun popweb-ipc-test--encode (value)
  "Return VALUE encoded the way Python encodes an argument."
  (base64-encode-string (encode-coding-string value 'utf-8)))

(defun popweb-ipc-test--concat (left right)
  "Return LEFT and RIGHT concatenated."
  (concat left right))

(defun popweb-ipc-test--count (&rest values)
  "Return how many VALUES there are."
  (length values))

(defun popweb-ipc-test--symbol-name (symbol)
  "Return the name of SYMBOL as a string."
  (symbol-name symbol))

(defvar popweb-ipc-test--boolean t
  "Non-nil means the test variable is true.")

(defvar popweb-ipc-test--string "value"
  "A string variable used to check the flag that comes back from Python.")

(ert-deftest popweb-ipc-test-encode-decode-round-trip ()
  "A string survives the trip through Base64, including newlines."
  (let ((text "中文 with a newline\nand a quote \" and a paren )"))
    (should (equal (popweb--decode-string (popweb--encode-string text)) text))))

(ert-deftest popweb-ipc-test-encode-handles-long-strings ()
  "A long string is split into Base64 lines and still decodes."
  (let ((text (make-string 200 ?x)))
    (should (string-match-p "\n" (popweb--encode-string text)))
    (should (equal (popweb--decode-string (popweb--encode-string text)) text))))

(ert-deftest popweb-ipc-test-decode-argument-plain-string ()
  "An argument without a prefix stays a string."
  (should (equal (popweb--decode-argument (popweb-ipc-test--encode "hello")) "hello")))

(ert-deftest popweb-ipc-test-decode-argument-quoted-form ()
  "A leading quote makes Python able to pass a symbol or a number."
  (should (eq (popweb--decode-argument (popweb-ipc-test--encode "'dark")) 'dark))
  (should (= (popweb--decode-argument (popweb-ipc-test--encode "'42")) 42)))

(ert-deftest popweb-ipc-test-decode-argument-list ()
  "A parenthesized argument becomes a list of strings."
  (should (equal (popweb--decode-argument (popweb-ipc-test--encode "(a b c)"))
                 '("a" "b" "c"))))

(ert-deftest popweb-ipc-test-decode-argument-empty-list ()
  "Empty parentheses are an empty list, not a list with one empty string."
  (should (equal (popweb--decode-argument (popweb-ipc-test--encode "()")) '())))

(ert-deftest popweb-ipc-test-eval-in-emacs-applies-the-function ()
  "The first argument names the function and the rest are its arguments."
  (should (equal (popweb--eval-in-emacs-func
                  "popweb-ipc-test--concat"
                  (popweb-ipc-test--encode "left")
                  (popweb-ipc-test--encode "right"))
                 "leftright")))

(ert-deftest popweb-ipc-test-eval-in-emacs-decodes-each-kind ()
  "Plain, quoted and list arguments are all decoded before the call."
  (should (= (popweb--eval-in-emacs-func
              "popweb-ipc-test--count"
              (popweb-ipc-test--encode "plain")
              (popweb-ipc-test--encode "'42")
              (popweb-ipc-test--encode "(a b)"))
             3)))

(ert-deftest popweb-ipc-test-eval-in-emacs-passes-a-symbol ()
  "A quoted argument reaches the Emacs function as a symbol."
  (should (equal (popweb--eval-in-emacs-func
                  "popweb-ipc-test--symbol-name"
                  (popweb-ipc-test--encode "'dark"))
                 "dark")))

(ert-deftest popweb-ipc-test-get-emacs-var-reports-a-boolean ()
  "The reply marks a boolean value as such, so Python can convert it."
  (let ((result (popweb--get-emacs-var-func "popweb-ipc-test--boolean")))
    (should (equal (nth 0 result) t))
    (should (equal (nth 1 result) "t"))))

(ert-deftest popweb-ipc-test-get-emacs-var-marks-a-string-as-not-boolean ()
  "A string value is not marked as a boolean."
  (let ((result (popweb--get-emacs-var-func "popweb-ipc-test--string")))
    (should (equal (nth 0 result) "value"))
    (should (equal (nth 1 result) "nil"))))

(ert-deftest popweb-ipc-test-get-emacs-vars-keeps-the-order ()
  "Several variables come back in the order they were asked for."
  (let ((result (popweb--get-emacs-vars-func
                 "popweb-ipc-test--string"
                 "popweb-ipc-test--boolean")))
    (should (equal (mapcar #'car result)
                   '("value" t)))))

(ert-deftest popweb-ipc-test-call-async-reads-the-method-name ()
  "The method string becomes a symbol and the arguments stay a list."
  (let ((calls nil))
    (cl-letf (((symbol-function 'popweb-epc-call-deferred)
               (lambda (manager method args)
                 (push (list manager method args) calls)
                 'deferred)))
      (let ((popweb-epc-process 'manager))
        (should (eq (popweb-call-async "call_module_method" "path" 1)
                    'deferred))))
    (should (equal calls '((manager call_module_method ("path" 1)))))))

(ert-deftest popweb-ipc-test-call-sync-reads-the-method-name ()
  "The synchronous call uses the same method and argument shape."
  (let ((calls nil))
    (cl-letf (((symbol-function 'popweb-epc-call-sync)
               (lambda (manager method args)
                 (push (list manager method args) calls)
                 "result")))
      (let ((popweb-epc-process 'manager))
        (should (equal (popweb-call-sync "hide_web_window" "name") "result"))))
    (should (equal calls '((manager hide_web_window ("name")))))))

(provide 'popweb-ipc-test)
;;; popweb-ipc-test.el ends here
