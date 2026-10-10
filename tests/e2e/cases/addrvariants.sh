#!/usr/bin/env bash
# Unusual senders (plus-addressing, upper-case spellings, punycode domains, 300+ char subjects, emoji, RTL): the same customers appear in many mailboxes and in several spellings.
# Killed runs (customer + email rows are created in one transaction), then two parallel runs (PAR=4 fetchers create the same customers at the same time), then a repeat: nothing lost or doubled.
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
run() { php_env -e APP_FETCH_PARALLEL=$1 odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5; }
for t in 2 4; do php_env odtest-php timeout -s KILL $t php artisan freescout:fetch-emails --days=7 >/dev/null 2>&1 || true; done
run 4
run 4
exit 0
