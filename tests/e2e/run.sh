#!/usr/bin/env bash
# End-to-end fetch tests + benchmark: real IMAP (Dovecot) + real DB + the real `freescout:fetch-emails`.
# Needs docker only. Everything runs in odtest-* containers; your .env and database are never touched.
#
#   tests/e2e/run.sh test  [quick|full|huge]   up -> cases A-D -> down   (exit 1 on failure)
#   tests/e2e/run.sh up    [quick|full|huge]   start containers, migrate, seed mailboxes
#   tests/e2e/run.sh fresh                     regenerate mails (SEED=, VARIETY=), wipe imported rows
#   tests/e2e/run.sh bench [mailbox ids|all]   fresh + one fetch, print metrics JSON (wall, cpu, queries, mem)
#   tests/e2e/run.sh profile [mailbox ids|all] fresh + one fetch under the Excimer sampler, print top 25 functions (self / inclusive)
#   tests/e2e/run.sh case  <A|B|C|D|...>       fresh + one case + assertions (containers must be up)
#   tests/e2e/run.sh exec  <cmd...>            run a command in the php container (e.g. artisan, php -l)
#   tests/e2e/run.sh down
# Profiles: quick 10x100 (~1k mails), full 40x300 (12k), huge 100x500 (50k). Override MAILBOXES= MAILS= PAR=.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO=$PWD; HERE=$REPO/tests/e2e; WORK=$HERE/.work; NET=odtest-net
CMD=${1:-test}; shift || true
STATE=$WORK/state.env

step() { printf '\n== %s\n' "$*"; }
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
sql() { docker exec odtest-db mariadb -ue2e -pe2e e2e -e "$1"; }
load() { [ -f $STATE ] || { echo "run '$0 up' first"; exit 2; }; source $STATE; }

up() {
  case "${1:-quick}" in quick) N=10; M=100;; full) N=40; M=300;; huge) N=100; M=500;; *) echo "profile: quick|full|huge"; exit 2;; esac
  N=${MAILBOXES:-$N}; M=${MAILS:-$M}
  mkdir -p $WORK; echo "N=$N; M=$M" > $STATE; [ -f $WORK/appkey ] || echo "base64:$(openssl rand -base64 32)" > $WORK/appkey
  step "images"
  docker image inspect onedesk-e2e-php >/dev/null 2>&1 || docker build -q -t onedesk-e2e-php -f $HERE/docker/php74.Dockerfile $HERE/docker >/dev/null
  docker image inspect onedesk-e2e-dovecot >/dev/null 2>&1 || docker build -q -t onedesk-e2e-dovecot -f $HERE/docker/dovecot.Dockerfile $HERE/docker >/dev/null
  step "containers"
  down >/dev/null 2>&1 || true
  docker network create $NET >/dev/null 2>&1 || true
  # MariaDB: native on arm64 (no emulation noise in timings), drop-in for the MySQL 5.7 schema used here.
  docker run -d --name odtest-db --network $NET -e MARIADB_ROOT_PASSWORD=root -e MARIADB_DATABASE=e2e -e MARIADB_USER=e2e -e MARIADB_PASSWORD=e2e \
    --memory ${DB_MEM:-2g} mariadb:10.11 --innodb-buffer-pool-size=512M --max-connections=200 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci --innodb-flush-log-at-trx-commit=2 >/dev/null
  # Overlay bootstrap/cache and storage with scratch dirs: the repo's cached dev config (host od-db) must not win over our env, and fresh() must not wipe dev attachments.
  rm -rf $WORK/bootcache $WORK/storage; mkdir -p $WORK/bootcache $WORK/storage/app $WORK/storage/logs $WORK/storage/framework/{cache,sessions,views}
  docker run -d --name odtest-php --network $NET --memory ${PHP_MEM:-3g} -v "$REPO":/app -v $WORK/bootcache:/app/bootstrap/cache -v $WORK/storage:/app/storage -w /app onedesk-e2e-php sleep infinity >/dev/null
  until docker exec odtest-db mariadb -ue2e -pe2e -e 'select 1' >/dev/null 2>&1; do sleep 2; done
  step "migrate + seed $N mailboxes"
  php_env odtest-php php artisan package:discover >/dev/null 2>&1 || true
  php_env odtest-php php artisan migrate --force -n >/dev/null
  fresh
  php_env odtest-php php /app/tests/e2e/seed.php $N
}

fresh() {  # regenerate N x M unread mails (SEED, VARIETY env), restart IMAP, wipe imported rows
  load
  docker rm -f odtest-imap >/dev/null 2>&1 || true
  rm -rf $WORK/mail && SEED=${SEED:-42} VARIETY=${VARIETY:-99} python3 $HERE/gen.py $N $M $WORK/mail 2>$WORK/gen.log && chmod -R a+rwX $WORK/mail
  docker run -d --name odtest-imap --network $NET --memory 512m -v $WORK/mail:/mail -v $WORK/users:/etc/dovecot/users -v $HERE/docker/dovecot.conf:/etc/dovecot/dovecot.conf onedesk-e2e-dovecot >/dev/null
  sql "SET FOREIGN_KEY_CHECKS=0; TRUNCATE threads; TRUNCATE conversations; TRUNCATE customers; TRUNCATE emails; TRUNCATE attachments; TRUNCATE polycast_events; SET FOREIGN_KEY_CHECKS=1;" 2>/dev/null
  docker exec odtest-php sh -c 'rm -rf /app/storage/app/attachment/* 2>/dev/null; true'
  php_env odtest-php php artisan freescout:clear-cache >/dev/null 2>&1 || true
  rm -f $WORK/bootcache/config.php   # clear-cache re-caches config: that would freeze APP_FETCH_PARALLEL (case B was never parallel) and DB env
  docker cp $WORK/expected.json odtest-php:/tmp/expected.json
  sleep 2
}

alive() { local c; for c in odtest-db odtest-php odtest-imap; do [ "$(docker inspect -f '{{.State.Running}}' $c 2>/dev/null)" = true ] || { echo "CONTAINER DIED: $c (OOM? see docker inspect $c, lower PAR/profile)"; return 1; }; done; }
fetch() { alive || return 1; php_env -e APP_FETCH_PARALLEL=${PAR:-1} odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5 || true; }
check() { alive || return 1; php_env odtest-php php /app/tests/e2e/check.php /tmp/expected.json; }

case_run() {  # name -> prints PASS/FAIL, returns 1 on failure
  local c=$1; load; step "case $c ($N mailboxes x $M mails)"; fresh
  local t0=$(date +%s)
  case $c in
    A) fetch;;                                                         # sequential, all in one run
    B) PAR=${PAR:-4} fetch;;                                           # parallel mailboxes; PAR max 4 (8 OOMs the shared 8GB docker VM)
    C) php_env odtest-php timeout 3 php artisan freescout:fetch-emails --days=7 >/dev/null 2>&1 || true; fetch;;   # killed mid-run, resumed
    D) fetch; fetch;;                                                  # idempotent second run
    *) if [ -x "$HERE/cases/$c.sh" ]; then "$HERE/cases/$c.sh"; else echo "unknown case $c"; return 2; fi;;
  esac
  echo "elapsed $(( $(date +%s) - t0 ))s"
  check && echo "PASS $c" || { echo "FAIL $c"; return 1; }
}

bench() {  # fresh + one fetch with metrics
  load; fresh
  php_env odtest-php php /app/tests/e2e/bench.php "${1:-all}"
}

profile() {  # fresh + one fetch under the sampling profiler
  load; fresh
  php_env odtest-php php /app/tests/e2e/profile.php "${1:-all}"
}

down() { docker rm -f odtest-db odtest-imap odtest-php >/dev/null 2>&1 || true; docker network rm $NET >/dev/null 2>&1 || true; }

case $CMD in
  up) up "${1:-quick}";;
  fresh) fresh;;
  profile) profile "${1:-all}";;
  bench) bench "${1:-all}";;
  case) case_run "$1";;
  exec) php_env odtest-php "$@";;
  down) down;;
  test) trap down EXIT; up "${1:-quick}"; F=0
        for c in A B C D $(ls $HERE/cases 2>/dev/null | sed 's/\.sh$//'); do case_run $c || F=1; done
        step result; [ $F -eq 0 ] && echo "ALL E2E CASES PASSED" || { echo "E2E FAILED"; exit 1; };;
  *) sed -n '2,16p' "$0"; exit 2;;
esac
