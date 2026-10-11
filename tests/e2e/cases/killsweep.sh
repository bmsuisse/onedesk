#!/usr/bin/env bash
# Killed with SIGKILL at several points (1s..5s, incl. mid-mailbox, mid-extra-import), resumed each time: nothing may be lost or doubled.
# Sourced env/functions come from run.sh (php_env, fetch); this file runs as a child, so re-declare what it needs.
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
for t in 1 2 3 4 5; do
  php_env odtest-php timeout -s KILL $t php artisan freescout:fetch-emails --days=7 >/dev/null 2>&1 || true
done
php_env odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5 || true
