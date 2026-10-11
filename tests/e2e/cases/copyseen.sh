#!/usr/bin/env bash
# An extra-mailbox copy must not mark the IMAP mail Seen: the copies of one mail are imported one after the other and another copy may still fail transiently.
# Setup: normal run, then lose every fanned-out copy (rows + the IMAP mail of the target mailbox, like copyretry), make creating conversations in the highest mailbox id (copied last) fail with a lock
# wait timeout (1205, transient) and fetch (the sibling copies are created/dup-checked first and must not mark the mail Seen), then lift the failure: the missing copies must appear.
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
sql() { docker exec odtest-db mariadb -ue2e -pe2e e2e -N -e "$1" 2>/dev/null; }
run() { php_env -e APP_FETCH_PARALLEL=1 odtest-php php artisan freescout:fetch-emails --days=7 > $WORK/copyseen.log 2>&1; grep -iE 'exception|fatal|deadlock|SQLSTATE' $WORK/copyseen.log | grep -v 'Lock wait timeout' | head -5; }
run
ROWS=$(sql "SELECT m.id, m.email, c.id, REGEXP_SUBSTR(t.headers, '(?i)message-id: *<[^>]+>') FROM threads t JOIN conversations c ON c.id=t.conversation_id JOIN mailboxes m ON m.id=c.mailbox_id
     WHERE c.subject LIKE '%FAN-%' AND t.first=1 AND INSTR(t.headers, t.message_id) = 0 AND INSTR(t.headers, m.email) > 0 AND t.headers REGEXP '(?im)^(to:[^\r\n]*,|cc:)' AND (SELECT COUNT(*) FROM threads x WHERE x.conversation_id=c.id) = 1")
TARGET=$(echo "$ROWS" | cut -f1 | sort -n | tail -1)
[ -n "$TARGET" ] || { echo "no extra copies to lose"; exit 1; }
echo "$ROWS" | while IFS=$'\t' read -r mbid mb cid hdr; do
  mid=$(echo "$hdr" | sed -E 's/^[^<]*<([^>]+)>.*/\1/')
  sql "SET FOREIGN_KEY_CHECKS=0; DELETE FROM attachments WHERE thread_id IN (SELECT id FROM threads WHERE conversation_id=$cid); DELETE FROM threads WHERE conversation_id=$cid; DELETE FROM conversations WHERE id=$cid; SET FOREIGN_KEY_CHECKS=1"
  docker exec odtest-imap doveadm expunge -u "$mb" mailbox INBOX header message-id "$mid" 2>&1 | head -2
done
for u in $(cut -d: -f1 $WORK/users); do docker exec odtest-imap doveadm flags remove -u "$u" '\Seen' not header X-E2E-Kind seen 2>&1 | head -2; done
sql "DROP TRIGGER IF EXISTS e2e_block"
echo "lost copies: $(echo "$ROWS" | wc -l), target mailbox $TARGET: $(echo "$ROWS" | awk -F'\t' -v t=$TARGET '$1==t' | wc -l); conversations now $(sql 'SELECT COUNT(*) FROM conversations')"
sql "DELIMITER //
CREATE TRIGGER e2e_block BEFORE INSERT ON conversations FOR EACH ROW BEGIN IF NEW.mailbox_id = $TARGET THEN SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 1205, MESSAGE_TEXT = 'Lock wait timeout exceeded (e2e)'; END IF; END//
DELIMITER ;"
[ "$(sql "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_name='e2e_block'")" = 1 ] || { echo "trigger not created"; exit 1; }
run
echo "after blocked run: $(sql 'SELECT COUNT(*) FROM conversations'), blocked errors $(grep -c 'Lock wait' $WORK/copyseen.log)"
sql "DROP TRIGGER e2e_block"
run
exit 0
