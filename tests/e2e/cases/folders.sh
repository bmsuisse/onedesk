#!/usr/bin/env bash
# Several IMAP folders per mailbox (INBOX + Archive / Sent / Zürich, a configured folder that does not exist), already \Seen mails mixed with unseen ones, flagged / answered / deleted
# mails: killed runs, one parallel run, then the server hands the imported mails back as unseen (not the ones that were \Seen from the start) for two more runs.
# Beyond check.php's counts: after the import no unseen mail may be left in ANY folder, no mail may be added or lost, and the flags other than \Seen must survive setSeen().
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
run() { php_env -e APP_FETCH_PARALLEL=$1 odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5; }
count() { local n=0 c; for u in $(cut -d: -f1 $WORK/users); do c=$(docker exec odtest-imap doveadm search -u "$u" "$@" 2>/dev/null | wc -l); n=$((n + c)); done; echo $n; }
unsee() { for u in $(cut -d: -f1 $WORK/users); do docker exec odtest-imap doveadm flags remove -u "$u" '\Seen' not header X-E2E-Kind seen 2>&1 | head -2; done; }
exp() { python3 -c "import json,sys; e=json.load(open('$WORK/expected.json')); print(eval(sys.argv[1]))" "$1"; }
total0=$(count all); seen0=$(count seen)
for t in 1 2 3; do php_env odtest-php timeout -s KILL $t php artisan freescout:fetch-emails --days=7 >/dev/null 2>&1 || true; done
run 4
rc=0
left=$(count unseen)
[ "$left" = 0 ] || { echo "FOLDERS-FAIL: $left mails still unseen after the import"; rc=1; }
[ "$(count all)" = "$total0" ] || { echo "FOLDERS-FAIL: mails in the folders changed: $total0 -> $(count all)"; rc=1; }
for f in "flagged:flagged" "answered:answered" "deleted:deleted" "draft:draft"; do
  want=$(exp "e['t11_flags']['${f%%:*}']"); got=$(count "${f##*:}")
  [ "$got" = "$want" ] || { echo "FOLDERS-FAIL: ${f%%:*} mails after the import: $got != $want (setSeen must not drop other flags)"; rc=1; }
done
unsee; run 1; unsee; run 4
[ "$(count unseen)" = 0 ] || { echo "FOLDERS-FAIL: $(count unseen) mails unseen after the re-runs"; rc=1; }
[ "$(count seen)" -ge "$seen0" ] || { echo "FOLDERS-FAIL: seen mails lost"; rc=1; }
exit $rc
