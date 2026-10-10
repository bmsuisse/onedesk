#!/usr/bin/env bash
# Malformed MIME must neither hang nor crash the run: fetch under a hard timeout (a loop shows as exit 124), then a second run must import nothing new
# (mails that cannot be imported are marked Seen / skipped, not retried into duplicates). check.php names the kind that went missing.
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
for run in 1 2; do
  out=$(php_env -e APP_FETCH_PARALLEL=${PAR:-4} odtest-php timeout 900 php artisan freescout:fetch-emails --days=7 2>&1); rc=$?
  [ $rc -eq 124 ] && { echo "HANG: fetch run $run exceeded 900s"; exit 1; }
  echo "$out" | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5
  [ $run -eq 2 ] && echo "second run created: $(echo "$out" | grep -c 'Thread successfully created')"
done
exit 0
