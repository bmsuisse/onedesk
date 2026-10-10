#!/usr/bin/env python3
"""Generate realistic Maildirs for the mock IMAP server plus the counts a correct fetch must produce.

usage: gen.py MAILBOXES MAILS_PER_MAILBOX OUTDIR
writes OUTDIR/<user>/Maildir/{cur,new,tmp}, OUTDIR/../users (dovecot passwd-file), OUTDIR/../expected.json

Mix per mailbox (deterministic, seeded):
  ~70% new tickets, ~20% replies (In-Reply-To an earlier mail of the same sender -> same conversation),
  ~4% exact duplicates (same Message-ID twice -> imported once), rest odd-but-valid encodings.
"""
import base64, email.header, email.utils, html as htmllib, json, os, quopri, random, sys, time, urllib.parse

N, M, OUT = int(sys.argv[1]), int(sys.argv[2]), os.path.abspath(sys.argv[3])
SEED, V = int(os.environ.get("SEED", 42)), int(os.environ.get("VARIETY", 99))  # V gates scenarios: 1 plain+replies, 2 +duplicates, 3 +odd encodings; later rounds add more
rnd = random.Random(SEED)
rnd4 = random.Random(SEED + 1000)  # theme "recipients" (V>=4) draws only from this one, so V<4 output stays identical to earlier rounds
rnd5 = random.Random(SEED + 2000)  # theme "attachments" (V>=5) draws only from this one
rnd6 = random.Random(SEED + 3000)  # theme "long threads / huge bodies / quotes" (V>=6) draws only from this one
rnd7 = random.Random(SEED + 4000)  # theme "malformed MIME" (V>=7) draws only from this one
rnd8 = random.Random(SEED + 5000)  # theme "one mail to several mailboxes / same sender in all mailboxes" (V>=8) draws only from this one
rnd9 = random.Random(SEED + 6000)  # theme "machine mail" (V>=9) draws only from this one
rnd10 = random.Random(SEED + 7000)  # theme "forwards / @fwd, mails from a mailbox address, helpdesk agents writing by email" (V>=10) draws only from this one
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

# V>=6 theme (huge_bodies = table-style mails whose body is stored whole; data: URI mails are counted in huge_data_uri_mails): very long threads (30+ chained replies in ONE conversation, References grows with every reply), huge bodies (1-3MB html:
# big tables or pasted data: URI images), deeply nested quoted replies in the formats real clients produce (Gmail, Apple Mail, Outlook
# web, Outlook desktop, plain text "> " quoting), signatures with legal disclaimers.
# Counts: a long thread is 1 conversation + 1 + K threads (every reply carries In-Reply-To of the previous mail, so processMessage finds
# prev_thread by Message-ID); it is NOT put into `tickets`, so no other reply joins it and the thread size of that conversation is exactly K+1.
# Quote semantics (separateReply): for a reply, the stored body is the part before the FIRST separator of Mail::$alternative_reply_separators
# (gmail_quote div, blockquote type="cite", divRplyFwdMsg, Outlook MsoNormal header); each message carries a unique token in its own new text,
# so the stored body of such a reply must contain its own token and none of the quoted tokens. Plain "> " quoting has no separator -> not asserted.
exp6 = {"long_threads": 0, "huge_bodies": 0, "huge_data_uri_mails": 0, "data_uri_images": 0}
long_sizes, quote_checks, huge_lens = [], [], []
CLIENTS = ["gmail", "outlook", "outlookcm", "apple", "plain"]
DISCLAIMER = ("This e-mail and any attachments are confidential and may be privileged. If you are not the intended recipient, please notify the sender "
              "immediately and delete this message; any unauthorised copying, disclosure or distribution of the material in this e-mail is strictly forbidden. "
              "Please consider the environment before printing this email. Registered office: Bahnhofstrasse 1, 8001 Zurich. -- Please do not reply above this line unless you mean it.")
def w6(lo, hi): return " ".join(rnd6.choice(WORDS) for _ in range(rnd6.randint(lo, hi)))
def rbytes6(n): return rnd6.getrandbits(8 * n).to_bytes(n, 'big')
def esc6(t): return htmllib.escape(t, quote=False)
def sig6(name):
    lines = [name, rnd6.choice(["Senior Account Manager", "Support Lead", "Head of Operations", "Sales"]), "ACME AG", f"T +41 44 {rnd6.randint(100, 999)} {rnd6.randint(10, 99)} {rnd6.randint(10, 99)}"]
    disc = rnd6.random() < .5
    txt = "\n-- \n" + "\n".join(lines) + ("\n\n" + DISCLAIMER if disc else "") + "\n"
    htm = "<div>-- <br>" + "<br>".join(esc6(l) for l in lines) + "</div>" + (f'<p style="font-size:8pt;color:#888888">{DISCLAIMER}</p>' if disc else "")
    return txt, htm
def qtxt(t): return "\n".join((">" if l.startswith(">") else "> ") + l for l in t.split("\n"))
def encode_html(doc):
    c = rnd6.random()
    if c < .6: return "base64", b64(doc.encode())
    return "quoted-printable", quopri.encodestring(doc.encode()).decode()
def part_mime(h, txt, htm):
    """multipart/alternative: ascii text part + html part (base64 or quoted-printable, so no over-long lines)"""
    b = f"----=_Alt_{rnd6.randint(10**5, 10**6)}_{rnd6.randint(10**8, 10**9)}"
    cte, enc = encode_html(htm)
    return "\n".join(h) + f'\nContent-Type: multipart/alternative; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 7bit\n\n{txt}\n--{b}\nContent-Type: text/html; charset=utf-8\nContent-Transfer-Encoding: {cte}\n\n{enc}\n--{b}--\n'
def long_thread(i, j, u, K, write):
    """ticket + K chained replies in mailbox u; returns the number of mails written"""
    now = time.time()
    ts0 = now - rnd6.randint(2 * 86400, 3 * 86400)
    gaps = [rnd6.randint(1, 1000) for _ in range(K)]
    span, tot, cum, tss = (now - 600) - ts0, sum(gaps), 0, [ts0]
    for g in gaps: cum += g; tss.append(ts0 + span * cum / tot)
    cust = f"cust{rnd6.randint(1, 300)}@example.org"
    coll = f"colleague{rnd6.randint(1, 80)}@partner.example"
    people = {"c": (f"Customer {cust.split('@')[0]}", cust), "x": (f"Colleague {coll.split('@')[0][9:]}", coll)}
    sigs = {k: sig6(v[0]) for k, v in people.items()}
    style = {k: rnd6.choice(CLIENTS) for k in people}
    subj = f"{rnd6.choice(WORDS)} {i}-{j}"
    mids = [f"<m{i}-{j}@gen.test>"] + [f"<lt{i}-{j}-{k}@gen.test>" for k in range(1, K + 1)]
    prev = None                                   # (txt, html, who, ts) of the previous mail
    for k in range(K + 1):
        who = "x" if k and rnd6.random() < .15 else "c"
        name, addr = people[who]
        st = style[who]
        tok = f"QT{i}x{j}x{k}Q"
        paras = [f"{tok} " + w6(8, 40)] + [w6(10, 60) for _ in range(rnd6.randint(0, 2))]
        new_txt, new_html = "\n\n".join(paras) + "\n", "".join(f"<p>{esc6(p)}</p>" for p in paras)
        stxt, shtml = sigs[who]
        ts = int(tss[k])
        txt, htm = new_txt + stxt, new_html + shtml
        if prev:
            ptxt, phtm, pwho, pts = prev
            pname, paddr = people[pwho]
            date = email.utils.formatdate(pts)
            attr = f"On {date}, {pname} &lt;{paddr}&gt; wrote:"
            txt += f"\nOn {date}, {pname} <{paddr}> wrote:\n" + qtxt(ptxt) + "\n"
            if st == "gmail": htm = f'<div dir="ltr">{htm}</div><br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">{attr}<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">{phtm}</blockquote></div>'
            elif st == "apple": htm = f'<div>{htm}</div><div><br><blockquote type="cite"><div>{attr}</div><br class="Apple-interchange-newline"><div>{phtm}</div></blockquote></div>'
            elif st == "outlook": htm = f'<div>{htm}</div><hr style="display:inline-block;width:98%" tabindex="-1"><div id="divRplyFwdMsg" dir="ltr"><font face="Calibri, sans-serif" style="font-size:11pt" color="#000000"><b>From:</b> {pname}<br><b>Sent:</b> {date}<br><b>To:</b> {u}<br><b>Subject:</b> {subj}</font><div>&nbsp;</div></div><div>{phtm}</div>'
            elif st == "outlookcm": htm = f'<div class="WordSection1">{htm}<div><div style="border:none;border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0cm 0cm 0cm"><p class="MsoNormal"><b>From:</b> {pname} [mailto:{paddr}]<br><b>Sent:</b> {date}<br><b>Subject:</b> {subj}</p></div></div>{phtm}</div>'
            else: htm = "<div>" + esc6(txt).replace("\n", "<br>") + "</div>"
            if st != "plain":
                forbid = sorted({f"QT{i}x{j}x0Q", f"QT{i}x{j}x{k - 1}Q"})
                quote_checks.append([mids[k], tok, forbid])
        elif st == "plain": htm = "<div>" + esc6(txt).replace("\n", "<br>") + "</div>"
        h = [f"Message-ID: {mids[k]}", f"Date: {email.utils.formatdate(ts)}", f"From: {email.utils.formataddr((name, addr))}", f"To: {u}",
             f"Subject: {rnd6.choice(['Re: ', 'RE: ', 'AW: ']) if k else ''}{subj}", "MIME-Version: 1.0"]
        if who == "x" or (k and rnd6.random() < .1): h.append("Cc: " + email.utils.formataddr(people["c" if who == "x" else "x"]))
        if k: h += [f"In-Reply-To: {mids[k - 1]}", "References: " + "\n ".join(" ".join(mids[n:n + 3]) for n in range(0, k, 3))]
        note(*[x.split(": ", 1)[1] for x in h if x.startswith(("From:", "To:", "Cc:"))])
        if st == "plain": raw = "\n".join(h) + f"\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 7bit\n\n{txt}"
        else: raw = part_mime(h, txt, f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head><body>{htm}</body></html>')
        write(raw, ts)
        prev = (txt, htm, who, ts)
    exp["conversations"] += 1; exp["threads"] += K + 1
    exp6["long_threads"] += 1; long_sizes.append(K + 1)
    return K + 1
def huge_html(imgs):
    target = rnd6.randint(1_000_000, 3_000_000)
    out, size = [], 0
    if rnd6.random() < .5:                        # report / newsletter style tables
        rows = ["<tr>" + "".join(f'<td style="padding:4px;border:1px solid #cccccc;font-family:Arial">{w6(1, 6)} {rnd6.randint(1, 99999)}</td>' for _ in range(6)) + "</tr>\n" for _ in range(60)]
        out.append('<p>Monthly report</p><table style="border-collapse:collapse">\n'); size = len(out[0])
        while size < target:
            r = rnd6.choice(rows); out.append(r); size += len(r)
        out.append("</table>")
    else:                                         # pasted screenshots as data: URIs
        while size < target:
            png = rbytes6(rnd6.randint(100_000, 400_000)); imgs.append(len(png))
            r = f"<p>{w6(10, 80)}</p>" + '<img src="data:image/png;base64,' + base64.b64encode(png).decode() + '" alt="shot">\n'
            out.append(r); size += len(r)
    return "".join(out)
def build_huge(mid, frm, to, subject, ts, extra=()):
    global ATT_N, ATT_SIZES
    ATT_SIZES = []
    imgs = []
    body = huge_html(imgs)
    # FetchEmails::saveCustomerThread() -> Thread::replaceBase64ImagesWithAttachments(): every data:image/..;base64 <img> becomes an embedded
    # attachment row (the body then only holds its URL, so it shrinks); only the table style keeps its full 1-3MB body.
    ATT_N = len(imgs); ATT_SIZES = list(imgs); exp6["data_uri_images"] += len(imgs)
    if imgs: exp6["huge_data_uri_mails"] += 1
    else: huge_lens.append(len(body)); exp6["huge_bodies"] += 1
    h = [f"Message-ID: {mid}", f"Date: {email.utils.formatdate(ts)}", f"From: {frm}", f"To: {to}", f"Subject: {subject}", "MIME-Version: 1.0"] + list(extra)
    return part_mime(h, "Please see the report below.\n", f"<html><body>{body}</body></html>")

# V>=7 theme: malformed MIME. Every malformed mail is a stand-alone new ticket (never a reply target, never duplicated) with a marker
# "MAL-<kind>-<i>-<j>" in its Subject, so check.php can tell which kind went missing. The import must not crash, lose OTHER mails or loop forever.
# Expected outcome per kind, derived from processMessage()/Query::populate()/Structure/Header:
#   imported (1 conversation + 1 thread), nothing else may change:
#     nomid     no Message-ID header: Query::populate() builds fs-<md5(raw body . uid)>@<from domain> as key, so the mail is imported with that id
#     charset   unknown/empty charset name in Content-Type: convertEncoding() falls back (iconv fails -> mb_convert_encoding in try/catch -> original bytes)
#     baddate   unparsable, impossible, empty, absent or far-future Date: Header::parseDate() falls back to now(), processMessage() clamps future dates to now
#     hdr8bit   raw UTF-8 / raw latin-1 bytes in Subject and From display name (no RFC 2047): the address still identifies the customer
#     nulbody   NUL bytes in the body: Message::decodeString() strips them (#5292), so no stored body may contain one
#     badcte    Content-Transfer-Encoding base64 on a non-base64 text / unknown encoding name: body is garbage or empty, but "we have to fetch absolutely all emails"
#     badquote  Content-Type with unterminated quote / junk parameters
#     emptybody headers only, or no blank line at all ("even with empty body")
#     nobound   multipart/* without a boundary parameter: Structure::find_parts() throws "no content found" and the mail is dropped (finding: data loss)
#     sameb     nested multipart reusing the boundary of its parent: must terminate and import (no attachments: only text parts)
#     deepnest  30 levels of multipart/mixed with unrelated boundaries (X<random>), text body innermost: imported, no attachment
#     prefixb   outer boundary "BND", inner multipart/alternative boundary "BND2" (RFC 2046 5.1.1: a delimiter line is "--" + the exact boundary, so
#               "--BND2" does not delimit the outer multipart): text + html body, no attachment
#     truncb64  attachment whose base64 is cut off mid-quantum, closing boundary present: stored with the bytes base64_decode() can recover
#     noend     multipart/mixed without the closing "--boundary--": last part runs to the end of the message, attachment complete
#   dropped (0 conversations):
#     nofrom    no From (and no Reply-To): processMessage() logs "From is empty", sets Seen and returns
MAL_KINDS = {"nomid": 8, "charset": 8, "baddate": 10, "hdr8bit": 10, "nulbody": 6, "badcte": 6, "badquote": 5, "emptybody": 5,
             "nobound": 5, "sameb": 3, "deepnest": 3, "prefixb": 4, "truncb64": 10, "noend": 8, "nofrom": 5}
mal_counts = {k: 0 for k in MAL_KINDS}      # conversations a correct import creates per kind
def rbytes7(n): return rnd7.getrandbits(8 * n).to_bytes(n, 'big')
def build_malformed(i, j, u, ts):
    """-> (raw mail text, kind, attachment sizes, imported); also registers customers (note) of imported mails"""
    kind = rnd7.choices(list(MAL_KINDS), list(MAL_KINDS.values()))[0]
    cust = f"cust{rnd7.randint(1, 300)}@example.org"
    frm = f"Customer {cust.split('@')[0]} <{cust}>"
    subj = f"{rnd7.choice(WORDS)} MAL-{kind}-{i}-{j}"
    date = email.utils.formatdate(ts)
    h = {"Message-ID": f"<mal{i}-{j}@gen.test>", "Date": date, "From": frm, "To": u, "Subject": subj, "MIME-Version": "1.0"}
    txt = "Hello,\n" + " ".join(rnd7.choice(WORDS) for _ in range(rnd7.randint(8, 80))) + "\n\nBest\n"
    sizes, ct = [], "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 7bit"
    body = txt
    def hdrs(): return "\n".join(f"{k}: {v}" for k, v in h.items() if v is not None)
    def att(b):
        return att_part(name_hdrs("plain", "report.pdf"), "application/pdf", b)
    if kind == "nomid": h["Message-ID"] = None
    elif kind == "charset":
        ct = f"Content-Type: text/plain; charset={rnd7.choice(['x-unknown-1', 'utf-9', 'windows-1299', '\"\"', 'bogus_charset', 'utf8mb4'])}\nContent-Transfer-Encoding: 8bit"
        body = "Grüße, Straße éè 注文\n" + txt
    elif kind == "baddate":
        h["Date"] = rnd7.choice(["Not a date at all", "Thu, 32 Feb 2024 25:61:00 +0000", "", None, "Tue, 99 Foo 0000 00:00:00 XYZ", "Mon, 01 Jan 2099 00:00:00 +0000", "2024-13-45T99:99:99Z", "0"])
    elif kind == "hdr8bit":
        if rnd7.random() < .5: h["Subject"] = "Rechnung für Bestellung " + subj; h["From"] = f"Müller Hans <{cust}>"
        else: h["Subject"] = "Gr\udcfc\udcdfe " + subj; h["From"] = f"M\udcfcller <{cust}>"      # raw latin-1 bytes (not valid UTF-8)
        ct = "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 8bit"
    elif kind == "nulbody":
        body = "\n".join(l + ("\x00" * rnd7.randint(0, 3)) for l in txt.split("\n")) + "\x00\x00end\n"
    elif kind == "badcte":
        ct = f"Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: {rnd7.choice(['base64', 'x-uuencode', 'quoted-printable', 'bogus'])}"
        body = txt + "!!!not base64 =3D =ZZ\n"
    elif kind == "badquote": ct = rnd7.choice(['Content-Type: text/plain; charset="utf-8', 'Content-Type: text/plain; ; ;charset=;', 'Content-Type: ;;', 'Content-Type: text/plain; boundary="'])
    elif kind == "emptybody":
        raw = hdrs() + "\nContent-Type: text/plain; charset=utf-8\n\n" if rnd7.random() < .6 else hdrs() + "\n"
        note(frm, u); mal_counts[kind] += 1
        return raw, kind, sizes
    elif kind == "nobound":
        ct = "Content-Type: multipart/mixed"
    elif kind == "sameb":
        b = "SAME"
        raw = hdrs() + f'\nContent-Type: multipart/mixed; boundary="{b}"\n\n--{b}\nContent-Type: multipart/alternative; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\n\n{txt}\n--{b}--\n--{b}--\n'
        note(frm, u); mal_counts[kind] += 1
        return raw, kind, sizes
    elif kind == "deepnest":
        bs = [f"X{rnd7.randint(10**8, 10**9)}n{n}" for n in range(30)]   # random, so no boundary is a prefix of another
        raw = hdrs() + "\n" + "".join(f'Content-Type: multipart/mixed; boundary="{b}"\n\n--{b}\n' for b in bs) + f"Content-Type: text/plain; charset=utf-8\n\n{txt}\n" + "".join(f"--{b}--\n" for b in reversed(bs))
        note(frm, u); mal_counts[kind] += 1
        return raw, kind, sizes
    elif kind == "prefixb":
        raw = hdrs() + f'\nContent-Type: multipart/mixed; boundary="BND"\n\n--BND\nContent-Type: multipart/alternative; boundary="BND2"\n\n--BND2\nContent-Type: text/plain; charset=utf-8\n\n{txt}\n--BND2\nContent-Type: text/html; charset=utf-8\n\n<p>{txt}</p>\n--BND2--\n\n--BND--\n'
        note(frm, u); mal_counts[kind] += 1
        return raw, kind, sizes
    elif kind in ("truncb64", "noend"):
        content = rbytes7(rnd7.randint(3000, 30000))
        enc = b64(content)
        n_chars = len(enc.replace("\n", "").rstrip("="))     # '=' padding carries no data; cutting must not leave a stray one at the end
        if kind == "truncb64":
            cut = rnd7.choice([1, 2, 3, 5, 7, 4001]) if len(enc) > 8000 else 1
            keep = n_chars - cut
            while keep % 4 == 0: keep -= 1      # always end inside a quantum (2 or 3 chars of 4, or 1 left over)
            flat = enc.replace("\n", "").rstrip("=")[:keep]
            enc = "\n".join(flat[x:x + 76] for x in range(0, len(flat), 76)) + "\n"
            sizes = [keep * 6 // 8]              # base64_decode(): 4 chars -> 3 bytes, 3 -> 2, 2 -> 1, 1 -> 0
        else: sizes = [len(content)]
        part = f"Content-Type: application/pdf; name=\"report.pdf\"\nContent-Transfer-Encoding: base64\nContent-Disposition: attachment; filename=\"report.pdf\"\n\n{enc}"
        raw = hdrs() + f'\nContent-Type: multipart/mixed; boundary="TB"\n\n--TB\nContent-Type: text/plain; charset=utf-8\n\n{txt}\n--TB\n{part}' + ("--TB--\n" if kind == "truncb64" else "")
        note(frm, u); mal_counts[kind] += 1
        return raw, kind, sizes
    elif kind == "nofrom": h["From"] = None
    raw = hdrs() + f"\n{ct}\n\n{body}"
    if kind != "nofrom":
        note(h["From"], u); mal_counts[kind] += 1
    return raw, kind, sizes

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

# V>=8 theme: one mail delivered to SEVERAL mailboxes (same Message-ID, extra_import path) and one sender writing to ALL mailboxes at the same moment.
# Fan-out ticket (marker "FAN-<i>-<j>" in the subject), delivered to K = 2..5 mailboxes (the first one is the one being generated, the others get a copy
# through pending), in one of three header styles: "all" (every target in To/Cc), "bcc" (headers list only mailbox i, the rest are Bcc) and
# "bccfirst" (headers list one LATER mailbox only, mailbox i is Bcc). processMessage() imports it once per target mailbox, whatever mailbox fetches it
# first: the first fetch imports it under its own Message-ID and, for every OTHER mailbox listed in To/Cc, an extra copy under the artificial id
# generateMessageId(mid, mailbox_id.mid); a Bcc mailbox sees a duplicate it is not a recipient of, sets extra=true and imports its own copy.
# So: K conversations, K threads, attachments x K. Replies to an "all" ticket (customer reply-all, In-Reply-To = ticket):
#   same    delivered to the same K mailboxes: each joins the conversation of ITS mailbox (prev thread of another mailbox -> the artificial-id lookup) -> +K threads
#   subset  delivered to some of them (always incl. mailbox i): +|subset| threads, no new conversation
#   latecc  customer adds one more mailbox X to the copy: X has no earlier thread -> prev_thread reset (#5350) -> new conversation "Re: ..." in X: +1 conversation
# check.php compares per marker and mailbox the number of conversations and threads (fan_groups).
# Broadcast: one notice listing ALL mailboxes in To/Cc (style "all", no reply). Burst senders: the same bulkN@bulk.example writes one distinct mail
# (own Message-ID, dates a few seconds apart) into every mailbox: parallel fetchers create the same customer at the same moment -> one customer, N conversations.
fan_groups, burst_exp, fan_kinds = {}, {}, {}   # fan_kinds: marker -> "style/reply kind", only printed by check.php to name what failed
exp8 = {"fanout_tickets": 0, "fanout_replies": 0, "broadcasts": 0, "burst_mails": 0}
def pool8(): return f"cust{rnd8.randint(1, 300)}@example.org" if rnd8.random() < .7 else f"colleague{rnd8.randint(1, 80)}@partner.example"
def fan_rcpt(ids, with_customers=True):
    """-> (To, extra headers) listing the mailboxes ids; sometimes all in To, sometimes first in To and the rest in Cc, sometimes a customer copy"""
    addrs_ = [f"mb{x}@test.local" for x in ids]
    if with_customers and rnd8.random() < .3: addrs_.insert(rnd8.randint(0, len(addrs_)), pool8())
    if rnd8.random() < .5 or len(addrs_) == 1: return ", ".join(addrs_), []
    return addrs_[0], ["Cc: " + ", ".join(addrs_[1:])]
def fanout(i, j, room, write, broadcast=False):
    """ticket (+ maybe a reply) written into mailbox i and queued for the other targets; -> slots used in mailbox i, 0 if it does not fit"""
    global ATT_N
    cap = max(1, M // 10)
    if broadcast:
        S, style, rk = list(range(i, N + 1)), "all", "none"
        if any(len(pending.get(x, [])) + 1 > cap for x in S[1:]): return 0
    else:
        later = [x for x in range(i + 1, N + 1) if len(pending.get(x, [])) + 2 <= cap]
        if not later: return 0
        S = [i] + sorted(rnd8.sample(later, min(rnd8.choice([1, 2, 2, 3, 4]), len(later))))
        style = rnd8.choice(["all"] * 3 + ["bcc", "bccfirst"])
        rk = rnd8.choice(["none"] * 4 + ["same"] * 3 + ["subset", "latecc"]) if style == "all" else "none"
        if style == "bccfirst" and len(S) < 2: style = "bcc"
    D = S
    if rk == "subset": D = [i] + [x for x in S[1:] if rnd8.random() < .5]
    if rk == "latecc":
        X = [x for x in range(i + 1, N + 1) if x not in S and len(pending.get(x, [])) + 1 <= cap]
        if X: D = S + [rnd8.choice(X)]
        else: rk = "same"
    if room < (2 if rk != "none" else 1): return 0
    now = time.time()
    ts = now - rnd8.randint(1200, 3 * 86400)
    cust = f"cust{rnd8.randint(1, 300)}@example.org"
    frm = f"Customer {cust.split('@')[0]} <{cust}>"
    marker = f"FAN-{i}-{j}"
    subj = f"{rnd8.choice(WORDS)} {marker}"
    listed = S if style == "all" else [i] if style == "bcc" else [rnd8.choice(S[1:])]
    to, extra = fan_rcpt(listed)
    mid = f"<fan{i}-{j}@gen.test>"
    att = rnd8.random() < .15
    raw = build(mid, frm, to, subj, ts, with_att=att, extra=extra)
    n_att, sz = ATT_N, list(ATT_SIZES)
    note(frm, to, *[x[4:] for x in extra])
    write(raw, ts)
    for x in S[1:]: pending.setdefault(x, []).append((raw, ts))
    fan_kinds[marker] = ("broadcast" if broadcast else style) + "/" + rk
    g = fan_groups[marker] = {f"mb{x}@test.local": [1, 1] for x in S}
    exp["conversations"] += len(S); exp["threads"] += len(S); exp["attachments"] += n_att * len(S); att_sizes.extend(sz * len(S))
    exp8["broadcasts" if broadcast else "fanout_tickets"] += 1
    used = 1
    if rk != "none":
        ts2 = ts + rnd8.randint(1, max(1, int(now - ts)))
        to2, extra2 = fan_rcpt(D)
        att2 = rnd8.random() < .1
        raw2 = build(f"<fanr{i}-{j}@gen.test>", frm, to2, "Re: " + subj, ts2, in_reply_to=mid, with_att=att2, extra=extra2)
        note(frm, to2, *[x[4:] for x in extra2])
        write(raw2, ts2); used = 2
        for x in D[1:]: pending.setdefault(x, []).append((raw2, ts2))
        for x in D:
            e = g.setdefault(f"mb{x}@test.local", [0, 0])
            if x not in S: e[0] += 1; exp["conversations"] += 1
            e[1] += 1
        exp["threads"] += len(D); exp["attachments"] += ATT_N * len(D); att_sizes.extend(list(ATT_SIZES) * len(D))
        exp8["fanout_replies"] += 1
    return used
# V>=9 theme: machine mail. Every machine mail carries "X-E2E-Kind: [<kind>]" (stored in threads.headers), so check.php can count conversations and threads per kind.
# Semantics, from processMessage()/saveCustomerThread():
#   * Auto-responders are NOT filtered on import: isAutoResponder() is only consulted for replies to a notification of an agent (no such mail here). An out-of-office
#     mail from the customer with In-Reply-To of the ticket is an ordinary customer reply: +1 thread in that conversation, no new conversation.
#     autoreply  customer's out-of-office reply to an earlier ticket (Auto-Submitted / X-Autoreply / Precedence), text or text+html: +1 thread
#     oooloop    3-6 auto-replies, each In-Reply-To the previous one (ping-pong loop): +K threads in the ticket's conversation; one of them redelivered byte for byte (no extra thread)
#     oooorphan  out-of-office with no In-Reply-To or an unknown one (and sometimes no Message-ID at all): new conversation
#     ical       "Accepted: ..." meeting reply, multipart/alternative with a text/calendar part: calendar.ics is an attachment (non-text/plain|html part); 60% reply to a ticket
#   * Bounces never thread: with $is_bounce the customer-reply lookup is skipped, so prev_thread stays null even if In-Reply-To names a known ticket -> new conversation
#     and the thread gets send_status_data.is_bounce. Detection: multipart/report; report-type=delivery-status in Content-Type (MailHelper::detectBounceByHeaders),
#     a message/delivery-status part, From mailer-daemon@, or "Return-Path: <>" as the FIRST header line (the regex is anchored to the start of the header block).
#     ndr        multipart/report: text + message/delivery-status + (message/rfc822 | text/rfc822-headers | nothing): every non-text/plain|html part is an attachment
#     ndrplain   plain text from MAILER-DAEMON@ (qmail style), maybe without Message-ID
#     nullpath   plain text auto-generated mail with "Return-Path: <>" first and In-Reply-To of an earlier ticket (when there is one)
#   * list: mailing-list posts (List-Id, Precedence: list, Reply-To = list or member, "X via list" From munging): a post + 0-3 replies chained by In-Reply-To = ONE conversation;
#     delivered to the list's subscriber mailboxes (1-3, To names only the list address, so the extra mailboxes see it as Bcc and import their own copy through the artificial
#     Message-ID): per mailbox 1 conversation, 1+K threads (marker LST-<i>-<j> in the subject, check.php list_groups). Reply-To wins as sender, so customers = list / member address.
#   * bulk: spam-like bulk (Precedence: bulk, List-Unsubscribe, X-Mailer variety, 5-40 recipients in To, html only with tracking pixel, sometimes huge, Reply-To elsewhere): a new
#     conversation, one customer per address (every To address becomes a customer).
#   * spoofself  From = the mailbox's own address;  mbloop  auto-reply chain between mailboxes (From another mailbox of this install): 1 conversation, K threads
#   * longmid    Message-ID of 200-850 chars (column is varchar(998), unique index on the first 191); 50% get a reply carrying it in In-Reply-To
# Also 35% of the normal new tickets get typical mailer headers (X-Mailer, folded Received/DKIM-Signature, Authentication-Results, X-Spam-*, Thread-Index, Importance...).
MKINDS = {"autoreply": 20, "oooloop": 5, "oooorphan": 7, "ical": 6, "ndr": 14, "ndrplain": 8, "nullpath": 4, "list": 16, "bulk": 12, "spoofself": 3, "mbloop": 3, "longmid": 4}
mach = {}            # kind -> [conversations, threads] a correct import creates
list_groups = {}     # marker -> {mailbox: [conversations, threads]}
MAILERS = ["Postfix", "Exim 4.96", "Sendmail 8.15.2", "Microsoft Outlook 16.0", "Apple Mail (2.3774.600.62)", "Mozilla Thunderbird 115.3", "PHPMailer 6.8.0",
           "Mailchimp Mailer - **CID1a2b3c4d5e**", "SendGrid", "Amazon SES", "Zimbra 9.0.0_GA_4570", "Lotus Notes Release 9.0.1 January 13, 2015", "The Bat! 10.2", "Roundcube Webmail/1.6.2", "Sendinblue"]
OOO_SUBJ = ["Automatic reply: ", "Out of Office: ", "Abwesenheitsnotiz: ", "Autoreply: ", "Automatische Antwort: ", "Réponse automatique : "]
OOO_TXT = ["I am currently out of the office with limited access to email and will return on Monday. For urgent matters please contact my colleagues.\n",
           "Vielen Dank für Ihre Nachricht. Ich bin bis am Montag nicht im Büro und beantworte Ihre E-Mail nach meiner Rückkehr.\n",
           "This is an automatic reply. Your message has been received, I will get back to you as soon as possible.\n"]
def macct(kind, convs, threads, atts=0, sizes=()):
    m = mach.setdefault(kind, [0, 0]); m[0] += convs; m[1] += threads
    exp["conversations"] += convs; exp["threads"] += threads; exp["attachments"] += atts; att_sizes.extend(sizes)
def m_hdr(kind, mid, ts, frm, to, subj, extra=()):
    h = [f"Message-ID: {mid}"] if mid else []
    return h + [f"Date: {email.utils.formatdate(ts)}", f"From: {frm}", f"To: {to}", f"Subject: {subj}", "MIME-Version: 1.0", f"X-E2E-Kind: [{kind}]"] + list(extra)
def m_text(h, body, ctype="text/plain; charset=utf-8", cte="7bit"):
    return "\n".join(h) + f"\nContent-Type: {ctype}\nContent-Transfer-Encoding: {cte}\n\n{body}"
def m_alt(h, txt, htm):
    b = f"----=_Alt_{rnd9.randint(10**5, 10**6)}_{rnd9.randint(10**8, 10**9)}"
    return "\n".join(h) + f'\nContent-Type: multipart/alternative; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 7bit\n\n{txt}\n--{b}\nContent-Type: text/html; charset=utf-8\nContent-Transfer-Encoding: 7bit\n\n{htm}\n--{b}--\n'
def w9(lo, hi): return " ".join(rnd9.choice(WORDS) for _ in range(rnd9.randint(lo, hi)))
def clen(s): return len(s.strip(" \t\n\r\0\x0b").replace("\n", "\r\n"))   # IMAP delivers CRLF, Part::parse() trims the part body, 7bit content is stored as is
def ts_after(pts, now, lo=5, hi=3600):
    return pts + rnd9.randint(lo, max(lo, min(hi, int(now - pts) - 2)))
def mailer_headers():
    """typical headers of real mailers on a normal mail (none of them influences import)"""
    pool = [lambda: "X-Mailer: " + rnd9.choice(MAILERS), lambda: "User-Agent: " + rnd9.choice(MAILERS),
            lambda: "X-Priority: " + rnd9.choice(["1 (Highest)", "3 (Normal)", "5 (Lowest)"]), lambda: "Importance: " + rnd9.choice(["high", "normal", "low"]),
            lambda: "X-MSMail-Priority: High", lambda: "Content-Language: de-CH", lambda: "Accept-Language: de-CH, en-US",
            lambda: "Thread-Index: AQHb" + "".join(rnd9.choice("abcdefABCDEF0123456789+/") for _ in range(30)) + "==",
            lambda: "X-MS-Has-Attach:", lambda: "X-MS-TNEF-Correlator:", lambda: "Auto-Submitted: no",
            lambda: "X-Spam-Status: No, score=" + str(round(rnd9.uniform(-3, 3), 1)) + " required=5.0 tests=HTML_MESSAGE,SPF_PASS autolearn=ham",
            lambda: "X-Spam-Score: " + str(round(rnd9.uniform(-3, 3), 1)), lambda: "X-Spam-Flag: NO",
            lambda: "Authentication-Results: mx.gen.test;\n\tdkim=pass header.d=example.org header.s=sel1;\n\tspf=pass smtp.mailfrom=example.org;\n\tdmarc=pass header.from=example.org",
            lambda: "Received: from mail-wr1-f41.google.com (mail-wr1-f41.google.com [209.85.221.41])\n\tby mx.gen.test (Postfix) with ESMTPS id " + "".join(rnd9.choice("ABCDEF0123456789") for _ in range(10)) + "\n\tfor <mb1@test.local>; Mon, 15 Jan 2024 10:00:00 +0100 (CET)",
            lambda: "DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=example.org; s=sel1;\n\th=to:subject:message-id:date:from:mime-version:from:to:cc:subject:date\n\t:message-id:reply-to; bh=" + "".join(rnd9.choice("abcXYZ0123456789+/") for _ in range(43)) + "=;\n\tb=" + "".join(rnd9.choice("abcXYZ0123456789+/") for _ in range(170))]
    return [f() for f in rnd9.sample(pool, rnd9.randint(1, 6))]
def mach_ticket(tickets):
    return rnd9.choice(tickets) if tickets else None
def machine(i, j, u, room, write, tickets):
    """one machine mail event written into mailbox i (and queued for subscriber mailboxes of a list); -> slots used in mailbox i, 0 if it does not fit"""
    global ATT_N
    kind = rnd9.choices(list(MKINDS), list(MKINDS.values()))[0]
    now = time.time()
    if not tickets and kind in ("autoreply", "oooloop", "nullpath"): kind = "oooorphan"
    if kind == "mbloop" and N < 2: kind = "spoofself"
    pool = lambda: f"cust{rnd9.randint(1, 300)}@example.org"
    if kind == "autoreply":
        mid0, _, subj, pts, _, from_hdr = mach_ticket(tickets)
        ts = ts_after(pts, now)
        extra = [f"In-Reply-To: {mid0}", f"References: {mid0}"] + rnd9.sample(["Auto-Submitted: auto-replied", "X-Autoreply: yes", "Precedence: auto_reply", "X-Auto-Response-Suppress: All"], rnd9.randint(1, 3))
        h = m_hdr(kind, f"<mch-ar{i}-{j}@gen.test>", ts, from_hdr, u, rnd9.choice(OOO_SUBJ) + subj, extra)
        txt = rnd9.choice(OOO_TXT)
        write(m_alt(h, txt, "<html><body><p>" + txt + "</p></body></html>") if rnd9.random() < .4 else m_text(h, txt), ts)
        note(from_hdr, u); macct(kind, 0, 1)
        return 1
    if kind == "oooloop":
        K = rnd9.randint(3, 6)
        if room < K: return 0
        mid0, _, subj, pts, _, from_hdr = mach_ticket(tickets)
        avail = int(now - pts) - 2
        step = rnd9.randint(1, max(1, min(900, avail // (K + 1))))
        prev, refs, prefix, raws = mid0, [mid0], rnd9.choice(OOO_SUBJ), []
        txt = rnd9.choice(OOO_TXT)
        for k in range(K):
            ts = pts + (k + 1) * step
            mid = f"<mch-ool{i}-{j}-{k}@gen.test>"
            h = m_hdr(kind, mid, ts, from_hdr, u, prefix * (k + 1) + subj, [f"In-Reply-To: {prev}", "References: " + " ".join(refs), "Auto-Submitted: auto-replied", "X-Autoreply: yes"])
            raw = m_text(h, txt); raws.append((raw, ts)); write(raw, ts)
            prev = mid; refs.append(mid)
        used = K
        if room > K and rnd9.random() < .4:
            raw, ts = rnd9.choice(raws); write(raw, ts); used += 1       # redelivered byte for byte: same Message-ID, same headers -> imported once
        note(from_hdr, u); macct(kind, 0, K)
        return used
    if kind in ("oooorphan", "ical"):
        mid0 = None
        if kind == "ical" and tickets and rnd9.random() < .6: mid0, _, subj0, pts, _, from_hdr = mach_ticket(tickets)
        if mid0:
            ts = ts_after(pts, now); subj = rnd9.choice(["Accepted: ", "Zugesagt: ", "Tentative: "]) + subj0; conv = 0
            extra = [f"In-Reply-To: {mid0}", f"References: {mid0}"]
        else:
            ts = now - rnd9.randint(600, 3 * 86400); from_hdr = pool(); conv = 1
            subj = (rnd9.choice(["Accepted: ", "Zugesagt: "]) if kind == "ical" else rnd9.choice(OOO_SUBJ)) + f"{rnd9.choice(WORDS)} {i}-{j}"
            extra = [f"In-Reply-To: <sent-{rnd9.randint(1, 10**9)}@out.onedesk.example>"] if rnd9.random() < .5 else []
        if kind == "oooorphan":
            extra += ["Auto-Submitted: auto-replied", "Precedence: auto_reply"]
            h = m_hdr(kind, None if rnd9.random() < .25 else f"<mch-oo{i}-{j}@gen.test>", ts, from_hdr, u, subj, extra)
            write(m_text(h, rnd9.choice(OOO_TXT)), ts); note(from_hdr, u); macct(kind, 1, 1)
            return 1
        ics = ("BEGIN:VCALENDAR\r\nMETHOD:REPLY\r\nPRODID:-//Microsoft Corporation//Outlook 16.0 MIMEDIR//EN\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
               f"ATTENDEE;PARTSTAT=ACCEPTED:mailto:{email.utils.parseaddr(from_hdr)[1]}\r\nDTSTART:20240115T100000Z\r\nDTEND:20240115T110000Z\r\nUID:{rnd9.randint(10**8, 10**9)}-{i}-{j}@gen.test\r\nSUMMARY:{subj}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        b = f"----=_Cal_{rnd9.randint(10**5, 10**6)}"
        h = m_hdr(kind, f"<mch-ical{i}-{j}@gen.test>", ts, from_hdr, u, subj, extra)
        write("\n".join(h) + f'\nContent-Type: multipart/alternative; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 7bit\n\nThe meeting has been accepted.\n'
              f'--{b}\nContent-Type: text/calendar; charset=utf-8; method=REPLY\nContent-Transfer-Encoding: base64\n\n{b64(ics.encode())}--{b}--\n', ts)
        note(from_hdr, u); macct(kind, conv, 1, 1, [len(ics)])
        return 1
    if kind in ("ndr", "ndrplain", "nullpath"):
        dom = f"mx{rnd9.randint(1, 9)}.gen.test"
        victim = f"user{rnd9.randint(1, 999)}@remote{rnd9.randint(1, 20)}.example"
        ts = now - rnd9.randint(600, 3 * 86400)
        extra, pre = [], []
        if tickets and rnd9.random() < (.9 if kind == "nullpath" else .4):
            mid0, _, subj0, pts, _, _ = mach_ticket(tickets); ts = ts_after(pts, now)
            extra += [f"In-Reply-To: {mid0}", f"References: {mid0}"]
        mid = None if rnd9.random() < .1 else f"<mch-{kind}{i}-{j}@{dom}>"
        if kind == "nullpath":
            if not extra: return 0
            frm = f"Postmaster <postmaster@{dom}>"
            h = ["Return-Path: <>"] + m_hdr(kind, mid, ts, frm, u, rnd9.choice(["Delivery Status Notification (Delay)", "Mail delivery failed: returning message to sender", "Auto-generated: your message was not delivered"]), extra + ["Auto-Submitted: auto-generated"])
            write(m_text(h, f"Your message to {victim} could not be delivered yet.\nThe system will keep trying for 4 days.\n"), ts)
            note(frm, u); macct(kind, 1, 1)
            return 1
        if kind == "ndrplain":
            frm = rnd9.choice([f"MAILER-DAEMON@{dom}", f"Mail Delivery System <Mailer-Daemon@{dom}>", f"MAILER-DAEMON@{dom} (Mail Delivery System)"])
            h = m_hdr(kind, mid, ts, frm, u, rnd9.choice(["failure notice", "Undelivered Mail Returned to Sender", "Delivery Status Notification (Failure)"]), extra)
            write(m_text(h, f"Hi. This is the qmail-send program at {dom}.\nI'm afraid I wasn't able to deliver your message to the following addresses.\nThis is a permanent error; I've given up. Sorry it didn't work out.\n\n<{victim}>:\n550 5.1.1 User unknown\n"), ts)
            note(frm, u); macct(kind, 1, 1)
            return 1
        frm = rnd9.choice([f"Mail Delivery Subsystem <MAILER-DAEMON@{dom}>", f"MAILER-DAEMON@{dom} (Mail Delivery System)", f"Microsoft Outlook <postmaster@{dom}>", f"postmaster@{dom}"])
        b = f"{''.join(rnd9.choice('ABCDEF0123456789') for _ in range(10))}.{rnd9.randint(10**9, 2 * 10**9)}/{dom}"
        dsn = f"Reporting-MTA: dns; {dom}\nX-Postfix-Queue-ID: {rnd9.randint(10**8, 10**9):X}\nArrival-Date: {email.utils.formatdate(ts)}\n\nFinal-Recipient: rfc822; {victim}\nAction: failed\nStatus: 5.1.1\nDiagnostic-Code: smtp; 550 5.1.1 <{victim}>: Recipient address rejected: User unknown\n"
        orig = f"Message-ID: <out{i}-{j}@onedesk.example>\nFrom: support@onedesk.example\nTo: {victim}\nSubject: Re: {w9(1, 3)}\nDate: {email.utils.formatdate(ts - 60)}\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n{body_text()}"
        form = rnd9.choice(["full", "full", "headers", "none"])
        raw = ("\n".join((["Return-Path: <>"] if rnd9.random() < .6 else []) + m_hdr(kind, mid, ts, frm, u, rnd9.choice(["Undelivered Mail Returned to Sender", "Delivery Status Notification (Failure)", "Undeliverable: " + w9(1, 3), "Zustellung fehlgeschlagen"]),
                         extra + ["Auto-Submitted: auto-replied", f"X-Failed-Recipients: {victim}"])) +
               f'\nContent-Type: multipart/report; report-type=delivery-status;\n\tboundary="{b}"\n\n--{b}\nContent-Description: Notification\nContent-Type: text/plain; charset=utf-8\n\n'
               f"This is the mail system at host {dom}.\n\nI'm sorry to have to inform you that your message could not be delivered to one or more recipients.\n\n<{victim}>: host remote.example said: 550 5.1.1 User unknown\n\n"
               f"--{b}\nContent-Description: Delivery report\nContent-Type: message/delivery-status\n\n{dsn}\n")
        sizes = [clen(dsn)]
        if form == "full": raw += f"--{b}\nContent-Description: Undelivered Message\nContent-Type: message/rfc822\nContent-Transfer-Encoding: 8bit\n\n{orig}\n"; sizes.append(clen(orig))
        elif form == "headers": hd = orig.split("\n\n")[0] + "\n"; raw += f"--{b}\nContent-Description: Undelivered Message Headers\nContent-Type: text/rfc822-headers\nContent-Transfer-Encoding: 7bit\n\n{hd}\n"; sizes.append(clen(hd))
        write(raw + f"--{b}--\n", ts)
        note(frm, u); macct(kind, 1, 1, len(sizes), sizes)
        return 1
    if kind == "list":
        lst = rnd9.randint(1, 12)
        lst_addr, lst_id = f"dev{lst}@lists.example", f"<dev{lst}.lists.example>"
        K = rnd9.choice([0, 0, 1, 2, 3])
        cap = max(1, M // 10)
        later = [x for x in range(i + 1, N + 1) if len(pending.get(x, [])) + 1 + K <= cap]
        S = [i] + sorted(rnd9.sample(later, min(rnd9.choice([0, 0, 0, 1, 1, 2]), len(later))))
        K = min(K, room - 1)
        if K < 0: return 0
        style = rnd9.choice(["member", "munged", "listreply"])
        ts0 = now - rnd9.randint(1200, 3 * 86400)
        member = lambda: f"colleague{rnd9.randint(1, 80)}@partner.example" if rnd9.random() < .6 else pool()
        marker = f"LST-{i}-{j}"
        subj = f"[dev{lst}] {rnd9.choice(WORDS)} {marker}"
        mids = [f"<mch-ls{i}-{j}-{k}@gen.test>" for k in range(K + 1)]
        gap = rnd9.randint(30, max(31, min(1800, int((now - ts0) / (K + 1)) - 2)))
        nm = ["Hans Müller", "Pat O'Brien", "Anna Schmid", "José Álvarez"]
        for k in range(K + 1):
            ts = ts0 + k * gap
            m, n = member(), rnd9.choice(nm)
            frm = email.utils.formataddr((n, m)) if style != "munged" else email.utils.formataddr((n + f" via dev{lst}", lst_addr))
            ex = [f"List-Id: Dev {lst} <dev{lst}.lists.example>", f"List-Post: <mailto:{lst_addr}>", f"List-Unsubscribe: <mailto:dev{lst}-request@lists.example?subject=unsubscribe>, <https://lists.example/u/{lst}>",
                  f"List-Help: <mailto:dev{lst}-request@lists.example?subject=help>", "Precedence: list", f"Sender: dev{lst}-bounces@lists.example", "Errors-To: dev%d-bounces@lists.example" % lst, "X-Mailman-Version: 2.1.29"]
            if style == "munged": ex.append(f"Reply-To: {m}")
            if style == "listreply": ex.append(f"Reply-To: {lst_addr}")
            if k: ex += [f"In-Reply-To: {mids[k - 1]}", "References: " + " ".join(mids[:k])]
            h = m_hdr(kind, mids[k], ts, frm, lst_addr, ("Re: " if k else "") + subj, ex)
            raw = m_text(h, w9(8, 60) + f"\n\n_______________________________________________\ndev{lst} mailing list\n{lst_addr}\nhttps://lists.example/listinfo/dev{lst}\n")
            write(raw, ts)
            for x in S[1:]: pending.setdefault(x, []).append((raw, ts))
            note(frm, lst_addr, *[x[10:] for x in ex if x.startswith("Reply-To:")])
        list_groups[marker] = {f"mb{x}@test.local": [1, K + 1] for x in S}
        macct(kind, len(S), len(S) * (K + 1))
        return K + 1
    if kind == "bulk":
        ts = now - rnd9.randint(600, 3 * 86400)
        n = rnd9.randint(1, 3000)
        frm = email.utils.formataddr((rnd9.choice(NAMES), f"news{rnd9.randint(1, 500)}@promo{rnd9.randint(1, 40)}.example")) if rnd9.random() < .7 else f"offers{n}@promo{rnd9.randint(1, 40)}.example"
        rcpt = [f"victim{rnd9.randint(1, 3000)}@spam-target.example" for _ in range(rnd9.randint(5, 40))]
        if rnd9.random() < .5: rcpt.insert(rnd9.randint(0, len(rcpt)), u)
        to = ",\n\t".join(rcpt)      # folded: 40 recipients exceed the 998 character line limit
        subj = rnd9.choice(["FINAL NOTICE: YOUR ACCOUNT", "Re: Re: Fwd: invoice " + str(n), "Big SALE -70% " + w9(2, 4), "\U0001f389 Winner " + w9(1, 2) + " \U0001f389", "Quick question " + w9(1, 3), "x" * rnd9.randint(240, 300) + " " + str(n)])
        hs = email.header.Header(subj, "utf-8").encode() if any(ord(c) > 127 for c in subj) else subj
        extra = [f"X-Mailer: {rnd9.choice(MAILERS)}", "Precedence: bulk", f"List-Unsubscribe: <mailto:unsub{n}@promo.example?subject=unsubscribe>, <https://promo.example/u/{n}>", "List-Unsubscribe-Post: List-Unsubscribe=One-Click", f"Feedback-ID: {n}:camp{n}:promo:{n}"]
        if rnd9.random() < .25: extra += ["X-Spam-Flag: YES", "X-Spam-Score: 9.4"]
        if rnd9.random() < .5:
            rt = f"reply{rnd9.randint(1, 500)}@promo-reply.example"; extra.append(f"Reply-To: {rt}"); note(rt)
        row = f'<tr><td style="padding:4px;font-family:Arial;color:#333333">{w9(2, 6)} <a href="https://promo.example/c?id={n}&amp;x=1">click</a></td></tr>\n'
        htm = '<html><body><table width="600">\n' + row * (rnd9.randint(2000, 6000) if rnd9.random() < .1 else rnd9.randint(3, 40)) + '</table><img src="http://track.promo.example/p.gif?u=%d" width="1" height="1" alt=""></body></html>' % n
        h = m_hdr(kind, f"<mch-bulk{i}-{j}@promo.example>", ts, frm, to, hs, extra)
        write(m_text(h, quopri.encodestring(htm.encode()).decode(), "text/html; charset=utf-8", "quoted-printable"), ts)
        note(frm, to); macct(kind, 1, 1)
        return 1
    if kind == "spoofself":
        ts = now - rnd9.randint(600, 3 * 86400)
        frm = f"Support Team <{u}>"
        h = m_hdr(kind, f"<mch-spoof{i}-{j}@gen.test>", ts, frm, u, rnd9.choice(["Your mailbox is full", "Password expires today", "Message from your administrator"]) + f" {i}-{j}", ["X-Mailer: " + rnd9.choice(MAILERS)])
        write(m_text(h, w9(8, 40) + "\n"), ts); note(frm, u); macct(kind, 1, 1)
        return 1
    if kind == "mbloop":
        K = rnd9.randint(3, 5)
        if room < K: return 0
        o = rnd9.choice([x for x in range(1, N + 1) if x != i])
        frm = f"mb{o}@test.local"
        ts0 = now - rnd9.randint(1200, 3 * 86400)
        step = rnd9.randint(1, max(1, min(900, int((now - ts0) / (K + 1)) - 2)))
        subj = f"{rnd9.choice(WORDS)} loop {i}-{j}"
        for k in range(K):
            ts = ts0 + k * step
            ex = ["Auto-Submitted: auto-replied", "X-Autoreply: yes"] + ([f"In-Reply-To: <mch-lp{i}-{j}-{k - 1}@gen.test>", f"References: <mch-lp{i}-{j}-{k - 1}@gen.test>"] if k else [])
            write(m_text(m_hdr(kind, f"<mch-lp{i}-{j}-{k}@gen.test>", ts, frm, u, "Re: " * (k + 1) + subj, ex), rnd9.choice(OOO_TXT)), ts)
        note(frm, u); macct(kind, 1, K)
        return K
    if kind == "longmid":
        ts = now - rnd9.randint(1200, 3 * 86400)
        mid = "<" + "".join(rnd9.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-=+") for _ in range(rnd9.randint(200, 850))) + "@long.gen.test>"
        cust = pool(); frm = f"Customer {cust.split('@')[0]} <{cust}>"
        subj = f"{rnd9.choice(WORDS)} {i}-{j}"
        write(m_text(m_hdr(kind, mid, ts, frm, u, subj), w9(8, 80) + "\n"), ts); note(frm, u)
        used, thr = 1, 1
        if room > 1 and rnd9.random() < .5:
            ts2 = ts_after(ts, now)
            write(m_text(m_hdr(kind, f"<mch-lm{i}-{j}@gen.test>", ts2, frm, u, "Re: " + subj, [f"In-Reply-To: {mid}", f"References: {mid}"]), w9(8, 40) + "\n"), ts2)
            used, thr = 2, 2
        macct(kind, 1, thr)
        return used
    return 0

# V>=10 theme: forwarded mail and the @fwd command, mails whose From is a mailbox address (self-addressed, same Message-ID twice in one mailbox), helpdesk agents writing by email.
# Every mail has a marker "T10-<i>-<j>" in the Subject (conversation-creating events) and "X-E2E-Kind: [t10-<kind>]"; check.php counts conversations/threads per kind and compares, per
# marker, the (mailbox, customer_email, subject) of every conversation. Agents are the users seeded by seed.php (agent1..5@helpdesk.example, agent6 + alternate agent6.alt@...).
# Semantics, from processMessage():
#   * @fwd (FWD_AS_CUSTOMER_COMMAND): applies only if subject starts with 1-3 letters + ":" (Fwd:, FW:, WG:, TR:), the mail is no reply, has exactly one To and no Cc, the body STARTS with
#     "@fwd" (tags stripped, case-insensitive), a "From:" address can be found in the body (first quote-delimited/angle-bracket address wins) and the sender is a user (main or alternate
#     address). Then the sender becomes that original address (new customer if unknown), the subject loses its "Fwd:" prefix, the command is removed. One conversation, one thread.
#     fwdcmd      agent forwards with @fwd (text, Gmail, Outlook web or Apple Mail html; sometimes an older forward below, sometimes agent6's alternate address, To an alias): customer = original sender
#     fwdnouser   a customer writes "@fwd" in a forward: not a user, nothing is substituted (customer = sender, subject untouched)
#     fwdnocmd    agent forwards without @fwd: customer = agent
#     fwdcc       @fwd but a second recipient (To or Cc): customer = agent
#     fwdnoaddr   @fwd with no address in the body: customer = agent
#     fwdatt      agent forwards "as attachment" (message/rfc822 part, body "@fwd ..." without any address): customer = agent, one attachment
#   * Mails from a mailbox address are plain customer mails (the mailbox is just another customer; nothing filters them):
#     selfmail    From = mailbox / its alias / "Name <mailbox>", To = the mailbox: new conversation
#     selfreply   the helpdesk's own copy (From mailbox or alias, To customer, Cc mailbox) with In-Reply-To of an earlier ticket: +1 thread in that conversation
#     selffan     From = mailbox i, To lists mailbox i and 1-2 later mailboxes: every listed mailbox imports its own copy (one conversation each)
#   * Same Message-ID twice in ONE mailbox: byte-identical headers = duplicate (skipped, body is not compared); different headers (extra Received/Delivered-To, other Date) = a new mail
#     (#5591): imported under the artificial Message-ID generateMessageId(mid, mailbox_id.mid), a third copy with other headers would hit that artificial id and be skipped (not generated).
#     dupidhdr    two variants with different headers: 2 conversations      dupidbody  same headers, different body: 1 conversation
#   * Agents: a reply to a notification carries In-Reply-To FS_notify-<thread>-<user>-<hash>@host with hash = md5(thread_id . app.key)[:16]; an invalid hash (or one of other length) logs an error,
#     sets Seen and drops the mail before any customer is created (gen cannot know thread ids: valid replies are the two-phase case cases/agentreply.sh)
#     agbadhash   dropped: no conversation, no thread, no customer
#     agentdirect agent answers the customer's mail from their own client (In-Reply-To = ticket Message-ID, no notification id): an ordinary customer reply from the agent's address, +1 thread
#     agentnew    agent writes a new mail to the mailbox: new conversation, customer = agent
T10 = {"fwdcmd": 22, "fwdnouser": 6, "fwdnocmd": 6, "fwdcc": 5, "fwdnoaddr": 4, "fwdatt": 4, "selfmail": 10, "selfreply": 8, "selffan": 4,
       "dupidhdr": 7, "dupidbody": 4, "agbadhash": 8, "agentdirect": 8, "agentnew": 5}
t10 = {}             # kind -> [conversations, threads] a correct import creates
t10_convs = {}       # marker -> [[mailbox, customer_email, subject], ...] of the conversations it opens
AGENTS = [f"agent{n}@helpdesk.example" for n in range(1, 6)] + ["agent6.alt@helpdesk.example"]
NAMES10 = [n for n in NAMES if "@" not in n]
FWD_PREFIX = ["Fwd: ", "FW: ", "Fw: ", "WG: ", "TR: ", "FWD: "]
def w10(lo, hi): return " ".join(rnd10.choice(WORDS) for _ in range(rnd10.randint(lo, hi)))
def pool10(): return f"cust{rnd10.randint(1, 300)}@example.org" if rnd10.random() < .7 else f"colleague{rnd10.randint(1, 80)}@partner.example"
def t10acct(kind, convs, threads, atts=0, sizes=()):
    m = t10.setdefault(kind, [0, 0]); m[0] += convs; m[1] += threads
    exp["conversations"] += convs; exp["threads"] += threads; exp["attachments"] += atts; att_sizes.extend(sizes)
def t10conv(marker, mailbox, cust, subj): t10_convs.setdefault(marker, []).append([mailbox, cust.lower(), subj])
def agent10():
    a = rnd10.choice(AGENTS)
    if rnd10.random() < .1: a = a.title()      # Agent1@Helpdesk.Example: sanitizeEmail() lower-cases
    return email.utils.formataddr(("Agent " + a[5:6], a)) if rnd10.random() < .5 else a
def t_alt(h, txt, htm):
    b = f"----=_Alt_{rnd10.randint(10**5, 10**6)}_{rnd10.randint(10**8, 10**9)}"
    return "\n".join(h) + f'\nContent-Type: multipart/alternative; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 8bit\n\n{txt}\n--{b}\nContent-Type: text/html; charset=utf-8\nContent-Transfer-Encoding: 8bit\n\n{htm}\n--{b}--\n'
def fwd_body(cmd, style, oname, oaddr, osubj, u, older):
    """forwarded mail body -> (text, html); html is None for the plain text style. oaddr is the first address after the command"""
    date = email.utils.formatdate(time.time() - rnd10.randint(86400, 20 * 86400))
    inner = w10(8, 60)
    nm = f"{oname} " if oname else ""
    txt = f"{cmd}\n\n---------- Forwarded message ---------\nFrom: {nm}<{oaddr}>\nDate: {date}\nSubject: {osubj}\nTo: Support <{u}>\n\n{inner}\n"
    if older: txt += f"\n> Begin forwarded message:\n> From: {older[0]} <{older[1]}>\n> Subject: older\n"
    if style == "text": return txt, None
    e = htmllib.escape(oname or "", quote=False)
    if style == "gmail":
        htm = (f'<div dir="ltr">{cmd}<br><br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">---------- Forwarded message ---------<br>From: <strong class="gmail_sendername" dir="auto">{e}</strong> '
               f'<span dir="auto">&lt;<a href="mailto:{oaddr}">{oaddr}</a>&gt;</span><br>Date: {date}<br>Subject: {osubj}<br>To: &lt;<a href="mailto:{u}">{u}</a>&gt;<br></div><br><br><div>{inner}</div></div></div>')
    elif style == "outlook":
        htm = (f'<div>{cmd}</div><hr style="display:inline-block;width:98%" tabindex="-1"><div id="divRplyFwdMsg" dir="ltr"><font face="Calibri, sans-serif" style="font-size:11pt" color="#000000">'
               f'<b>From:</b> {e} &lt;{oaddr}&gt;<br><b>Sent:</b> {date}<br><b>To:</b> {u}<br><b>Subject:</b> {osubj}</font><div>&nbsp;</div></div><div>{inner}</div>')
    else:
        htm = (f'<div>{cmd}</div><div><br><blockquote type="cite"><div>Begin forwarded message:</div><br><div style="margin:0px"><b>From:</b> {e} &lt;<a href="mailto:{oaddr}">{oaddr}</a>&gt;<br></div>'
               f'<div><b>Subject:</b> {osubj}</div><br><div>{inner}</div></blockquote></div>')
    if older: htm = htm.replace(f"<div>{inner}</div>", f"<div>{inner}</div><div>Begin forwarded message:<br>From: {older[0]} &lt;<a href=\"mailto:{older[1]}\">{older[1]}</a>&gt;</div>", 1)
    return txt, "<html><body>" + htm + "</body></html>"
def theme10(i, j, u, room, write, tickets):
    """one event of the theme written into mailbox i (selffan also queues copies); -> slots used in mailbox i, 0 if it does not fit"""
    kind = rnd10.choices(list(T10), list(T10.values()))[0]
    if not tickets and kind in ("selfreply", "agentdirect"): kind = "agentnew"
    now = time.time()
    ts = now - rnd10.randint(600, 3 * 86400)
    marker = f"T10-{i}-{j}"
    subj0 = f"{rnd10.choice(WORDS)} {marker}"
    xk = f"t10-{kind}"
    addr = lambda hdr: email.utils.parseaddr(hdr)[1]
    if kind.startswith("fwd"):
        agent = agent10()
        orig, oname = pool10(), rnd10.choice(NAMES10)
        older = (rnd10.choice(NAMES10) or "Older Sender", pool10()) if rnd10.random() < .25 else None
        prefix = rnd10.choice(FWD_PREFIX)
        cmd = rnd10.choice(["@fwd", "@fwd", "@FWD"]) if kind != "fwdnocmd" else ""
        to, extra, frm = u, [], agent
        if kind == "fwdnouser": frm = pool10()
        if kind == "fwdcmd" and rnd10.random() < .1: to = f"alias{i}@test.local"
        if kind == "fwdcmd" and rnd10.random() < .12: frm = "agent6.alt@helpdesk.example"
        if kind == "fwdcc":
            if rnd10.random() < .5: to = f"{u}, {pool10()}"
            else: extra = ["Cc: " + pool10()]
        h = m_hdr(xk, f"<t10-{kind}{i}-{j}@helpdesk.example>", ts, frm, to, prefix + subj0, extra)
        if kind == "fwdatt":
            orig_msg = f"Message-ID: <out{i}-{j}@orig.example>\nFrom: {oname} <{orig}>\nTo: <{u}>\nSubject: {subj0}\nDate: {email.utils.formatdate(ts - 600)}\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n{body_text()}"
            b = f"----=_Fwd_{rnd10.randint(10**5, 10**6)}"
            raw = ("\n".join(h) + f'\nContent-Type: multipart/mixed; boundary="{b}"\n\n--{b}\nContent-Type: text/plain; charset=utf-8\n\n{cmd}\n\nPlease see attached.\n--{b}\n'
                   f"Content-Description: Forwarded Message\nContent-Type: message/rfc822\nContent-Transfer-Encoding: 8bit\n\n{orig_msg}\n--{b}--\n")
            write(raw, ts)
            note(frm, to); t10conv(marker, u, addr(frm), prefix + subj0); t10acct(kind, 1, 1, 1, [len(orig_msg.strip(" \t\n\r\0\x0b").replace("\n", "\r\n").encode())])   # bytes: the display name may be non-ASCII
            return 1
        if kind == "fwdnoaddr": txt, htm = f"{cmd}\n\nPlease take care of this, thanks.\n", None
        else: txt, htm = fwd_body(cmd, rnd10.choice(["text", "text", "gmail", "outlook", "apple"]), oname, orig, subj0, u, older)
        raw = t_alt(h, txt, htm) if htm and rnd10.random() < .5 else m_text(h, htm, "text/html; charset=utf-8", "8bit") if htm else m_text(h, txt, "text/plain; charset=utf-8", "8bit")
        write(raw, ts); used = 1
        if kind == "fwdcmd" and room > 1 and rnd10.random() < .12: write(raw, ts); used = 2      # redelivered byte for byte
        subst = kind == "fwdcmd"
        note(frm, to, *([orig] if subst else []), *[x[4:] for x in extra])
        t10conv(marker, u, orig if subst else addr(frm), subj0 if subst else prefix + subj0); t10acct(kind, 1, 1)
        return used
    if kind in ("selfmail", "agentnew", "agbadhash"):
        if kind == "selfmail":
            frm = rnd10.choice([u, u, f"alias{i}@test.local", email.utils.formataddr((f"MB{i} Support", u))])
            to, extra = u, ["Cc: " + pool10()] if rnd10.random() < .3 else []
            h = m_hdr(xk, f"<t10-self{i}-{j}@gen.test>", ts, frm, to, subj0, extra)
            write(m_text(h, w10(8, 80) + "\n"), ts)
            note(frm, to, *[x[4:] for x in extra]); t10conv(marker, u, addr(frm), subj0); t10acct(kind, 1, 1)
            return 1
        if kind == "agentnew":
            frm = agent10()
            write(m_text(m_hdr(xk, f"<t10-new{i}-{j}@helpdesk.example>", ts, frm, u, subj0), w10(8, 60) + "\n"), ts)
            note(frm, u); t10conv(marker, u, addr(frm), subj0); t10acct(kind, 1, 1)
            return 1
        tid, uid = rnd10.randint(1, 200000), rnd10.randint(1, 6)
        hl = rnd10.choices([16, 8, 32], [6, 2, 2])[0]
        nid = f"<FS_notify-{tid}-{uid}-{''.join(rnd10.choice('0123456789abcdef') for _ in range(hl))}@helpdesk.example>"
        h = m_hdr(xk, f"<t10-bad{i}-{j}@helpdesk.example>", ts, agent10(), u, "Re: [#" + str(rnd10.randint(1, 9999)) + "] " + subj0, [f"In-Reply-To: {nid}", f"References: {nid}"])
        write(m_text(h, w10(8, 60) + "\n"), ts); t10acct(kind, 0, 0)       # dropped before createCustomers(): no note()
        return 1
    if kind in ("selfreply", "agentdirect"):
        mid0, _, subj, pts, _, from_hdr = rnd10.choice(tickets)
        ts = pts + rnd10.randint(5, max(5, min(3600, int(now - pts) - 2)))
        cust = addr(from_hdr)
        if kind == "selfreply":
            frm = rnd10.choice([u, f"alias{i}@test.local", email.utils.formataddr((f"MB{i} Support", u))]); to, extra = cust, [f"Cc: {u}"]
        else:
            frm = agent10(); to, extra = rnd10.choice([u, cust]), ([f"Cc: {u}"] if rnd10.random() < .3 else [])
        h = m_hdr(xk, f"<t10-{kind}{i}-{j}@gen.test>", ts, frm, to, "Re: " + subj, extra + [f"In-Reply-To: {mid0}", f"References: {mid0}"])
        write(m_text(h, w10(8, 60) + "\n"), ts)
        note(frm, to, *[x[4:] for x in extra]); t10acct(kind, 0, 1)
        return 1
    if kind == "selffan":
        cap = max(1, M // 10)
        later = [x for x in range(i + 1, N + 1) if len(pending.get(x, [])) + 1 <= cap]
        if not later: return 0
        S = [i] + sorted(rnd10.sample(later, min(rnd10.choice([1, 1, 2]), len(later))))
        frm = rnd10.choice([u, email.utils.formataddr((f"MB{i} Support", u))])
        to = ", ".join(f"mb{x}@test.local" for x in S)
        h = m_hdr(xk, f"<t10-fan{i}-{j}@gen.test>", ts, frm, to, subj0)
        raw = m_text(h, w10(8, 80) + "\n")
        write(raw, ts)
        for x in S[1:]: pending.setdefault(x, []).append((raw, ts))
        note(frm, to)
        for x in S: t10conv(marker, f"mb{x}@test.local", u, subj0)
        t10acct(kind, len(S), len(S))
        return 1
    # dupidhdr / dupidbody: one new ticket whose Message-ID is used twice in this mailbox
    if room < 2: return 0
    cust = pool10(); frm = f"Customer {cust.split('@')[0]} <{cust}>"
    mid = f"<t10-dup{i}-{j}@gen.test>"
    body = w10(8, 80) + "\n"
    a = m_text(m_hdr(xk, mid, ts, frm, u, subj0), body)
    if kind == "dupidbody":
        b = m_text(m_hdr(xk, mid, ts, frm, u, subj0), body + "second delivery, same headers\n")
    elif rnd10.random() < .5:       # same Date and body, the second route added headers
        h = m_hdr(xk, mid, ts, frm, u, subj0, [f"Delivered-To: {u}", "Received: from mx2.gen.test (mx2.gen.test [10.0.0.2]) by mx1.gen.test (Postfix) with ESMTP id " + "".join(rnd10.choice("ABCDEF0123456789") for _ in range(10))])
        b = m_text(h, body)
    else:                           # other Date, other body
        ts2 = ts + rnd10.randint(1, max(1, min(3600, int(now - ts) - 2)))
        b = m_text(m_hdr(xk, mid, ts2, frm, u, subj0), body + "resent\n")
    write(a, ts); write(b, ts); used = 2
    if kind == "dupidhdr" and room > 2 and rnd10.random() < .3: write(b, ts); used = 3        # the second variant redelivered byte for byte
    note(frm, u)
    for _ in range(2 if kind == "dupidhdr" else 1): t10conv(marker, u, cust, subj0)
    t10acct(kind, 2 if kind == "dupidhdr" else 1, 2 if kind == "dupidhdr" else 1)
    return used

# one bulk sender per ~40 mails; the dates are shared by all mailboxes (a few seconds apart), so mailboxes fetched in parallel meet the sender at the same time
bursts = []
if V >= 8 and N >= 2:
    for b in range(1, max(1, M // 40) + 1):
        bursts.append((f"bulk{b}@bulk.example", time.time() - rnd8.randint(900, 3 * 86400)))
        burst_exp[bursts[-1][0]] = 0

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
    plan = None           # V>=6: (position, replies) of this mailbox's one long thread
    if V >= 6 and M >= 40 and rnd6.random() < .4: plan = (rnd6.randint(0, M // 2), min(rnd6.randint(30, 45), M // 3))
    def pool_addr():
        return f"cust{rnd4.randint(1, 300)}@example.org" if rnd4.random() < .7 else f"colleague{rnd4.randint(1, 80)}@partner.example"
    def pool_list(lo, hi):
        return [person(pool_addr(), rnd4.random() < .2) for _ in range(rnd4.randint(lo, hi))]
    bq = list(bursts) if V >= 8 else []        # V>=8: bulk senders still to write into this mailbox
    bcast = [M // 4, M // 2][:(2 if M >= 100 else 1)] if V >= 8 and i == 1 and N >= 4 and M >= 40 else []
    while j < M:
        if V >= 4 and pending.get(i) and (len(pending[i]) + len(bq) >= M - j or rnd4.random() < .1):   # copy of a mail that also went to this mailbox
            raw, pts = pending[i].pop(0)
            write(raw, pts); j += 1
            continue
        if plan and j >= plan[0]:
            K = min(plan[1], M - j - 1 - len(pending.get(i, [])) - len(bq))
            plan = None
            if K >= 5:
                j += long_thread(i, j, u, K, write)
                continue
        if bq and (len(pending.get(i, [])) + len(bq) >= M - j or rnd8.random() < len(bq) / (M - j)):
            addr, bts = bq.pop(0)
            ts = bts + rnd8.randint(0, 5)
            frm = email.utils.formataddr((rnd8.choice(NAMES), addr)) if rnd8.random() < .3 else addr
            write(build(f"<bulk{addr[4:addr.index('@')]}-{i}@gen.test>", frm, u, f"{rnd8.choice(WORDS)} bulk status {addr[:addr.index('@')]}", ts, with_att=rnd8.random() < .15), ts)
            note(frm, u); burst_exp[addr] += 1; exp8["burst_mails"] += 1
            exp["conversations"] += 1; exp["threads"] += 1; exp["attachments"] += ATT_N; att_sizes.extend(ATT_SIZES)
            j += 1
            continue
        if bcast and j >= bcast[0]:
            used = fanout(i, j, M - j - len(pending.get(i, [])) - len(bq), write, broadcast=True)
            if used: bcast.pop(0); j += used; continue
        if V >= 9 and rnd9.random() < .09:
            used = machine(i, j, u, M - j - len(pending.get(i, [])) - len(bq), write, tickets)
            if used: j += used; continue
        if V >= 10 and rnd10.random() < .08:
            used = theme10(i, j, u, M - j - len(pending.get(i, [])) - len(bq), write, tickets)
            if used: j += used; continue
        if V >= 7 and rnd7.random() < .06:
            mts = time.time() - rnd7.randint(600, 3 * 86400)
            raw, _, sz = build_malformed(i, j, u, mts)
            write(raw, mts); j += 1
            exp["attachments"] += len(sz); att_sizes.extend(sz)
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
            if V >= 8 and rnd8.random() < .04:
                used = fanout(i, j, M - j - len(pending.get(i, [])) - len(bq), write)
                if used: j += used; continue
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
            if V >= 9 and rnd9.random() < .35: extra += mailer_headers()
            if V >= 6 and not att and copies == 1 and rnd6.random() < .012: raw = build_huge(mid, from_hdr, to_hdr, hdr_subj, ts, extra)
            else: raw = build(mid, from_hdr, to_hdr, hdr_subj, ts, kind=kind, with_att=att, extra=extra, inline=inl)
            write(raw, ts)
            if copies == 2: pending.setdefault(jx, []).append((raw, ts))
            else: tickets.append((mid, cust, hdr_subj, ts, raw, from_hdr))
            exp["conversations"] += copies; exp["threads"] += copies; exp["attachments"] += ATT_N * copies; att_sizes.extend(ATT_SIZES * copies)
        j += 1

if V >= 7: exp["conversations"] += sum(mal_counts.values()); exp["threads"] += sum(mal_counts.values())
exp["customers"] = len(addrs) if V >= 4 else len(senders) + N   # + one customer per mailbox address: createCustomers() deliberately does not exclude the To address (upstream, exclusion commented out)
exp["mails_in_mailboxes"] = N * M
if V >= 5: exp.update(exp_extra, attachment_sizes=sorted(att_sizes))
if V >= 7: exp.update(malformed_counts=mal_counts)
if V >= 8: exp.update(exp8, fan_groups=fan_groups, fan_kinds=fan_kinds, burst_senders=burst_exp)
if V >= 9: exp.update(machine_kinds=mach, list_groups=list_groups)
if V >= 10: exp.update(t10_kinds=t10, t10_convs={k: sorted(v) for k, v in t10_convs.items()})
if V >= 6: exp.update(exp6, long_thread_sizes=sorted(long_sizes, reverse=True), min_huge_len=min(huge_lens) if huge_lens else 0, quote_checks=quote_checks)
open(os.path.join(os.path.dirname(OUT), "users"), "w").write("".join(f"{u}:{{PLAIN}}pw::::::\n" for u in users))
json.dump(exp, open(os.path.join(os.path.dirname(OUT), "expected.json"), "w"))
print(exp, file=sys.stderr)
