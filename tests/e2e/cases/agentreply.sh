#!/usr/bin/env bash
# Agents answer helpdesk notifications by e-mail (two phases: thread ids and hashes only exist after the first import).
# 1. normal parallel fetch  2. for ~36 imported conversations write into the IMAP Maildirs: valid replies (FS_notify-<thread>-<user>-<md5 hash>), replies with a wrong hash,
#    and a notification forwarded ("Fwd:") into ANOTHER mailbox  3. fetch again (parallel, then sequential, then once more: idempotent).
# check.php: valid replies = message threads by the right agent in the right conversation (also from agent6's alternate address), forwards open a conversation, bad hashes leave nothing.
HERE=$(cd "$(dirname "$0")/.." && pwd); WORK=$HERE/.work
php_env() { docker exec -e APP_ENV=local -e APP_KEY="$(cat $WORK/appkey)" -e DB_HOST=odtest-db -e DB_DATABASE=e2e -e DB_USERNAME=e2e -e DB_PASSWORD=e2e \
  -e CACHE_DRIVER=file -e SESSION_DRIVER=file -e QUEUE_DRIVER=sync -e E2E_IMAP_HOST=odtest-imap "$@"; }
run() { php_env -e APP_FETCH_PARALLEL=$1 odtest-php php artisan freescout:fetch-emails --days=7 2>&1 | grep -iE 'exception|fatal|deadlock|SQLSTATE' | head -5; }
run 4
docker cp $HERE/agent_targets.php odtest-php:/tmp/agent_targets.php
php_env odtest-php php /tmp/agent_targets.php 36 > $WORK/targets.json
python3 - $WORK <<'PY'
import json, sys, time, random, email.utils, subprocess
work = sys.argv[1]
t = json.load(open(f"{work}/targets.json")); exp = json.load(open(f"{work}/expected.json"))
rnd = random.Random(7)
agents = [f"agent{n}@helpdesk.example" for n in range(1, 6)] + ["agent6.alt@helpdesk.example"]
uid = lambda a: t["users"]["agent6@helpdesk.example" if a.startswith("agent6") else a]
mbs = sorted({x["mb"] for x in t["targets"]}) or ["mb1@test.local"]
checks, used_addrs, convs, threads = [], set(), 0, 0
def deliver(mb, n, raw):
    p = f"{work}/mail/{mb}/Maildir/new/agentreply-{n}.gen"
    open(p, "w", encoding="utf-8").write(raw); subprocess.run(["chmod", "666", p])
for n, x in enumerate(t["targets"]):
    a = agents[n % len(agents)]
    mid = f"<agentreply-{n}@helpdesk.example>"
    ts = time.time() - 120 - n
    ntf = lambda h: f"<FS_notify-{x['tid']}-{uid(a)}-{h}@helpdesk.example>"
    mode = "bad" if n % 6 == 5 else "fwd" if n % 6 == 4 else "reply"
    to = x["mb"]
    if mode == "bad": nid = ntf(rnd.choice(["0123456789abcdef", "deadbeef", "0" * 32]))
    else: nid = ntf(x["hash"])
    subj = f"Re: [#{x['number']}] {x['subject']}"
    if mode == "fwd":
        to = next((m for m in mbs if m != x["mb"]), None) or f"mb{(int(x['mb'][2:x['mb'].index('@')]) % 20) + 1}@test.local"
        subj = f"Fwd: [#{x['number']}] {x['subject']}"
    h = [f"Message-ID: {mid}", f"Date: {email.utils.formatdate(ts)}", f"From: {email.utils.formataddr(('Agent ' + a[5], a))}", f"To: {to}", f"Subject: {subj}", "MIME-Version: 1.0",
         f"In-Reply-To: {nid}", f"References: {nid}", "Content-Type: text/plain; charset=utf-8", "Content-Transfer-Encoding: 7bit"]
    body = f"Agent answer {n}: thank you for your message, we are looking into it.\n"
    deliver(to, n, "\n".join(h) + "\n\n" + body)
    m = mid.strip("<>")
    if mode == "reply": checks.append([m, x["cid"], uid(a), "reply"]); threads += 1; used_addrs.add(a)
    elif mode == "fwd": checks.append([m, x["cid"], uid(a), "fwd"]); threads += 1; convs += 1; used_addrs.add(a)
    else: checks.append([m, 0, 0, "none"])
exp["conversations"] += convs; exp["threads"] += threads
exp["customers"] = t["customers"] + len({a for a in used_addrs if a not in t["known"]})
exp["agent_reply_checks"] = checks
json.dump(exp, open(f"{work}/expected.json", "w"))
PY
docker cp $WORK/expected.json odtest-php:/tmp/expected.json
run 4
run 1
run 4
exit 0
