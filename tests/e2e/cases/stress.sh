#!/usr/bin/env bash
# Stress mix: parallel fetchers (PAR=4, never above) killed with SIGKILL at several points and resumed, then a full run, then a second full run that must import nothing.
# check.php (run after this case) asserts the final counts; the "second run imports nothing" part is asserted here by comparing row counts around it.
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
sql() { docker exec odtest-db mariadb -ue2e -pe2e e2e -N -e "$1" 2>/dev/null; }
run() { php_env -e APP_FETCH_PARALLEL=4 odtest-php "$@" php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5 || true; }
for t in 2 3 5 4 7 3; do
  php_env -e APP_FETCH_PARALLEL=4 odtest-php timeout -s KILL $t php artisan freescout:fetch-emails --days=7 >/dev/null 2>&1 || true
  docker exec odtest-php pkill -9 -f 'freescout:fetch-emails' >/dev/null 2>&1 || true   # parallel children outlive the killed parent
done
run
before=$(sql "select (select count(*) from conversations),(select count(*) from threads),(select count(*) from customers),(select count(*) from attachments),(select count(*) from emails)")
run
after=$(sql "select (select count(*) from conversations),(select count(*) from threads),(select count(*) from customers),(select count(*) from attachments),(select count(*) from emails)")
[ "$before" = "$after" ] || { echo "second run changed counts: [$before] -> [$after]"; exit 1; }
