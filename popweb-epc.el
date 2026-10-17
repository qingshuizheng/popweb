;;; popweb-epc.el --- EPC server and client  -*- lexical-binding: t; -*-

;; Copyright (C) 2011,2012,2013 Masashi Sakurai
;;
;; Author: Masashi Sakurai <m.sakurai at kiwanami.net>
;; Keywords: lisp
;; URL: https://github.com/tkf/emacs-epc
;; Package-Requires: ((emacs "24.4"))

;; This file is not part of GNU Emacs.

;;; License:
;;
;; This program is free software; you can redistribute it and/or modify
;; it under the terms of the GNU General Public License as published by
;; the Free Software Foundation, either version 3 of the License, or
;; (at your option) any later version.
;;
;; This program is distributed in the hope that it will be useful,
;; but WITHOUT ANY WARRANTY; without even the implied warranty of
;; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;; GNU General Public License for more details.
;;
;; You should have received a copy of the GNU General Public License
;; along with this program.  If not, see <http://www.gnu.org/licenses/>.

;;; Commentary:
;;
;; A copy of the `epc' library by Masashi Sakurai (the original file is
;; `epcs.el'), with every symbol prefixed `popweb-'.  EPC is a length
;; prefixed S-expression protocol over a TCP socket: the first six bytes of a
;; message are its length in hexadecimal, the rest is one Lisp form.
;;
;; Popweb uses the client half to call Python methods and the server half to
;; let Python call back into Emacs.  The wire format is the one python-epc
;; implements, so it must not drift; `test/popweb-epc-test.el' pins it.

;;; Code:

(require 'cl-lib)
(require 'subr-x)

(require 'popweb-deferred)

(defvar popweb-epc-debug nil
  "Whether to write the EPC traffic to the `*popweb-epc-log*' buffer.")

(defun popweb-epc-log (&rest args)
  "Write the message made from ARGS to the EPC log buffer.
Nothing happens unless `popweb-epc-debug' is non-nil."
  (when popweb-epc-debug
    (with-current-buffer (get-buffer-create "*popweb-epc-log*")
      (buffer-disable-undo)
      (goto-char (point-max))
      (insert (apply 'format args) "\n\n\n"))))

(defun popweb-epc-make-procbuf (name)
  "Create and return a process buffer called NAME.
The buffer is erased, has undo disabled, and does not ask before it is
killed, because its content is protocol traffic rather than a document."
  (let ((buf (get-buffer-create name)))
    (with-current-buffer buf
      (set (make-local-variable 'kill-buffer-query-functions) nil)
      (erase-buffer) (buffer-disable-undo))
    buf))

(defvar popweb-epc-uid 1
  "Counter that gives every EPC connection and session its own id.
The value is incremented by `popweb-epc-uid' before it is used, so the first
id handed out is 2; that has been the behaviour since the original library.")

(defun popweb-epc-uid ()
  "Increment `popweb-epc-uid' and return the new value."
  (cl-incf popweb-epc-uid))

(defvar popweb-epc-accept-process-timeout 150
  "Milliseconds a synchronous EPC call waits for more input at a time.
`popweb-epc-sync' loops on this value until the answer or an error arrives.")

(put 'epc-error 'error-conditions '(error epc-error))
(put 'epc-error 'error-message "EPC Error")

(cl-defstruct popweb-epc-connection
  "Network connection of an EPC session and the way its events are routed.

name    is used for the process and buffer names.
process is the network process of the connection.
buffer  accumulates incoming bytes until a whole message has arrived.
channel is a list of a name and the observers of the connection."
  name process buffer channel)

(defun popweb-epc-connect (host port)
  "Open a connection to the EPC peer at HOST and PORT.
Return the new `popweb-epc-connection'; its process filter and sentinel
are installed here, so incoming messages reach `popweb-epc-process-filter'
without further setup."
  (popweb-epc-log ">> Connection start: %s:%s" host port)
  (let* ((connection-id (popweb-epc-uid))
         (connection-name (format "popweb-epc con %s" connection-id))
         (connection-buf (popweb-epc-make-procbuf (format "*%s*" connection-name)))
         (connection-process
          (open-network-stream connection-name connection-buf host port))
         (channel (list connection-name nil))
         (connection (make-popweb-epc-connection
                      :name connection-name
                      :process connection-process
                      :buffer connection-buf
                      :channel channel)))
    (popweb-epc-log ">> Connection establish")
    (set-process-coding-system  connection-process 'binary 'binary)
    (set-process-filter connection-process
                        (lambda (p m)
                          (popweb-epc-process-filter connection p m)))
    (set-process-sentinel connection-process
                          (lambda (p e)
                            (popweb-epc-process-sentinel connection p e)))
    (set-process-query-on-exit-flag connection-process nil)
    connection))

(defun popweb-epc-process-sentinel (connection process msg)
  "Handle a state change of PROCESS of CONNECTION, described by MSG.
The connection is torn down on any change, which is what makes
`popweb-epc-live-p' turn nil after the Python process exits."
  (popweb-epc-log "!! Process Sentinel [%s] : %S : %S"
                  (popweb-epc-connection-name connection) process msg)
  (popweb-epc-disconnect connection))

(defun popweb-epc-net-send (connection sexp)
  "Send SEXP to the peer of CONNECTION as one EPC message.
The message is the Lisp form printed without non-ASCII escaping, encoded as
UTF-8, and prefixed with its length in six hexadecimal digits."
  (let* ((msg (encode-coding-string
               (concat (popweb-epc-prin1-to-string sexp) "\n") 'utf-8-unix))
         (string (concat (format "%06x" (length msg)) msg))
         (proc (popweb-epc-connection-process connection)))
    (popweb-epc-log ">> SEND : [%S]" string)
    (process-send-string proc string)))

(defun popweb-epc-disconnect (connection)
  "Close the process of CONNECTION and kill its buffer.
The sentinel is removed first, so `delete-process' does not come back through
`popweb-epc-process-sentinel'."
  (let ((process (popweb-epc-connection-process connection))
        (buf (popweb-epc-connection-buffer connection))
        (name (popweb-epc-connection-name connection)))
    (popweb-epc-log "!! Disconnect [%s]" name)
    (when process
      (set-process-sentinel process nil)
      (delete-process process)
      (when (get-buffer buf) (kill-buffer buf)))
    (popweb-epc-log "!! Disconnected finished [%s]" name)))

(defun popweb-epc-process-filter (connection process message)
  "Append MESSAGE from PROCESS to the buffer of CONNECTION and dispatch it.
MESSAGE is a chunk of the byte stream, not necessarily a whole EPC message;
`popweb-epc-process-available-input' takes the complete ones off the front."
  (popweb-epc-log "INCOMING: [%s] [%S]" (popweb-epc-connection-name connection) message)
  (with-current-buffer (popweb-epc-connection-buffer connection)
    (goto-char (point-max))
    (insert message)
    (popweb-epc-process-available-input connection process)))

(defun popweb-epc-signal-connect (channel event-sym &optional callback)
  "Append an observer for EVENT-SYM to CHANNEL and return a deferred object.
A non-nil EVENT-SYM matches only that signal, while nil matches every signal
of the channel.  When CALLBACK is given, the returned deferred object runs it
asynchronously; further tasks can be connected to that object."
  (let ((d (if callback
               (popweb-deferred-new callback)
             (popweb-deferred-new))))
    (push (cons event-sym d)
          (cddr channel))
    d))

(defun popweb-epc-signal-send (channel event-sym &rest args)
  "Send EVENT-SYM and ARGS to every observer of CHANNEL.
Each observer is a deferred object, and receives one event of the shape
\(EVENT-SYM ARGS), so a callback can destructure both the name and the values."
  (let ((observers (cddr channel))
        (event (list event-sym args)))
    (cl-loop for i in observers
             for name = (car i)
             for d = (cdr i)
             if (or (eq event-sym name) (eq t name))
             do (popweb-deferred-callback-post d event))))

(defun popweb-epc-process-available-input (connection process)
  "Dispatch every complete EPC message that has arrived on CONNECTION.
PROCESS is the connection's process, used for its buffer.  A handler that
signals an error is logged and the loop continues with the next message."
  (with-current-buffer (process-buffer process)
    (while (popweb-epc-net-have-input-p)
      (let ((event (popweb-epc-net-read-or-lose process))
            (ok nil))
        (popweb-epc-log "<< RECV [%S]" event)
        (unwind-protect
            (condition-case err
                (progn
                  (apply 'popweb-epc-signal-send
                         (cons (popweb-epc-connection-channel connection) event))
                  (setq ok t))
              (error (popweb-epc-log "MsgError: %S / <= %S" err event)))
          (unless ok
            (popweb-epc-process-available-input connection process)))))))

(defun popweb-epc-net-have-input-p ()
  "Return non-nil when the current buffer starts with a complete message.
The length prefix is read first, so a partial message is left for the next
call to `popweb-epc-process-filter'."
  (goto-char (point-min))
  (and (>= (buffer-size) 6)
       (>= (- (buffer-size) 6) (popweb-epc-net-decode-length))))

(defun popweb-epc-net-read-or-lose (_process)
  "Read one message, or signal an error that names the problem.
PROCESS is accepted for symmetry with the other `popweb-epc-net-*'
functions; the message is read from the current buffer.  A malformed
message enters the debugger before it is re-signaled as a plain error."
  (condition-case error
      (popweb-epc-net-read)
    (error
     (debug 'error error)
     (error "Net-read error: %S" error))))

(defun popweb-epc-net-read ()
  "Read one complete message from the front of the current buffer.
The length prefix and the form are removed from the buffer, and the form is
decoded from UTF-8 and read as Lisp."
  (goto-char (point-min))
  (let* ((length (popweb-epc-net-decode-length))
         (start (+ 6 (point)))
         (end (+ start length))
         _content)
    (cl-assert (cl-plusp length))
    (prog1 (save-restriction
             (narrow-to-region start end)
             (read (decode-coding-string
                    (buffer-string) 'utf-8-unix)))
      (delete-region (point-min) end))))

(defun popweb-epc-net-decode-length ()
  "Return the length stored in the six hexadecimal bytes at point.
Point is not moved; the caller decides what to do with the number."
  (string-to-number (buffer-substring-no-properties (point) (+ (point) 6)) 16))

(defun popweb-epc-prin1-to-string (sexp)
  "Return SEXP as a string that the EPC peer can read back.
Unlike `prin1-to-string', non-ASCII characters are written as themselves and
newlines are not escaped, which is what python-epc expects."
  (with-temp-buffer
    (let (print-escape-nonascii
          print-escape-newlines
          print-length
          print-level)
      (prin1 sexp (current-buffer))
      (buffer-string))))

(cl-defstruct popweb-epc-manager
  "Everything one EPC session needs, in one object.

title          is the instance name shown on the controller UI.
server-process is the process object of the peer.
commands       is the (PROGRAM . ARGS) that started that process.
port           is the TCP port of the peer.
connection     is the `popweb-epc-connection' of the session.
methods        maps a method name to its `popweb-epc-method'.
sessions       maps a call id to the deferred object that waits for it.
exit-hooks     runs after the session is shut down."
  title server-process commands port connection methods sessions exit-hooks)

(cl-defstruct popweb-epc-method
  "One method that the peer of an EPC session can call.

name      is the method name, a symbol such as `return'.
task      is the function that runs for a call.
arg-specs is a string such as \"(A B C)\", for documentation.
docstring is the one-line description shown by `methods'."
  name task docstring arg-specs)

(defvar popweb-epc-live-connections nil
  "EPC managers of the sessions that are currently connected.
The list is kept for debugging: nothing routes messages through it.")

(defun popweb-epc-server-process-name (uid)
  "Return the process name of the EPC server whose id is UID."
  (format "popweb-epc-server:%s" uid))

(defun popweb-epc-server-buffer-name (uid)
  "Return the buffer name of the EPC server whose id is UID."
  (format " *%s*" (popweb-epc-server-process-name uid)))

(defun popweb-epc-stop-epc (mngr)
  "Disconnect the connection of MNGR and stop its peer process.
The process is asked for pending output first, then killed if it is still
running, and the session is removed from `popweb-epc-live-connections'."
  (let* ((proc (popweb-epc-manager-server-process mngr))
         (buf (and proc (process-buffer proc))))
    (popweb-epc-disconnect (popweb-epc-manager-connection mngr))
    (when proc
      (accept-process-output proc 0 popweb-epc-accept-process-timeout t))
    (when (and proc (equal 'run (process-status proc)))
      (kill-process proc))
    (when buf  (kill-buffer buf))
    (setq popweb-epc-live-connections (delete mngr popweb-epc-live-connections))
    ))

(defun popweb-epc-args (args)
  "Return ARGS itself when it is an atom, or its second element when it is a list.
The EPC protocol wraps an argument list in one more list, and this unwraps
that extra level."
  (cond
   ((atom args) args)
   (t (cadr args))))

(defun popweb-epc-init-epc-layer (mngr)
  "Connect the event handlers of the connection of MNGR.
After this call the manager answers `call', `return', `return-error',
`epc-error' and `methods' messages from the peer.  MNGR is returned."
  (let* ((mngr mngr)
         (conn (popweb-epc-manager-connection mngr))
         (channel (popweb-epc-connection-channel conn)))
    ;; dispatch incoming messages with the lexical scope
    (cl-loop for (method . body) in
             `((call
                . (lambda (args)
                    (popweb-epc-log "SIG CALL: %S" args)
                    (apply 'popweb-epc-handler-called-method ,mngr (popweb-epc-args args))))
               (return
                . (lambda (args)
                    (popweb-epc-log "SIG RET: %S" args)
                    (apply 'popweb-epc-handler-return ,mngr (popweb-epc-args args))))
               (return-error
                . (lambda (args)
                    (popweb-epc-log "SIG RET-ERROR: %S" args)
                    (apply 'popweb-epc-handler-return-error ,mngr (popweb-epc-args args))))
               (epc-error
                . (lambda (args)
                    (popweb-epc-log "SIG EPC-ERROR: %S" args)
                    (apply 'popweb-epc-handler-epc-error ,mngr (popweb-epc-args args))))
               (methods
                . (lambda (args)
                    (popweb-epc-log "SIG METHODS: %S" args)
                    (popweb-epc-handler-methods ,mngr (caadr args))))
               ) do
             (popweb-epc-signal-connect channel method body))
    (push mngr popweb-epc-live-connections)
    mngr))

(defun popweb-epc-manager-send (mngr method &rest messages)
  "Send METHOD and MESSAGES to the peer of MNGR.
METHOD is a symbol, and MESSAGES becomes the argument list of the message."
  (let* ((conn (popweb-epc-manager-connection mngr)))
    (popweb-epc-net-send conn (cons method messages))))

(defun popweb-epc-manager-get-method (mngr method-name)
  "Return the method of MNGR named METHOD-NAME, or nil when it is unknown."
  (cl-loop for i in (popweb-epc-manager-methods mngr)
           if (eq method-name (popweb-epc-method-name i))
           do (cl-return i)))

(defun popweb-epc-handler-methods (mngr uid)
  "Answer the `methods' request UID of MNGR with its registered methods.
Every entry is a list of the method name, its argument specs and its
docstring; missing optional parts become empty strings."
  (let ((info
         (cl-loop for i in (popweb-epc-manager-methods mngr)
                  collect
                  (list
                   (popweb-epc-method-name i)
                   (or (popweb-epc-method-arg-specs i) "")
                   (or (popweb-epc-method-docstring i) "")))))
    (popweb-epc-manager-send mngr 'return uid info)))

(defun popweb-epc-handler-called-method (mngr uid name args)
  "Run the method NAME of MNGR for call UID with ARGS and send the answer.
A method that returns a deferred object answers when that object produces a
value; an unknown method or a signaled error answers with an EPC error."
  (let ((mngr mngr) (uid uid))
    (let* ((_methods (popweb-epc-manager-methods mngr))
           (method (popweb-epc-manager-get-method mngr name)))
      (cond
       ((null method)
        (popweb-epc-log "ERR: No such method : %s" name)
        (popweb-epc-manager-send mngr 'epc-error uid (format "EPC-ERROR: No such method : %s" name)))
       (t
        (condition-case err
            (let* ((f (popweb-epc-method-task method))
                   (ret (apply f args)))
              (cond
               ((popweb-deferred-object-p ret)
                (popweb-deferred-nextc ret
                                       (lambda (xx) (popweb-epc-manager-send mngr 'return uid xx))))
               (t (popweb-epc-manager-send mngr 'return uid ret))))
          (error
           (popweb-epc-log "ERROR : %S" err)
           (popweb-epc-manager-send mngr 'return-error uid err))))))))

(defun popweb-epc-manager-remove-session (mngr uid)
  "Forget the call identified by UID in MNGR.
The deferred object of the call is dropped as well, so a late answer for it
is ignored instead of running its callback."
  (cl-loop with ret = nil
           for pair in (popweb-epc-manager-sessions mngr)
           unless (eq uid (car pair))
           do (push pair ret)
           finally
           do (setf (popweb-epc-manager-sessions mngr) ret)))

(defun popweb-epc-handler-return (mngr uid args)
  "Deliver the successful value ARGS to the call UID of MNGR.
An answer for a call that is no longer waiting is only logged."
  (let ((pair (assq uid (popweb-epc-manager-sessions mngr))))
    (cond
     (pair
      (popweb-epc-log "RET: id:%s [%S]" uid args)
      (popweb-epc-manager-remove-session mngr uid)
      (popweb-deferred-callback (cdr pair) args))
     (t                                 ; error
      (popweb-epc-log "RET: NOT FOUND: id:%s [%S]" uid args)))))

(defun popweb-epc-handler-return-error (mngr uid args)
  "Deliver the remote error ARGS to the call UID of MNGR.
The deferred object sees a string, so an errorback is what runs."
  (let ((pair (assq uid (popweb-epc-manager-sessions mngr))))
    (cond
     (pair
      (popweb-epc-log "RET-ERR: id:%s [%S]" uid args)
      (popweb-epc-manager-remove-session mngr uid)
      (popweb-deferred-errorback (cdr pair) (format "%S" args)))
     (t                                 ; error
      (popweb-epc-log "RET-ERR: NOT FOUND: id:%s [%S]" uid args)))))

(defun popweb-epc-handler-epc-error (mngr uid args)
  "Deliver the EPC level error ARGS to the call UID of MNGR.
The error is wrapped in `epc-error', so callers can tell a protocol failure
from an error raised by the remote method itself."
  (let ((pair (assq uid (popweb-epc-manager-sessions mngr))))
    (cond
     (pair
      (popweb-epc-log "RET-EPC-ERR: id:%s [%S]" uid args)
      (popweb-epc-manager-remove-session mngr uid)
      (popweb-deferred-errorback (cdr pair) (list 'epc-error args)))
     (t                                 ; error
      (popweb-epc-log "RET-EPC-ERR: NOT FOUND: id:%s [%S]" uid args)))))

(defun popweb-epc-call-deferred (mngr method-name args)
  "Call METHOD-NAME of the peer of MNGR with ARGS, without waiting.
Return the deferred object that receives the result; A new session id is
allocated and remembered until the answer arrives."
  (let ((uid (popweb-epc-uid))
        (sessions (popweb-epc-manager-sessions mngr))
        (d (popweb-deferred-new)))
    (push (cons uid d) sessions)
    (setf (popweb-epc-manager-sessions mngr) sessions)
    (popweb-epc-manager-send mngr 'call uid method-name args)
    d))

(defun popweb-epc-define-method (mngr method-name task &optional arg-specs docstring)
  "Make TASK available to the peer of MNGR under METHOD-NAME.
ARG-SPECS and DOCSTRING are optional documentation returned by the `methods'
request.  Return the new `popweb-epc-method' object."
  (let* ((method (make-popweb-epc-method
                  :name method-name :task task
                  :arg-specs arg-specs :docstring docstring))
         (methods (cons method (popweb-epc-manager-methods mngr))))
    (setf (popweb-epc-manager-methods mngr) methods)
    method))

(defun popweb-epc-sync (mngr d)
  "Wait for deferred object D of MNGR and return its value.
Input is accepted from the connection of MNGR while waiting.  A failure is
signaled as an error, so a caller of `popweb-epc-call-sync' sees the remote
error as if it had been raised locally."
  (let ((result 'popweb-epc-nothing))
    (popweb-deferred-chain
     d
     (popweb-deferred-nextc it
                            (lambda (x) (setq result x)))
     (popweb-deferred-error it
                            (lambda (er) (setq result (cons 'error er)))))
    (while (eq result 'popweb-epc-nothing)
      (save-current-buffer
        (accept-process-output
         (popweb-epc-connection-process (popweb-epc-manager-connection mngr))
         0 popweb-epc-accept-process-timeout t)))
    (if (and (consp result) (eq 'error (car result)))
        (error (cdr result)) result)))

(defun popweb-epc-call-sync (mngr method-name args)
  "Call METHOD-NAME of the peer of MNGR with ARGS and return the result.
The call blocks Emacs until the answer arrives; a remote error is signaled."
  (popweb-epc-sync mngr (popweb-epc-call-deferred mngr method-name args)))

(defun popweb-epc-live-p (mngr)
  "Return non-nil when MNGR is an EPC manager with a live connection.
A nil MNGR, a manager that was never connected, and a manager whose process
has exited all return nil instead of signaling."
  (let ((proc (ignore-errors
                (popweb-epc-connection-process (popweb-epc-manager-connection mngr)))))
    (and (processp proc)
         ;; Same as `process-live-p' in Emacs >= 24:
         (memq (process-status proc) '(run open listen connect stop)))))

(defvar popweb-epc-server-client-processes nil
  "Accepted client connections of every EPC server, as (PROCESS . MANAGER).
`popweb-epc-server-sentinel' adds an entry when a client connects and
removes it when the client goes away.")

(defvar popweb-epc-server-processes nil
  "Running EPC servers, as (PROCESS . `popweb-epc-server').
The list is kept for debugging and for shutting servers down at exit.")

(cl-defstruct popweb-epc-server
  "One EPC server and the function that initializes each new client.

name             is the process name of the server.
process          is the server process object.
port             is the TCP port the server listens on.
connect-function runs with the manager of a newly accepted client."
  name process port connect-function)

(defun popweb-epc-server-get-manager-by-process (proc)
  "Return the EPC manager of the accepted client PROC, or nil."
  (cl-loop for (pp . mngr) in popweb-epc-server-client-processes
           if (eql pp proc)
           do (cl-return mngr)
           finally return nil))

(defun popweb-epc-server-accept (process)
  "Turn the accepted client PROCESS into an EPC manager and return it.
The process filter, coding system and sentinel are installed here, so all
further traffic goes through the normal message loop."
  (popweb-epc-log "POPWEB-EPC-SERVER- >> Connection accept: %S" process)
  (let* ((connection-id (popweb-epc-uid))
         (connection-name (format "popweb-epc con %s" connection-id))
         (channel (list connection-name nil))
         (connection (make-popweb-epc-connection
                      :name connection-name
                      :process process
                      :buffer (process-buffer process)
                      :channel channel)))
    (popweb-epc-log "POPWEB-EPC-SERVER- >> Connection establish")
    (set-process-coding-system process 'binary 'binary)
    (set-process-filter process
                        (lambda (p m)
                          (popweb-epc-process-filter connection p m)))
    (set-process-query-on-exit-flag process nil)
    (set-process-sentinel process
                          (lambda (p e)
                            (popweb-epc-process-sentinel connection p e)))
    (make-popweb-epc-manager :server-process process :port t
                             :connection connection)))

(defun popweb-epc-server-sentinel (process message connect-function)
  "Handle a state change of server PROCESS described by MESSAGE.
A new client is accepted, registered and initialized with CONNECT-FUNCTION;
a client that goes away is shut down and forgotten."
  (popweb-epc-log "POPWEB-EPC-SERVER- SENTINEL: %S %S" process message)
  (let ((mngr (popweb-epc-server-get-manager-by-process process)))
    (cond
     ;; new connection
     ((and (string-match "open" message) (null mngr))
      (condition-case err
          (let ((mngr (popweb-epc-server-accept process)))
            (push (cons process mngr) popweb-epc-server-client-processes)
            (popweb-epc-init-epc-layer mngr)
            (when connect-function (funcall connect-function mngr))
            mngr)
        (error
         (popweb-epc-log "POPWEB-EPC-SERVER- Protocol error: %S" err)
         (popweb-epc-log "POPWEB-EPC-SERVER- ABORT %S" process)
         (delete-process process))))
     ;; ignore
     ((null mngr) nil )
     ;; disconnect
     (t
      (let ((pair (assq process popweb-epc-server-client-processes)) _d)
        (when pair
          (popweb-epc-log "POPWEB-EPC-SERVER- DISCONNECT %S" process)
          (popweb-epc-stop-epc (cdr pair))
          (setq popweb-epc-server-client-processes
                (assq-delete-all process popweb-epc-server-client-processes))
          ))
      nil))))

(defun popweb-epc-server-start (connect-function &optional port)
  "Start an EPC server and return its process.
CONNECT-FUNCTION runs with the manager of every new client; PORT is the TCP
port to listen on, and any free port is used when it is nil.  The server only
listens on 127.0.0.1, because nothing outside this machine may call Emacs."
  (let*
      ((connect-function connect-function)
       (name (format "POPWEB EPC Server %s" (popweb-epc-uid)))
       (buf (popweb-epc-make-procbuf (format " *%s*" name)))
       (main-process
        (make-network-process
         :name name
         :buffer buf
         :family 'ipv4
         :server t
         :host "127.0.0.1"
         :service (or port t)
         :noquery t
         :sentinel
         (lambda (process message)
           (popweb-epc-server-sentinel process message connect-function)))))
    (push (cons main-process
                (make-popweb-epc-server
                 :name name :process main-process
                 :port (process-contact main-process :service)
                 :connect-function connect-function))
          popweb-epc-server-processes)
    main-process))

(provide 'popweb-epc)
;;; popweb-epc.el ends here
