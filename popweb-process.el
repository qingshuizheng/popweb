;;; popweb-process.el --- Lifecycle of the popweb Python process  -*- lexical-binding: t; -*-

;; Copyright (C) 2021 Andy Stewart
;;
;; Author: Andy Stewart <lazycat.manatee@gmail.com>
;; Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
;; Created: 2021-11-13
;; Keywords: tools
;; URL: https://github.com/manateelazycat/popweb
;; Package-Requires: ((emacs "27.1"))

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
;; along with this program; see the file COPYING.  If not, write to the
;; Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor,
;; Boston, MA 02110-1301, USA.

;;; Commentary:
;;
;; Emacs starts one Python process per session and talks to it over EPC.  The
;; handshake has two steps: this side opens an EPC server, the Python side
;; opens its own server and reports the port back through `popweb--first-start',
;; and only then does Emacs have an EPC manager it can call.
;;
;; `popweb-start' hides that handshake from the extensions.  They hand it a
;; callback and the arguments for the callback; the callback runs immediately
;; when the process is already up, and after the handshake when it is not.
;;
;; The environment of the child process is adjusted here as well: Qt decides
;; screen scaling and input backend from environment variables, and inheriting
;; the ones that belong to the Emacs process is how a popup ends up half the
;; intended size.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)

(require 'popweb-config)
(require 'popweb-ipc)

(defconst popweb-directory
  (file-name-directory (or load-file-name buffer-file-name default-directory))
  "Directory that holds popweb's Elisp and Python files.
It is resolved when this file is loaded, so byte compiled and source loads
agree as long as popweb.py is installed next to this file.")

(defconst popweb-python-file (expand-file-name "popweb.py" popweb-directory)
  "Absolute file name of the Python entry point that Emacs starts.")

(defvar popweb-server nil
  "Process object of the EPC server that Python calls back into.
The value is nil until `popweb--start-epc-server' has run.")

(defvar popweb-server-port nil
  "Port number of the EPC server in `popweb-server'.
It is kept separately because the port is what Python is told on its command
line, and `process-contact' is not available on every platform.")

(defvar popweb-internal-process nil
  "Process object of the Python side of popweb.")

(defvar popweb-internal-process-prog nil
  "Program that `popweb-internal-process' runs.
It is the interpreter from `popweb-python-command', or gdb when
`popweb-enable-debug' is on.")

(defvar popweb-internal-process-args nil
  "Command line arguments passed to `popweb-internal-process-prog'.")

(defvar popweb--first-start-args nil
  "Arguments to hand to the first-start callback after the handshake.
`popweb-start' stores them here when the process is not up yet, and
`popweb--first-start' consumes them.")

(defvar popweb--first-start-pending nil
  "Whether a first-start callback is waiting for the handshake.
The flag is separate from `popweb--first-start-args' because a callback may
legitimately be started with no arguments, and that must not look like \"no
callback is waiting\".")

(defvar popweb--first-start-callback nil
  "Function to call once the Python side is ready.
It receives the argument list that was given to `popweb-start'.")

(defvar popweb-stop-process-hook nil
  "Hook run before the Python process is stopped.
Extensions use it to drop any state that only makes sense while the process
is alive; it is an abnormal hook and its return value is ignored.")

(defun popweb-emacs-running-in-wayland-native ()
  "Return non-nil when Emacs draws its frames with native Wayland.
The check matters for Qt, not for Emacs: a native Wayland session and an
XWayland session need opposite values of `QT_AUTO_SCREEN_SCALE_FACTOR'."
  (eq window-system 'pgtk))

(defun popweb--build-process-environment ()
  "Return the environment for the Python child process.
`process-environment' is inherited, minus any Qt scaling variable that would
make Qt scale the popup twice.  On GNU/Linux the Qt platform and scaling
variables are then added back with the values that match the session;
macOS and Windows get no additions, because their Qt builds do not read
them."
  (let ((environments (seq-filter
                       (lambda (var)
                         (and (not (string-match-p "QT_SCALE_FACTOR" var))
                              (not (string-match-p "QT_SCREEN_SCALE_FACTOR" var))))
                       process-environment)))
    (when popweb-enable-debug
      (cl-pushnew "QT_DEBUG_PLUGINS=1" environments :test #'equal))

    (unless (eq system-type 'darwin)
      (cl-pushnew
       (if (popweb-emacs-running-in-wayland-native)
           ;; Wayland native needs the automatic factor, otherwise the Qt
           ;; window only covers half of the screen.
           "QT_AUTO_SCREEN_SCALE_FACTOR=1"
         ;; XWayland needs the factor off, otherwise a Qt build that enables
         ;; high DPI by itself is scaled twice.
         "QT_AUTO_SCREEN_SCALE_FACTOR=0")
       environments :test #'equal)

      (cl-pushnew "QT_FONT_DPI=96" environments :test #'equal)

      ;; Keep the scale factor at one and let the zoom factor of the web page
      ;; do the work; this is what makes 4K screens usable.
      (cl-pushnew "QT_SCALE_FACTOR=1" environments :test #'equal)

      ;; Popups load pages from local files, so the same-origin policy would
      ;; reject every request the page makes to the site it previews.
      (cl-pushnew "QTWEBENGINE_CHROMIUM_FLAGS=--disable-web-security"
                  environments :test #'equal)

      ;; Only a real X11 session can use XCB for input events.
      (when (and (eq system-type 'gnu/linux)
                 (not (popweb-emacs-running-in-wayland-native)))
        (cl-pushnew "QT_QPA_PLATFORM=xcb" environments :test #'equal)))
    environments))

(defun popweb--called-from-wsl-on-windows-p ()
  "Return non-nil when Emacs runs in WSL and Python is a Windows program.
In that combination the child process cannot use a pty for its standard
input, so `popweb-start-process' has to use a pipe instead."
  (and (eq system-type 'gnu/linux)
       (string-match-p ".exe" popweb-python-command)))

(defun popweb--start-epc-server ()
  "Start the EPC server that Python calls back into and return its process.
The server answers three methods: `eval-in-emacs', `get-emacs-var' and
`get-emacs-vars'.  Starting it twice is a no-op; the existing server is
returned."
  (unless (process-live-p popweb-server)
    (setq popweb-server
          (popweb-epc-server-start
           (lambda (mngr)
             (let ((mngr mngr))
               (popweb-epc-define-method mngr 'eval-in-emacs 'popweb--eval-in-emacs-func)
               (popweb-epc-define-method mngr 'get-emacs-var 'popweb--get-emacs-var-func)
               (popweb-epc-define-method mngr 'get-emacs-vars 'popweb--get-emacs-vars-func)))))
    (if popweb-server
        (setq popweb-server-port (process-contact popweb-server :service))
      (error "[POPWEB] popweb-server failed to start")))
  popweb-server)

(defun popweb-start-process ()
  "Start the Python process unless it is already running.
The EPC server is started first, because its port is one of the arguments of
the child process.  The command line is exactly `popweb-python-file' plus
that port; the interpreter and the environment are the only parts that vary
between platforms and debug modes."
  (unless (popweb-epc-live-p popweb-epc-process)
    (popweb--start-epc-server)
    (let* ((popweb-args (append
                         (list popweb-python-file)
                         (list (number-to-string popweb-server-port))))
           environments)

      (setq environments (popweb--build-process-environment))

      (if popweb-enable-debug
          (progn
            (setq popweb-internal-process-prog "gdb")
            (setq popweb-internal-process-args
                  (append (list "-batch" "-ex" "run" "-ex" "bt" "--args"
                                popweb-python-command)
                          popweb-args)))
        (setq popweb-internal-process-prog popweb-python-command)
        (setq popweb-internal-process-args popweb-args))

      (let ((process-connection-type (not (popweb--called-from-wsl-on-windows-p)))
            (process-environment environments))
        (setq popweb-internal-process
              (apply #'start-process
                     popweb-name popweb-name
                     popweb-internal-process-prog popweb-internal-process-args)))
      (set-process-query-on-exit-flag popweb-internal-process nil))))

(defun popweb--start-when-required ()
  "Start the Python process at load time when the user asked for it.
This is the body of the idle timer controlled by
`popweb-start-python-process-when-require'; it is a named function so that
the timer can be identified and cancelled."
  (when popweb-start-python-process-when-require
    (popweb-start-process)))

(defun popweb--first-start (popweb-epc-port)
  "Finish the handshake for the Python process listening on POPWEB-EPC-PORT.
Call it from the `popweb--first-start' method of the Python side; it builds
the EPC manager, registers the reply handlers, and then runs the callback that
was waiting for the process."
  (setq popweb-epc-process (make-popweb-epc-manager
                            :server-process popweb-internal-process
                            :commands (cons popweb-internal-process-prog
                                            popweb-internal-process-args)
                            :title (mapconcat #'identity
                                              (cons popweb-internal-process-prog
                                                    popweb-internal-process-args)
                                              " ")
                            :port popweb-epc-port
                            :connection (popweb-epc-connect "127.0.0.1" popweb-epc-port)))
  (popweb-epc-init-epc-layer popweb-epc-process)
  (when popweb--first-start-pending
    (funcall popweb--first-start-callback popweb--first-start-args))
  (setq popweb--first-start-pending nil
        popweb--first-start-args nil))

(defun popweb-start (first-start-callback args)
  "Run FIRST-START-CALLBACK with ARGS once the Python process is up.
When the process is already running the callback runs immediately; otherwise
it is remembered until `popweb--first-start' has finished the handshake."
  (setq popweb--first-start-callback first-start-callback)

  (if (popweb-epc-live-p popweb-epc-process)
      (funcall first-start-callback args)

    (setq popweb--first-start-pending t
          popweb--first-start-args args)
    (popweb-start-process)))

;;;###autoload
(defun popweb-restart-process ()
  "Stop the Python process and start it again."
  (interactive)
  (popweb-kill-process)
  (popweb-start-process)
  (message "Popweb process restarted."))

;;;###autoload
(defun popweb-kill-process ()
  "Stop the Python process and kill its output buffer."
  (interactive)

  ;; Extensions drop their state before the process that owns it disappears.
  (run-hooks 'popweb-stop-process-hook)

  (popweb--kill-python-process))

;;;###autoload
(defun popweb--kill-python-process ()
  "Stop the Python process and kill the buffer named by `popweb-name'."
  (interactive)
  (when (popweb-epc-live-p popweb-epc-process)
    ;; Let the Python side close its EPC client before the socket goes away.
    (popweb-call-async "cleanup")
    (popweb-epc-stop-epc popweb-epc-process)
    (when (get-buffer popweb-name)
      (kill-buffer popweb-name))
    (message "[POPWEB] Process terminated.")))

(run-with-idle-timer 1 nil #'popweb--start-when-required)

(provide 'popweb-process)
;;; popweb-process.el ends here
