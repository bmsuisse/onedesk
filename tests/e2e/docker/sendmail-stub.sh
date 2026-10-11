#!/bin/sh
# sendmail replacement for PHP mail() in the e2e `send` case: stores the raw message (stdin) in /app/storage/sink/mail-NNNN.eml, args in .args
d=/app/storage/sink; mkdir -p $d; n=$(ls $d | grep -c '\.eml$'); f=$d/mail-$(printf %04d $((n+1)))
echo "$@" > $f.args; cat > $f.eml
