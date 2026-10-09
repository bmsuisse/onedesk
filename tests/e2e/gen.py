#!/usr/bin/env python3
"""Generate realistic Maildirs for the mock IMAP server plus the counts a correct fetch must produce.

usage: gen.py MAILBOXES MAILS_PER_MAILBOX OUTDIR
writes OUTDIR/<user>/Maildir/{cur,new,tmp}, OUTDIR/../users (dovecot passwd-file), OUTDIR/../expected.json

Mix per mailbox (deterministic, seeded):
  ~70% new tickets, ~20% replies (In-Reply-To an earlier mail of the same sender -> same conversation),
  ~4% exact duplicates (same Message-ID twice -> imported once), rest odd-but-valid encodings.
"""
import base64, email.header, email.utils, json, os, random, sys, time, urllib.parse

N, M, OUT = int(sys.argv[1]), int(sys.argv[2]), os.path.abspath(sys.argv[3])
SEED, V = int(os.environ.get("SEED", 42)), int(os.environ.get("VARIETY", 99))  # V gates scenarios: 1 plain+replies, 2 +duplicates, 3 +odd encodings; later rounds add more
rnd = random.Random(SEED)
rnd4 = random.Random(SEED + 1000)  # theme "recipients" (V>=4) draws only from this one, so V<4 output stays identical to earlier rounds
rnd5 = random.Random(SEED + 2000)  # theme "attachments" (V>=5) draws only from this one
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
def rbytes(n): return rnd5.getrandbits(8 * n).to_bytes(n, 'big') if n else b''   # seeded, so a failing seed reproduces byte for byte
def b64(raw): return base64.encodebytes(raw).decode()

# V>=5 theme: inline images (cid:) in HTML mails, many small attachments, duplicate names, RFC2231/RFC2047 unicode file names,
# zero-byte (Attachment::create() refuses empty content -> no row) and very large (5MB) attachments.
ATT_SIZES = []       # decoded sizes of those attachments (check.php compares the multiset with the attachments table: catches truncated content)
ATT_N = 0            # attachment rows a correct import creates for the mail build() just produced
att_sizes = []       # V>=5: decoded size of every attachment a correct import stores
exp_extra = {"inline_images": 0, "zero_byte_parts": 0, "big_attachments": 0}
cid_seq = 0
PLAIN_NAMES = [("report.pdf", "application/pdf"), ("scan.jpg", "image/jpeg"), ("data.csv", "text/csv"), ("notes.txt", "text/plain"), ("invoice.pdf", "application/pdf"), ("photo.png", "image/png")]
UNI_NAMES = ["Rechnung_für_März €.pdf", "Réclamation — commande n°5.pdf", "注文書.pdf", "Zoë Ångström & Öberg.txt", "файл отчёта.pdf"]
def att_part(name_hdr, ctype, content, disp="attachment", cid=None):
    h = f"Content-Type: {ctype}; {name_hdr[0]}\nContent-Transfer-Encoding: base64\nContent-Disposition: {disp}; {name_hdr[1]}\n"
    if cid: h += f"Content-ID: <{cid}>\n"
    return h + "\n" + b64(content)
def name_hdrs(kind, name):
    q = urllib.parse.quote(name)
    if kind == "2231": return (f"name*=UTF-8''{q}", f"filename*=UTF-8''{q}")
    if kind == "2231cont":                      # parameter continuation: filename*0*=...; filename*1*=...
        h = len(q) // 2
        while 0 < h < len(q) and "%" in q[h - 2:h]: h += 1      # never split inside a %XX escape
        return (f"name*0*=UTF-8''{q[:h]};\n name*1*={q[h:]}", f"filename*0*=UTF-8''{q[:h]};\n filename*1*={q[h:]}")
    if kind == "2047":
        w = email.header.Header(name, "utf-8").encode()
        return (f'name="{w}"', f'filename="{w}"')
    return (f'name="{name}"', f'filename="{name}"')
def build5(h, txt, inline):
    global ATT_N, cid_seq
    n = 0
    # Real mailers use long random boundaries. V>=6: 4% of the mails use the short but RFC-valid "MIX"/"REL"; webklex' detectParts() splits on the bare
    # boundary text anywhere in the body, so a "MIX" inside the base64 of an attachment cuts it off.
    short = V >= 6 and rnd5.random() < .04
    mixed_b, rel_b = ("MIX", "REL") if short else (f"----=_Part_{rnd5.randint(10**5, 10**6)}_{rnd5.randint(10**8, 10**9)}.{rnd5.randint(10**11, 10**12)}", f"----=_NextPart_{rnd5.randint(10**8, 10**9)}")
    out = "\n".join(h) + f'\nContent-Type: multipart/mixed; boundary="{mixed_b}"\n\n--{mixed_b}\n'
    if inline:
        imgs = []
        for _ in range(rnd5.choice([1, 1, 1, 2, 3, 4])):
            cid_seq += 1
            imgs.append(f"img{cid_seq}@gen.test")
        html = "<html><body><p>" + txt.replace("\n", "<br>") + "</p>" + "".join(f'<img src="cid:{c}" alt="x">' for c in imgs) + "</body></html>"
        out += f'Content-Type: multipart/related; boundary="{rel_b}"\n\n--{rel_b}\nContent-Type: text/html; charset=utf-8\n\n{html}\n'
        for c in imgs:
            png = b"\x89PNG\r\n\x1a\n" + rbytes(rnd5.randint(200, 4000))
            out += f"--{rel_b}\n" + att_part((f'name="{c}.png"', f'filename="{c}.png"'), "image/png", png, "inline", c) + "\n"
            n += 1; exp_extra["inline_images"] += 1; ATT_SIZES.append(len(png))
        out += f"--{rel_b}--\n"
    else:
        out += f"Content-Type: text/plain; charset=utf-8\n\n{txt}\n"
    r = rnd5.random()
    cnt = 0 if inline and r < .5 else 1 if r < .65 else rnd5.randint(2, 3) if r < .88 else rnd5.randint(4, 8) if r < .97 else rnd5.randint(15, 30)
    dup = rnd5.choice(PLAIN_NAMES) if cnt > 3 or rnd5.random() < .3 else None   # same name several times in one mail
    for _ in range(cnt):
        k = rnd5.random()
        if dup and rnd5.random() < .7: name, ct = dup
        else: name, ct = rnd5.choice(PLAIN_NAMES)
        kind = "plain"
        if k < .25: name, kind = rnd5.choice(UNI_NAMES), rnd5.choice(["2231", "2231cont", "2047"]); ct = "application/octet-stream"
        elif k < .30: name = "my file #1 (copy).pdf"; ct = "application/pdf"      # space and # become "_"
        z = rnd5.random()
        if z < .04: content = b""; exp_extra["zero_byte_parts"] += 1               # Attachment::create(): empty content -> not stored
        elif z < .045: content = rbytes(5 * 1024 * 1024); exp_extra["big_attachments"] += 1; n += 1
        else: content = rbytes(rnd5.randint(1, 3000) if cnt > 3 else rnd5.randint(2_000, 40_000)); n += 1
        if content: ATT_SIZES.append(len(content))
        out += f"--{mixed_b}\n" + att_part(name_hdrs(kind, name), ct, content) + "\n"
    ATT_N = n
    return out + f"--{mixed_b}--\n"

def build(mid, frm, to, subject, ts, in_reply_to=None, kind="plain", with_att=False, extra=(), inline=False):
    global ATT_N, ATT_SIZES
    ATT_N, ATT_SIZES = int(with_att), []
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
    if V >= 5: return build5(h, txt, inline)
    b = "MIX"; out = "\n".join(h) + f'\nContent-Type: multipart/mixed; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\n\n{txt}\n'
    out += f'--{b}\nContent-Type: application/octet-stream; name="doc.bin"\nContent-Transfer-Encoding: base64\nContent-Disposition: attachment; filename="doc.bin"\n\n{b64(rbytes(att_size()))}\n'
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
        inl = V >= 5 and (rnd5.random() < .3 if att else rnd5.random() < .08)   # att mails: 30% also carry cid images; 8% of the rest are inline-image-only
        att = att or inl
        if r < .20 and tickets:                                   # reply: same conversation
            mid0, cust, subj, pts, _, from_hdr = rnd.choice(tickets)
            ts = pts + rnd.randint(1, int(now - pts))                # a reply is dated after its ticket; the app imports in date order
            extra = []
            if V >= 4:
                if rnd4.random() < .15: extra.append("Cc: " + ", ".join(pool_list(1, 2)))
                note(from_hdr, u, *[x[4:] for x in extra])
            write(build(f"<r{i}-{j}@gen.test>", from_hdr, u, "Re: " + subj, ts, in_reply_to=mid0, with_att=att, extra=extra, inline=inl), ts)
            exp["threads"] += 1; exp["attachments"] += ATT_N; att_sizes.extend(ATT_SIZES)
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
            raw = build(mid, from_hdr, to_hdr, hdr_subj, ts, kind=kind, with_att=att, extra=extra, inline=inl)
            write(raw, ts)
            if copies == 2: pending.setdefault(jx, []).append((raw, ts))
            else: tickets.append((mid, cust, hdr_subj, ts, raw, from_hdr))
            exp["conversations"] += copies; exp["threads"] += copies; exp["attachments"] += ATT_N * copies; att_sizes.extend(ATT_SIZES * copies)
        j += 1

exp["customers"] = len(addrs) if V >= 4 else len(senders) + N   # + one customer per mailbox address: createCustomers() deliberately does not exclude the To address (upstream, exclusion commented out)
exp["mails_in_mailboxes"] = N * M
if V >= 5: exp.update(exp_extra, attachment_sizes=sorted(att_sizes))
open(os.path.join(os.path.dirname(OUT), "users"), "w").write("".join(f"{u}:{{PLAIN}}pw::::::\n" for u in users))
json.dump(exp, open(os.path.join(os.path.dirname(OUT), "expected.json"), "w"))
print(exp, file=sys.stderr)
