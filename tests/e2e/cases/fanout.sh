#!/usr/bin/env bash
# Mails delivered to several mailboxes (same Message-ID, extra_import) while mailboxes are fetched in parallel, a run is SIGKILLed mid-way, and runs are repeated:
# whichever mailbox wins the race for a Message-ID, every target mailbox must end up with exactly one conversation/thread (check.php: fan_groups, burst_senders).
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
php_env -e APP_FETCH_PARALLEL=4 odtest-php timeout -s KILL 4 php artisan freescout:fetch-emails --days=7 >/dev/null 2>&1 || true
for run in 1 2 3; do
  php_env -e APP_FETCH_PARALLEL=4 odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5
done
exit 0
