#!/usr/bin/env bash
# Out-of-office / bounce storms: the server redelivers every mail as UNSEEN (flags lost, mailbox re-synced) after an import: a parallel run, then a sequential run that must
# find every mail again and import NOTHING twice (auto-reply loops share subject and body, extra copies live under artificial Message-IDs, bounces have no In-Reply-To match).
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
run() { php_env -e APP_FETCH_PARALLEL=$1 odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5; }
unsee() { for u in $(cut -d: -f1 $WORK/users); do docker exec odtest-imap doveadm flags remove -u "$u" '\Seen' not header X-E2E-Kind seen 2>&1 | head -2; done; }
run 4
unsee
run 1
unsee
run 4
exit 0
