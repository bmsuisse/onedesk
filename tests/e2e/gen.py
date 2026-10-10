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
    while j < M:
        if V >= 4 and pending.get(i) and (len(pending[i]) >= M - j or rnd4.random() < .1):   # copy of a mail that also went to this mailbox
            raw, pts = pending[i].pop(0)
            write(raw, pts); j += 1
            continue
        if plan and j >= plan[0]:
            K = min(plan[1], M - j - 1 - len(pending.get(i, [])))
            plan = None
            if K >= 5:
                j += long_thread(i, j, u, K, write)
                continue
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
if V >= 6: exp.update(exp6, long_thread_sizes=sorted(long_sizes, reverse=True), min_huge_len=min(huge_lens) if huge_lens else 0, quote_checks=quote_checks)
open(os.path.join(os.path.dirname(OUT), "users"), "w").write("".join(f"{u}:{{PLAIN}}pw::::::\n" for u in users))
json.dump(exp, open(os.path.join(os.path.dirname(OUT), "expected.json"), "w"))
print(exp, file=sys.stderr)
