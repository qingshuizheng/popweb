;;; popweb-process-test.el --- Tests for popweb-process  -*- lexical-binding: t; -*-

;;; Commentary:
;; Starting the Python process is split from the code that talks to it, so the
;; command line can be checked by replacing `start-process'.  The environment
;; builder is pure and is checked for each platform branch.  The idle timer is
;; disabled before the library is loaded: no test wants a real process.

;;; Code:

(require 'ert)

(require 'popweb-process)

(setq popweb-start-python-process-when-require nil)

(defun popweb-process-test--env-value (name environment)
  "Return the value of NAME in ENVIRONMENT, or nil."
  (let ((entry (seq-find (lambda (item) (string-prefix-p (concat name "=") item)) environment)))
    (when entry (substring entry (1+ (length name))))))

(ert-deftest popweb-process-test-environment-drops-owned-qt-variables ()
  "The Qt scaling variables of Emacs itself are not inherited."
  (let ((system-type 'darwin)
        (window-system 'ns)
        (process-environment '("PATH=/bin" "QT_SCALE_FACTOR=2" "QT_SCREEN_SCALE_FACTOR=2")))
    (let ((environment (popweb--build-process-environment)))
      (should (member "PATH=/bin" environment))
      (should-not (seq-find (lambda (item) (string-prefix-p "QT_SCALE_FACTOR" item)) environment))
      (should-not (seq-find (lambda (item) (string-prefix-p "QT_SCREEN_SCALE_FACTOR" item))
                            environment)))))

(ert-deftest popweb-process-test-environment-adds-linux-x11-values ()
  "An X11 session gets the XCB platform and no automatic scaling."
  (let ((system-type 'gnu/linux)
        (window-system 'x)
        (popweb-enable-debug nil)
        (process-environment '("PATH=/bin")))
    (let ((environment (popweb--build-process-environment)))
      (should (equal (popweb-process-test--env-value "QT_AUTO_SCREEN_SCALE_FACTOR" environment) "0"))
      (should (equal (popweb-process-test--env-value "QT_FONT_DPI" environment) "96"))
      (should (equal (popweb-process-test--env-value "QT_SCALE_FACTOR" environment) "1"))
      (should (equal (popweb-process-test--env-value "QTWEBENGINE_CHROMIUM_FLAGS" environment)
                     "--disable-web-security"))
      (should (equal (popweb-process-test--env-value "QT_QPA_PLATFORM" environment) "xcb")))))

(ert-deftest popweb-process-test-environment-enables-wayland-scaling ()
  "A native Wayland session needs the automatic scale factor and no XCB."
  (let ((system-type 'gnu/linux)
        (window-system 'pgtk)
        (popweb-enable-debug nil)
        (process-environment '("PATH=/bin")))
    (let ((environment (popweb--build-process-environment)))
      (should (equal (popweb-process-test--env-value "QT_AUTO_SCREEN_SCALE_FACTOR" environment) "1"))
      (should-not (popweb-process-test--env-value "QT_QPA_PLATFORM" environment)))))

(ert-deftest popweb-process-test-environment-adds-debug-plugin-logging ()
  "Debug mode asks Qt to print why a plugin failed to load."
  (let ((system-type 'darwin)
        (window-system 'ns)
        (popweb-enable-debug t)
        (process-environment '("PATH=/bin")))
    (let ((environment (popweb--build-process-environment)))
      (should (equal (popweb-process-test--env-value "QT_DEBUG_PLUGINS" environment) "1")))))


(ert-deftest popweb-process-test-wsl-detection ()
  "Only a Linux Emacs running a Windows Python is the WSL case."
  (let ((system-type 'gnu/linux)
        (popweb-python-command "python.exe"))
    (should (popweb--called-from-wsl-on-windows-p)))
  (let ((system-type 'gnu/linux)
        (popweb-python-command "python3"))
    (should-not (popweb--called-from-wsl-on-windows-p)))
  (let ((system-type 'darwin)
        (popweb-python-command "python.exe"))
    (should-not (popweb--called-from-wsl-on-windows-p))))

(defmacro popweb-process-test--with-stubbed-start (&rest body)
  "Run BODY with a recorded `start-process' and no EPC server."
  (declare (indent 0))
  `(let ((popweb-epc-process nil)
         (popweb-server nil)
         (popweb-server-port nil)
         (popweb-python-command "python3")
         (popweb-enable-debug nil)
         (started nil))
     (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) nil))
               ((symbol-function 'popweb--start-epc-server)
                (lambda ()
                  (setq popweb-server-port 4321)
                  'server))
               ((symbol-function 'popweb--build-process-environment)
                (lambda () '("PATH=/bin")))
               ((symbol-function 'start-process)
                (lambda (name buffer program &rest args)
                  (setq started (list name buffer program args))
                  'fake-process))
               ((symbol-function 'set-process-query-on-exit-flag) (lambda (_process _flag) nil)))
       ,@body)))

(ert-deftest popweb-process-test-start-process-command-line ()
  "The child is the Python file plus the EPC port of Emacs."
  (popweb-process-test--with-stubbed-start
    (popweb-start-process)
    (should (equal started
                   (list popweb-name popweb-name "python3"
                         (list popweb-python-file "4321"))))
    (should (eq popweb-internal-process 'fake-process))
    (should (equal popweb-internal-process-prog "python3"))
    (should (equal popweb-internal-process-args (list popweb-python-file "4321")))))

(ert-deftest popweb-process-test-start-process-under-gdb ()
  "Debug mode runs the interpreter through gdb in batch mode."
  (popweb-process-test--with-stubbed-start
    (setq popweb-enable-debug t)
    (popweb-start-process)
    (should (equal (nth 2 started) "gdb"))
    (should (equal (nth 3 started)
                   (list "-batch" "-ex" "run" "-ex" "bt" "--args"
                         "python3" popweb-python-file "4321")))))

(ert-deftest popweb-process-test-start-when-live-calls-at-once ()
  "When the process is up the callback runs immediately."
  (let ((called nil))
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) t))
              ((symbol-function 'popweb-start-process) (lambda () (error "Must not start"))))
      (popweb-start (lambda (args) (setq called args)) '(t "value"))
      (should (equal called '(t "value"))))))

(ert-deftest popweb-process-test-start-when-dead-remembers-the-arguments ()
  "When the process is down the callback waits for the handshake."
  (let ((started nil)
        (popweb--first-start-args nil)
        (popweb--first-start-pending nil)
        (popweb--first-start-callback nil))
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) nil))
              ((symbol-function 'popweb-start-process) (lambda () (setq started t))))
      (popweb-start #'ignore '(t "value"))
      (should started)
      (should (equal popweb--first-start-args '(t "value")))
      (should popweb--first-start-pending)
      (should (eq popweb--first-start-callback #'ignore)))))

(ert-deftest popweb-process-test-first-start-runs-the-waiting-callback ()
  "The port from Python builds the manager, then the callback runs."
  (let* ((delivered nil)
         (layers nil)
         (captured-manager nil)
         (popweb-internal-process 'fake-process)
         (popweb-internal-process-prog "python3")
         (popweb-internal-process-args '("popweb.py" "1234"))
         (popweb--first-start-args '(t "value"))
         (popweb--first-start-pending t)
         (popweb--first-start-callback (lambda (args) (setq delivered args))))
    (cl-letf (((symbol-function 'make-popweb-epc-manager)
               (lambda (&rest plist)
                 (setq captured-manager plist)
                 'manager))
              ((symbol-function 'popweb-epc-connect) (lambda (_host _port) 'connection))
              ((symbol-function 'popweb-epc-init-epc-layer)
               (lambda (manager) (push manager layers) manager)))
      (popweb--first-start 9999))
    (should (eq popweb-epc-process 'manager))
    (should (equal (plist-get captured-manager :port) 9999))
    (should (equal (plist-get captured-manager :connection) 'connection))
    (should (equal layers '(manager)))
    (should (equal delivered '(t "value")))
    (should-not popweb--first-start-pending)
    (should (null popweb--first-start-args))))

(ert-deftest popweb-process-test-first-start-calls-back-with-no-arguments ()
  "A callback queued with nil arguments still runs after the handshake."
  (let* ((called 0)
         (popweb-internal-process 'fake-process)
         (popweb-internal-process-prog "python3")
         (popweb-internal-process-args '("popweb.py" "1234"))
         (popweb--first-start-args nil)
         (popweb--first-start-pending t)
         (popweb--first-start-callback (lambda (_args) (cl-incf called))))
    (cl-letf (((symbol-function 'make-popweb-epc-manager) (lambda (&rest _) 'manager))
              ((symbol-function 'popweb-epc-connect) (lambda (_host _port) 'connection))
              ((symbol-function 'popweb-epc-init-epc-layer) #'ignore))
      (popweb--first-start 9999))
    (should (= called 1))
    (should-not popweb--first-start-pending)))

(ert-deftest popweb-process-test-kill-process-runs-the-hook-then-stops ()
  "Extensions can clean up before the process disappears."
  (let ((hook-ran nil)
        (killed nil))
    (let ((popweb-stop-process-hook (list (lambda () (setq hook-ran t)))))
      (cl-letf (((symbol-function 'popweb--kill-python-process) (lambda () (setq killed t))))
        (popweb-kill-process)))
    (should hook-ran)
    (should killed)))

(ert-deftest popweb-process-test-kill-python-process-cleans-up ()
  "Cleanup is requested, the EPC manager stopped and the buffer killed."
  (let ((popweb-name "*popweb-test-buffer*")
        (calls nil)
        (stopped nil)
        (popweb-epc-process 'manager))
    (get-buffer-create popweb-name)
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) t))
              ((symbol-function 'popweb-call-async)
               (lambda (method &rest args) (push (cons method args) calls)))
              ((symbol-function 'popweb-epc-stop-epc)
               (lambda (manager) (setq stopped manager))))
      (popweb--kill-python-process))
    (should (equal calls '(("cleanup"))))
    (should (eq stopped 'manager))
    (should (null (get-buffer popweb-name)))))

(ert-deftest popweb-process-test-kill-python-process-is-safe-when-dead ()
  "Stopping a process that is not running does nothing."
  (let ((popweb-epc-process nil))
    (cl-letf (((symbol-function 'popweb-epc-live-p) (lambda (_manager) nil))
              ((symbol-function 'popweb-epc-stop-epc) (lambda (_manager) (error "Must not stop"))))
      (popweb--kill-python-process))))

(ert-deftest popweb-process-test-idle-start-honours-the-option ()
  "The idle timer body starts a process only when the option is on."
  (let ((calls 0))
    (cl-letf (((symbol-function 'popweb-start-process) (lambda () (cl-incf calls))))
      (let ((popweb-start-python-process-when-require nil))
        (popweb--start-when-required)
        (should (= calls 0)))
      (let ((popweb-start-python-process-when-require t))
        (popweb--start-when-required)
        (should (= calls 1))))))

(provide 'popweb-process-test)
;;; popweb-process-test.el ends here
