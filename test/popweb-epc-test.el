;;; popweb-epc-test.el --- Tests for the EPC wire format  -*- lexical-binding: t; -*-

;;; Commentary:
;; EPC sends a Lisp form with a six digit hexadecimal length in front of it.
;; The tests pin that framing, the UTF-8 decoding, and one complete round trip
;; over a loopback socket: Emacs calls its own server and gets the answer back
;; through the same code path that Python uses.

;;; Code:

(require 'ert)
(require 'popweb-epc)

(defun popweb-epc-test--frame (form)
  "Return FORM as the bytes of one EPC message."
  (let* ((body (concat (popweb-epc-prin1-to-string form) "\n"))
         (encoded (encode-coding-string body 'utf-8-unix)))
    (concat (format "%06x" (length encoded)) encoded)))

(ert-deftest popweb-epc-test-prin1-keeps-non-ascii ()
  "Non-ASCII text is written as itself, so the CL reader reads it back."
  (let ((printed (popweb-epc-prin1-to-string "中文")))
    (should (string-match-p "中" printed))
    (should (equal (read printed) "中文"))))

(ert-deftest popweb-epc-test-prin1-does-not-escape-newlines ()
  "A newline inside a string stays a literal newline in the message."
  (should (string-match-p "\n" (popweb-epc-prin1-to-string "a\nb"))))

(ert-deftest popweb-epc-test-length-prefix-is-six-hex-digits ()
  "The prefix says how many bytes follow it, not how many characters."
  (let ((message (popweb-epc-test--frame '(return 1 "中文"))))
    (should (string-prefix-p "0000" message))
    (should (equal (substring message 0 6) (format "%06x" (- (length message) 6))))))

(ert-deftest popweb-epc-test-have-input-p-accepts-a-whole-message ()
  "A complete message is recognised before it is read."
  (with-temp-buffer
    (set-buffer-multibyte nil)
    (insert (popweb-epc-test--frame '(return 1 "value")))
    (should (popweb-epc-net-have-input-p))))

(ert-deftest popweb-epc-test-have-input-p-rejects-a-partial-message ()
  "A message that has not arrived in full is left in the buffer."
  (with-temp-buffer
    (set-buffer-multibyte nil)
    (insert "000010(return")
    (should-not (popweb-epc-net-have-input-p))))

(ert-deftest popweb-epc-test-have-input-p-needs-the-prefix ()
  "Fewer than six bytes cannot contain a length."
  (with-temp-buffer
    (insert "00001")
    (should-not (popweb-epc-net-have-input-p))))

(ert-deftest popweb-epc-test-read-round-trips-unicode ()
  "Reading a message returns the form that was sent, including UTF-8 text."
  (with-temp-buffer
    (set-buffer-multibyte nil)
    (insert (popweb-epc-test--frame '(return 1 "中文")))
    (should (equal (popweb-epc-net-read) '(return 1 "中文")))
    (should (= (buffer-size) 0))))

(ert-deftest popweb-epc-test-read-leaves-the-next-message ()
  "Only one message is consumed, so a second call reads the next one."
  (with-temp-buffer
    (set-buffer-multibyte nil)
    (insert (popweb-epc-test--frame '(return 1 "one")))
    (insert (popweb-epc-test--frame '(return 2 "two")))
    (should (equal (popweb-epc-net-read) '(return 1 "one")))
    (should (equal (popweb-epc-net-read) '(return 2 "two")))))

(ert-deftest popweb-epc-test-decode-length ()
  "The six hexadecimal bytes at point are read as a number."
  (with-temp-buffer
    (insert "00003c")
    (goto-char (point-min))
    (should (= (popweb-epc-net-decode-length) 60))))

(ert-deftest popweb-epc-test-args-unwraps-a-list ()
  "EPC adds one level of list around the arguments; `epc-args' removes it."
  (should (equal (popweb-epc-args '(1 2 3)) 2))
  (should (equal (popweb-epc-args 'atom) 'atom)))

(ert-deftest popweb-epc-test-define-and-find-a-method ()
  "A method is stored on the manager and found by name."
  (let* ((mngr (make-popweb-epc-manager))
         (method (popweb-epc-define-method mngr 'ping #'ignore "(VALUE)" "Ping.")))
    (should (eq (popweb-epc-manager-get-method mngr 'ping) method))
    (should (null (popweb-epc-manager-get-method mngr 'missing)))
    (should (equal (popweb-epc-method-arg-specs method) "(VALUE)"))
    (should (equal (popweb-epc-method-docstring method) "Ping."))))

(ert-deftest popweb-epc-test-live-p-is-safe-without-a-manager ()
  "A manager that was never connected is not live."
  (should-not (popweb-epc-live-p nil))
  (should-not (popweb-epc-live-p (make-popweb-epc-manager))))

(ert-deftest popweb-epc-test-loopback-round-trip ()
  "A call reaches the server's method and its result comes back to the caller."
  (let* ((server-accepted nil)
         (received nil)
         (server (popweb-epc-server-start
                  (lambda (mngr)
                    (popweb-epc-define-method
                     mngr 'ping (lambda (value) (setq received value) "pong"))
                    (setq server-accepted t))))
         (port (process-contact server :service))
         (client (make-popweb-epc-manager
                  :connection (popweb-epc-connect "127.0.0.1" port))))
    (unwind-protect
        (progn
          (popweb-epc-init-epc-layer client)
          ;; The server accepts the connection in its sentinel, which runs
          ;; while we wait for process output.
          (with-timeout (5 (error "The EPC server did not accept the connection"))
            (while (not server-accepted)
              (accept-process-output nil 0.01)))
          ;; `popweb-epc-call-sync' waits on the client process alone, which
          ;; cannot make progress here because the server lives in this same
          ;; Emacs; pump every process and the deferred queue instead.
          (let* ((call (popweb-epc-call-deferred client 'ping '("hello")))
                 (result 'waiting))
            (popweb-deferred-nextc call (lambda (value) (setq result value)))
            (with-timeout (5 (error "The EPC call did not return"))
              (while (eq result 'waiting)
                (accept-process-output nil 0.01)
                (popweb-deferred-worker)))
            (should (equal result "pong"))
            (should (equal received "hello"))))
      (popweb-epc-disconnect (popweb-epc-manager-connection client))
      (dolist (pair popweb-epc-server-client-processes)
        (popweb-epc-stop-epc (cdr pair)))
      (delete-process server)
      (setq popweb-epc-server-client-processes nil))))

(provide 'popweb-epc-test)
;;; popweb-epc-test.el ends here
