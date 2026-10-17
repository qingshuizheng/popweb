;;; popweb-deferred-test.el --- Tests for popweb-deferred  -*- lexical-binding: t; -*-

;;; Commentary:
;; The deferred library is vendored, but the parts popweb depends on are the
;; queue semantics: a callback runs with the value, an errorback with the
;; error, and a queued task runs from the worker.

;;; Code:

(require 'ert)
(require 'popweb-deferred)

(ert-deftest popweb-deferred-test-chain-passes-it ()
  "Each form of the chain sees the previous value as `it'."
  (should (equal (popweb-deferred-chain (+ 1 2) (* it 2) (list it)) '(6))))

(ert-deftest popweb-deferred-test-new-defaults-to-identity ()
  "A deferred object without a callback returns its value unchanged."
  (should (equal (popweb-deferred-callback (popweb-deferred-new) 42) 42)))

(ert-deftest popweb-deferred-test-callback-gets-the-value ()
  "The callback is called with the value and its result is returned."
  (let (seen)
    (should (equal (popweb-deferred-callback
                    (popweb-deferred-new (lambda (value) (push value seen) (* value 2)))
                    21)
                   42))
    (should (equal seen '(21)))))

(ert-deftest popweb-deferred-test-errorback-gets-the-error ()
  "The errorback is called with the error value."
  (let* ((d (popweb-deferred-new))
         (seen nil))
    (setf (popweb-deferred-object-errorback d) (lambda (err) (push err seen)))
    (popweb-deferred-errorback d "boom")
    (should (equal seen '("boom")))))

(ert-deftest popweb-deferred-test-nextc-runs-the-continuation ()
  "A continuation attached with `nextc' receives the first value."
  (let ((popweb-deferred-queue nil)
        (d (popweb-deferred-new))
        (seen nil))
    (popweb-deferred-nextc d (lambda (value) (push value seen)))
    (popweb-deferred-callback d 7)
    (should (null seen))
    (popweb-deferred-worker)
    (should (equal seen '(7)))))

(ert-deftest popweb-deferred-test-error-runs-the-errorback-continuation ()
  "An error continuation receives the error of the previous object."
  (let* ((popweb-deferred-queue nil)
         (seen nil)
         (d (popweb-deferred-new)))
    (popweb-deferred-error d (lambda (err) (push err seen)))
    (popweb-deferred-errorback d "failed")
    (popweb-deferred-worker)
    ;; The default errorback resignals the string as an `error' condition, so
    ;; the continuation sees that condition rather than the original string.
    (should (eq (car (car seen)) 'error))
    (should (equal (cadr (car seen)) "failed"))))

(ert-deftest popweb-deferred-test-default-cancel-disarms-the-object ()
  "Cancelling removes both callbacks and the continuation."
  (let* ((d (popweb-deferred-new))
         (next (popweb-deferred-new)))
    (setf (popweb-deferred-object-next d) next)
    (popweb-deferred-default-cancel d)
    (should (eq (popweb-deferred-object-callback d) 'identity))
    (should (eq (popweb-deferred-object-errorback d) 'popweb-deferred-resignal))
    (should (null (popweb-deferred-object-next d)))))

(ert-deftest popweb-deferred-test-resignal-keeps-a-known-error ()
  "An error condition is re-signaled with its own type."
  (should-error (popweb-deferred-resignal '(error "Boom")) :type 'error))

(ert-deftest popweb-deferred-test-resignal-wraps-an-unknown-value ()
  "A value that is not a condition becomes a plain error."
  (should-error (popweb-deferred-resignal 42) :type 'error))

(ert-deftest popweb-deferred-test-worker-consumes-the-queue ()
  "The worker runs the queued task and empties the queue."
  (let* ((popweb-deferred-queue nil)
         (seen nil)
         (d (popweb-deferred-new (lambda (value) (push value seen)))))
    (popweb-deferred-post-task d 'ok "value")
    (should (= (length popweb-deferred-queue) 1))
    (popweb-deferred-worker)
    (should (null popweb-deferred-queue))
    (should (equal seen '("value")))))

(ert-deftest popweb-deferred-test-worker-without-a-queue-does-nothing ()
  "An empty queue is not an error, because the timer may fire late."
  (setq popweb-deferred-queue nil)
  (should (null (popweb-deferred-worker))))

(provide 'popweb-deferred-test)
;;; popweb-deferred-test.el ends here
