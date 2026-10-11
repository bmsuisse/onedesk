#!/usr/bin/env bash
# send: every outgoing-mail path against a mail sink. SMTP (per-mailbox config, AUTH, queue id) and PHP mail() (sendmail stub); mailables ReplyToCustomer (+attachment, unicode),
# AutoReply, UserNotification, Test. Raw MIME is captured, asserted semantically (mime_check.py) and compared with golden/mime/*.eml.  SEND_RECORD=1 rewrites the goldens.
source "$(dirname "$0")/../lib.sh"
SINK=$WORK/storage/sink
sink_reset() { rm -rf $SINK; mkdir -p $SINK; chmod 777 $SINK; }
docker rm -f odtest-smtp >/dev/null 2>&1
docker run -d --name odtest-smtp --network odtest-net --memory 128m -v $HERE/docker/smtp_sink.py:/sink.py -v $SINK:/sink python:3.12-slim python -u /sink.py >/dev/null || { echo "cannot start sink"; exit 2; }
until docker exec odtest-php php -r 'exit(@fsockopen("odtest-smtp", 2525) ? 0 : 1);' 2>/dev/null; do sleep 1; done
trap 'docker rm -f odtest-smtp >/dev/null 2>&1' EXIT
RC=0
for mode in smtp mail; do
  echo "== send via $mode"
  sink_reset; fixture >/dev/null
  if [ $mode = smtp ]; then out=$(phpx /app/tests/e2e/send.php smtp 2>&1)
  else out=$(phpx -d sendmail_path=/app/tests/e2e/docker/sendmail-stub.sh /app/tests/e2e/send.php mail 2>&1); fi
  echo "$out" | grep -v '^$' | head -8
  python3 $HERE/mime_check.py $mode $SINK ${SEND_RECORD:+--record} || RC=1
done
exit $RC
