# Shared helpers for the web / send / queue / module / golden suites (sourced). Everything runs inside the odtest-* containers.
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); WORK=$HERE/.work; REPO=$(cd "$HERE/../.." && pwd)
ENVV=(-e APP_ENV=local -e APP_URL=${E2E_APP_URL:-http://e2e.test} -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e
      -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e E2E_IMAP_HOST=odtest-imap)
php_env() { docker exec -e APP_KEY="$(cat $WORK/appkey)" "${ENVV[@]}" "$@"; }
art() { php_env -e QUEUE_DRIVER=${QD:-sync} odtest-php php artisan "$@"; }
phpx() { php_env -e QUEUE_DRIVER=${QD:-sync} odtest-php php "$@"; }
sql() { docker exec odtest-db mariadb -ue2e -pe2e e2e -N -e "$1"; }
# assertion helpers: ok/bad count failures in $FAILS, print one line each
FAILS=0; PASSES=0
ok()  { PASSES=$((PASSES+1)); echo "  ok   $*"; }
bad() { FAILS=$((FAILS+1)); echo "  FAIL $*"; }
expect() { local what=$1 want=$2 got=$3; [ "$got" = "$want" ] && ok "$what" || bad "$what: expected [$want], got [$got]"; }
summary() { echo "  -- $1: $PASSES passed, $FAILS failed"; [ $FAILS -eq 0 ]; }
fixture() { phpx /app/tests/e2e/fixture.php | tail -1; }
web_up() {  # php artisan serve on http://localhost:8089 (4 workers), container odtest-web
  docker rm -f odtest-web >/dev/null 2>&1; mkdir -p $WORK/builds   # scratch overlay: vars.js bakes APP_URL (the dev checkout has http://localhost), keep the repo untouched
  docker run -d --name odtest-web --network odtest-net -p 8089:8000 --memory 1g -v "$REPO":/app -v $WORK/bootcache:/app/bootstrap/cache -v $WORK/storage:/app/storage -v $WORK/builds:/app/public/js/builds -w /app \
    -e APP_KEY="$(cat $WORK/appkey)" -e APP_ENV=local -e APP_DEBUG=true -e APP_URL=http://127.0.0.1:8089 -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
    -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=${QD:-sync} -e PHP_CLI_SERVER_WORKERS=4 "${@}" ${PHPIMG:-onedesk-e2e-php85} php artisan serve --host=0.0.0.0 --port=8000 >/dev/null
  docker exec odtest-web php artisan freescout:generate-vars >/dev/null 2>&1
  local i; for i in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:8089/login && return 0; sleep 2; done; echo "odtest-web did not come up"; return 1
}
web_down() { docker rm -f odtest-web >/dev/null 2>&1 || true; }
