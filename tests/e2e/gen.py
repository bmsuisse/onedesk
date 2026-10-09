#!/usr/bin/env python3
"""Generate realistic Maildirs for the mock IMAP server plus the counts a correct fetch must produce.

usage: gen.py MAILBOXES MAILS_PER_MAILBOX OUTDIR
writes OUTDIR/<user>/Maildir/{cur,new,tmp}, OUTDIR/../users (dovecot passwd-file), OUTDIR/../expected.json

Mix per mailbox (deterministic, seeded):
  ~70% new tickets, ~20% replies (In-Reply-To an earlier mail of the same sender -> same conversation),
  ~4% exact duplicates (same Message-ID twice -> imported once), rest odd-but-valid encodings.
"""
import base64, email.header, email.utils, json, os, random, sys, time

N, M, OUT = int(sys.argv[1]), int(sys.argv[2]), os.path.abspath(sys.argv[3])
SEED, V = int(os.environ.get("SEED", 42)), int(os.environ.get("VARIETY", 99))  # V gates scenarios: 1 plain+replies, 2 +duplicates, 3 +odd encodings; later rounds add more
rnd = random.Random(SEED)
WORDS = "invoice order delivery refund login password account billing shipping error crash update contact support".split()
SUBJECTS_NONASCII = ["Rechnung für Bestellung", "Réclamation commande", "Wiederholte Störung — bitte prüfen", "注文について"]
os.makedirs(OUT, exist_ok=True)
users, senders = [], set()
exp = {"conversations": 0, "threads": 0, "attachments": 0}

def body_text(): return "Hello,\n" + " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(8, 400))) + "\n\nBest\n"
def att_size():
    r = rnd.random()
    return rnd.randint(2_000, 20_000) if r < .80 else rnd.randint(80_000, 150_000) if r < .95 else rnd.randint(500_000, 1_000_000)
def b64(raw): return base64.encodebytes(raw).decode()

def build(mid, frm, to, subject, ts, in_reply_to=None, kind="plain", with_att=False):
    h = [f"Message-ID: {mid}", f"Date: {email.utils.formatdate(ts)}", f"From: {frm}", f"To: {to}", f"Subject: {subject}", "MIME-Version: 1.0"]
    if in_reply_to: h += [f"In-Reply-To: {in_reply_to}", f"References: {in_reply_to}"]
    txt = body_text()
    html = "<html><body><p>" + txt.replace("\n", "<br>") + "</p></body></html>"
    if kind == "latin1":
        parts = [("text/plain; charset=iso-8859-1", "quoted-printable", "Gr\xfc\xdfe,\n".encode("latin-1") .decode("latin-1").replace("\xfc", "=FC").replace("\xdf", "=DF") + txt)]
    elif kind == "html":
        parts = [("text/html; charset=utf-8", "7bit", html)]
    elif kind == "alt":
        parts = None
    else:
        parts = [("text/plain; charset=utf-8", "7bit", txt)]
    if kind == "alt" and not with_att:
        b = "ALT"
        return "\n".join(h) + f'\nContent-Type: multipart/alternative; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\n\n{txt}\n--{b}\nContent-Type: text/html; charset=utf-8\n\n{html}\n--{b}--\n'
    if not with_att:
        ct, cte, content = parts[0]
        return "\n".join(h) + f"\nContent-Type: {ct}\nContent-Transfer-Encoding: {cte}\n\n{content}"
    b = "MIX"; out = "\n".join(h) + f'\nContent-Type: multipart/mixed; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\n\n{txt}\n'
    out += f'--{b}\nContent-Type: application/octet-stream; name="doc.bin"\nContent-Transfer-Encoding: base64\nContent-Disposition: attachment; filename="doc.bin"\n\n{b64(os.urandom(att_size()))}\n'
    return out + f"--{b}--\n"

for i in range(1, N + 1):
    u = f"mb{i}@test.local"; users.append(u)
    d = f"{OUT}/{u}/Maildir"
    for s in ("cur", "new", "tmp"): os.makedirs(f"{d}/{s}", exist_ok=True)
    tickets = []          # (message_id, sender, subject, ts, raw) of earlier new tickets, for replies
    seq = 0
    def write(msg, ts):
        global seq
        seq += 1
        open(f"{d}/new/{int(ts)}.{i}_{seq}.gen", "w", encoding="utf-8", errors="surrogateescape").write(msg)
    j = 0
    while j < M:
        now = time.time()
        ts = now - rnd.randint(600, 3 * 86400)
        r = rnd.random()
        att = rnd.random() < 0.2
        if r < .20 and tickets:                                   # reply: same conversation
            mid0, cust, subj, pts, _ = rnd.choice(tickets)
            ts = pts + rnd.randint(1, int(now - pts))                # a reply is dated after its ticket; the app imports in date order
            write(build(f"<r{i}-{j}@gen.test>", f"Customer {cust.split('@')[0]} <{cust}>", u, "Re: " + subj, ts, in_reply_to=mid0, with_att=att), ts)
            exp["threads"] += 1; exp["attachments"] += att
        elif r < .24 and tickets and V >= 2:                                 # exact duplicate delivery of an earlier ticket
            _, _, _, pts, raw = rnd.choice(tickets)
            write(raw, pts)                                       # byte-identical redelivery; a different Date would be a new mail (#5591)
        else:                                                     # new ticket, odd encodings sometimes
            cust = f"cust{rnd.randint(1, 300)}@example.org"; senders.add(cust)
            mid = f"<m{i}-{j}@gen.test>"
            kind = rnd.choice(["plain"] * 5 + ["html", "alt", "latin1"]) if V >= 3 else "plain"
            subj = f"{rnd.choice(WORDS)} {i}-{j}"
            hdr_subj = subj
            if V >= 3 and rnd.random() < .1:
                subj = rnd.choice(SUBJECTS_NONASCII) + f" {i}-{j}"
                hdr_subj = email.header.Header(subj, "utf-8").encode()
            raw = build(mid, f"Customer {cust.split('@')[0]} <{cust}>", u, hdr_subj, ts, kind=kind, with_att=att)
            write(raw, ts)
            tickets.append((mid, cust, hdr_subj, ts, raw))
            exp["conversations"] += 1; exp["threads"] += 1; exp["attachments"] += att
        j += 1

exp["customers"] = len(senders) + N   # + one customer per mailbox address: createCustomers() deliberately does not exclude the To address (upstream, exclusion commented out)
exp["mails_in_mailboxes"] = N * M
open(os.path.join(os.path.dirname(OUT), "users"), "w").write("".join(f"{u}:{{PLAIN}}pw::::::\n" for u in users))
json.dump(exp, open(os.path.join(os.path.dirname(OUT), "expected.json"), "w"))
print(exp, file=sys.stderr)
