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
rnd4 = random.Random(SEED + 1000)  # theme "recipients" (V>=4) draws only from this one, so V<4 output stays identical to earlier rounds
WORDS = "invoice order delivery refund login password account billing shipping error crash update contact support".split()
SUBJECTS_NONASCII = ["Rechnung für Bestellung", "Réclamation commande", "Wiederholte Störung — bitte prüfen", "注文について"]
os.makedirs(OUT, exist_ok=True)
users, senders = [], set()
exp = {"conversations": 0, "threads": 0, "attachments": 0}
addrs = set()         # V>=4: every address (From/Reply-To/To/Cc) of every imported mail, sanitized; createCustomers() makes one customer per address
exp["reply_to_conversations"] = 0
pending = {}          # V>=4: mailbox index -> raws delivered there as a copy of a mail addressed to several mailboxes
NAMES = ["Müller, Hans", "O'Brien, Pat", 'Doe "Johnny" John', "José Álvarez", "田中 太郎", "ACME GmbH (Support)", "info@acme.ch",
         "Dr. Anna-Lena von Hohenstein-Schulz", "Smith, John (ACME, Inc.)", "", "Zoë Ångström-Öberg", "x" * 90]

def body_text(): return "Hello,\n" + " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(8, 400))) + "\n\nBest\n"
def att_size():
    r = rnd.random()
    return rnd.randint(2_000, 20_000) if r < .80 else rnd.randint(80_000, 150_000) if r < .95 else rnd.randint(500_000, 1_000_000)
def person(addr, quirk=False):
    return email.utils.formataddr((rnd4.choice(NAMES), addr)) if quirk else addr
def note(*headers):
    for _, a in email.utils.getaddresses(headers):
        addrs.add(a.lower())
def b64(raw): return base64.encodebytes(raw).decode()

def build(mid, frm, to, subject, ts, in_reply_to=None, kind="plain", with_att=False, extra=()):
    h = [f"Message-ID: {mid}", f"Date: {email.utils.formatdate(ts)}", f"From: {frm}", f"To: {to}", f"Subject: {subject}", "MIME-Version: 1.0"]
    h += list(extra)
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
    def pool_addr():
        return f"cust{rnd4.randint(1, 300)}@example.org" if rnd4.random() < .7 else f"colleague{rnd4.randint(1, 80)}@partner.example"
    def pool_list(lo, hi):
        return [person(pool_addr(), rnd4.random() < .2) for _ in range(rnd4.randint(lo, hi))]
    while j < M:
        if V >= 4 and pending.get(i) and (len(pending[i]) >= M - j or rnd4.random() < .1):   # copy of a mail that also went to this mailbox
            raw, pts = pending[i].pop(0)
            write(raw, pts); j += 1
            continue
        now = time.time()
        ts = now - rnd.randint(600, 3 * 86400)
        r = rnd.random()
        att = rnd.random() < 0.2
        if r < .20 and tickets:                                   # reply: same conversation
            mid0, cust, subj, pts, _, from_hdr = rnd.choice(tickets)
            ts = pts + rnd.randint(1, int(now - pts))                # a reply is dated after its ticket; the app imports in date order
            extra = []
            if V >= 4:
                if rnd4.random() < .15: extra.append("Cc: " + ", ".join(pool_list(1, 2)))
                note(from_hdr, u, *[x[4:] for x in extra])
            write(build(f"<r{i}-{j}@gen.test>", from_hdr, u, "Re: " + subj, ts, in_reply_to=mid0, with_att=att, extra=extra), ts)
            exp["threads"] += 1; exp["attachments"] += att
        elif r < .24 and tickets and V >= 2:                                 # exact duplicate delivery of an earlier ticket
            _, _, _, pts, raw, _ = rnd.choice(tickets)
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
            from_hdr, to_hdr, extra, copies = f"Customer {cust.split('@')[0]} <{cust}>", u, [], 1
            if V >= 4:
                # several recipients: other customers in To/Cc, own alias, Reply-To, display-name quirks, case variants,
                # a mail addressed to two mailboxes (delivered to both), Bcc-only delivery (mailbox not in any header)
                if rnd4.random() < .15: from_hdr = person(cust, True)
                if rnd4.random() < .05: from_hdr = from_hdr.replace(cust, cust.title())
                multi = i < N and rnd4.random() < .03
                if multi:
                    jx = rnd4.randint(i + 1, N)
                    multi = len(pending.get(jx, [])) < max(1, M // 10)
                to = [u]
                cc = []
                if multi: (to if rnd4.random() < .5 else cc).append(f"mb{jx}@test.local")
                elif rnd4.random() < .03: to = pool_list(1, 2)                                  # Bcc: only customers visible in the headers
                elif rnd4.random() < .15: to += pool_list(1, 2)
                if rnd4.random() < .25: cc += pool_list(1, 3)
                if rnd4.random() < .08: cc.append(f"alias{i}@test.local")
                if rnd4.random() < .05: to = [x.upper() if "@example.org" in x and "<" not in x else x for x in to]
                to_hdr = ", ".join(to)
                if cc: extra.append("Cc: " + ", ".join(cc))
                if not multi and rnd4.random() < .08:
                    rt = person(f"rt{rnd4.randint(1, 60)}@replyto.example", rnd4.random() < .3)
                    extra.append("Reply-To: " + rt); exp["reply_to_conversations"] += 1
                    note(rt)
                note(from_hdr, to_hdr, *[x[4:] for x in extra if x.startswith("Cc:")])
                if multi: copies = 2
            raw = build(mid, from_hdr, to_hdr, hdr_subj, ts, kind=kind, with_att=att, extra=extra)
            write(raw, ts)
            if copies == 2: pending.setdefault(jx, []).append((raw, ts))
            else: tickets.append((mid, cust, hdr_subj, ts, raw, from_hdr))
            exp["conversations"] += copies; exp["threads"] += copies; exp["attachments"] += att * copies
        j += 1

exp["customers"] = len(addrs) if V >= 4 else len(senders) + N   # + one customer per mailbox address: createCustomers() deliberately does not exclude the To address (upstream, exclusion commented out)
exp["mails_in_mailboxes"] = N * M
open(os.path.join(os.path.dirname(OUT), "users"), "w").write("".join(f"{u}:{{PLAIN}}pw::::::\n" for u in users))
json.dump(exp, open(os.path.join(os.path.dirname(OUT), "expected.json"), "w"))
print(exp, file=sys.stderr)
