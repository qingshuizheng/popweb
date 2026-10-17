#!/bin/sh
# Byte-compile the elisp sources and check every docstring.
#
#   scripts/check-elisp.sh                  # every tracked and new .el file
#   scripts/check-elisp.sh popweb-dict.el   # just these
#
# .elc output goes to $ELC_DIR (default /tmp/popweb-elc) so the working tree
# stays clean.  The extensions are on the load path because their files require
# `popweb' by name and each other by name.
set -eu
cd "$(dirname "$0")/.."

EMACS=${EMACS:-emacs}
ELC_DIR=${ELC_DIR:-/tmp/popweb-elc}
LOAD_PATH="-L ."
for directory in extension/*/; do
    LOAD_PATH="$LOAD_PATH -L ${directory%/}"
done
LOAD_PATH="$LOAD_PATH -L test"

if [ "$#" -gt 0 ]; then
    FILES=$*
else
    FILES=$(git ls-files --cached --others --exclude-standard '*.el' | sort \
            | while read -r f; do [ -f "$f" ] && echo "$f"; done | tr '\n' ' ')
fi
COUNT=$(echo "$FILES" | wc -w | tr -d ' ')

FILES_LISP=""
for f in $FILES; do FILES_LISP="$FILES_LISP \"$f\""; done

redir="(progn
  (make-directory \"$ELC_DIR\" t)
  (setq byte-compile-dest-file-function
        (lambda (f) (expand-file-name (concat (file-name-nondirectory f) \"c\")
                                      \"$ELC_DIR\"))))"

# A file whose last form is missing a closing paren still reads the forms
# before it, so its warning count silently drops instead of failing.  Walk the
# top level of every file first and stop on the first unbalanced one.
echo "== read every top-level form"
# shellcheck disable=SC2086
$EMACS -Q --batch $LOAD_PATH -l scripts/check-forms.el \
    --eval "(z/check-forms $FILES_LISP)"

# A definition whose body was lost still reads and still compiles: a `defun'
# that is only a docstring silently returns nil.  Walk the definitions before
# compiling anything.
echo "== every definition has a body"
# shellcheck disable=SC2086
$EMACS -Q --batch $LOAD_PATH -l scripts/check-bodies.el \
    --eval "(z/check-bodies $FILES_LISP)"

echo "== byte-compile $COUNT file(s) -> $ELC_DIR"
# shellcheck disable=SC2086
compile_out=$($EMACS -Q --batch $LOAD_PATH --eval "$redir" -f batch-byte-compile $FILES 2>&1) || {
    printf '%s\n' "$compile_out"
    exit 1
}
printf '%s\n' "$compile_out" | grep -v '^$' | grep -v '^Loading ' || true
WARNINGS=$(printf '%s\n' "$compile_out" | grep -c 'Warning' || true)
if [ "$WARNINGS" -gt 0 ]; then
    echo "FAILED: $WARNINGS byte-compile warning(s); the tree is kept at zero"
    exit 1
fi

# A file can compile cleanly in the batch above and still fail on its own: the
# batch is sorted, so a file that only defines a variable another file reads
# first may be compiled after it.  Compiling every file with only its requires
# on the load path is what catches that.
echo "== byte-compile each file on its own"
for f in $FILES; do
    if ! out=$($EMACS -Q --batch $LOAD_PATH --eval "$redir" -f batch-byte-compile "$f" 2>&1); then
        echo "FAILED: $f does not compile on its own"
        printf '%s\n' "$out" | grep -E 'Error:|Cannot open load file|Symbol' || printf '%s\n' "$out" | tail -5
        exit 1
    fi
done
echo "   every file compiles on its own"

echo "== checkdoc"
# checkdoc writes to stderr as "Warning (emacs): ...", so a run that finds
# anything has to be counted rather than trusted to the exit code.
# shellcheck disable=SC2086
doc_out=$($EMACS -Q --batch $LOAD_PATH --eval "$redir" --eval \
    "(dolist (f (list $FILES_LISP)) (checkdoc-file f))" 2>&1)
printf '%s\n' "$doc_out" | grep -v '^$' || true
DOC_FINDINGS=$(printf '%s\n' "$doc_out" | grep -c 'Warning (emacs)' || true)
if [ "$DOC_FINDINGS" -gt 0 ]; then
    echo "FAILED: $DOC_FINDINGS checkdoc finding(s)"
    exit 1
fi
