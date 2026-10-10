#!/usr/bin/env bash
# A copy for another mailbox (To/Cc fan-out) is lost after the original was imported (transient failure / kill between commit and setSeen), and the target mailbox
# does not hold the mail itself (single-recipient and Bcc-only copies are not fanned out, so those are left alone): the original mail, unseen again, must be retried and recreate exactly the missing copy (no duplicates anywhere).
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
sql() { docker exec odtest-db mariadb -ue2e -pe2e e2e -N -e "$1" 2>/dev/null; }
run() { php_env -e APP_FETCH_PARALLEL=1 odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5; }
run
# Copies live under an artificial Message-ID: their stored headers carry the original one.
sql "SELECT m.email, c.id, REGEXP_SUBSTR(t.headers, '(?i)message-id: *<[^>]+>') FROM threads t JOIN conversations c ON c.id=t.conversation_id JOIN mailboxes m ON m.id=c.mailbox_id
     WHERE c.subject LIKE '%FAN-%' AND t.first=1 AND INSTR(t.headers, t.message_id) = 0 AND INSTR(t.headers, m.email) > 0 AND t.headers REGEXP '(?im)^(to:[^\r\n]*,|cc:)' AND (SELECT COUNT(*) FROM threads x WHERE x.conversation_id=c.id) = 1" | while IFS=$'\t' read -r mb cid hdr; do
  mid=$(echo "$hdr" | sed -E 's/^[^<]*<([^>]+)>.*/\1/')
  sql "SET FOREIGN_KEY_CHECKS=0; DELETE FROM attachments WHERE thread_id IN (SELECT id FROM threads WHERE conversation_id=$cid); DELETE FROM threads WHERE conversation_id=$cid; DELETE FROM conversations WHERE id=$cid; SET FOREIGN_KEY_CHECKS=1"
  docker exec odtest-imap doveadm expunge -u "$mb" mailbox INBOX header message-id "$mid" 2>&1 | head -2
done
for u in $(cut -d: -f1 $WORK/users); do docker exec odtest-imap doveadm flags remove -u "$u" '\Seen' all 2>&1 | head -2; done
run
exit 0
