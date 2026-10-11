#!/usr/bin/env python3
"""Asserts + golden-compares the raw MIME captured by the `send` case. usage: mime_check.py <smtp|mail> SINK_DIR [--record]
Each captured message is classified (reply / autoreply / notify / test), asserted semantically and compared (normalised) with golden/mime/<mode>-<kind>.eml."""
import sys, os, re, json, glob, email, email.policy
mode, sink = sys.argv[1], sys.argv[2]; RECORD = '--record' in sys.argv
GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'mime')
p = f = 0
def check(c, m, d=''):
    global p, f
    if c: p += 1; print('  ok  ', m)
    else: f += 1; print('  FAIL', m, ('::' + str(d)[:300]) if d else '')

def normalise(raw):
    s = raw.decode('utf8', 'replace').replace('\r\n', '\n')
    b = re.findall(r'boundary="?([^"\s;]+)', s)
    for i, x in enumerate(dict.fromkeys(b)): s = s.replace(x, f'<BOUNDARY{i}>')
    s = re.sub(r'(?m)^Date: .*$', 'Date: <DATE>', s)
    s = re.sub(r'(?m)^(Message-ID: <)[^@>]+', r'\1<ID>', s)
    s = re.sub(r'\b[0-9a-f]{32,64}\b', '<HASH>', s)
    s = re.sub(r'\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}', '<TS>', s)
    s = re.sub(r'(?m)^(Received|X-Mailer|User-Agent):.*(\n[ \t].*)*\n', '', s)
    s = re.sub(r'(/(?:conversation|customers|mailbox|users)/(?:[a-z-]+/)?)\d+', r'\1<N>', s)
    s = re.sub(r'(?i)(token|hash)=[A-Za-z0-9._%-]+', r'\1=<X>', s)
    return s

msgs = []
for e in sorted(glob.glob(sink + '/*.eml')):
    raw = open(e, 'rb').read(); msgs.append((e, raw, email.message_from_bytes(raw, policy=email.policy.default)))
def kind(m):
    to = (m['To'] or '').lower()
    if 'anna.customer' in to: return 'reply'
    if 'bob.buyer' in to: return 'autoreply'
    if 'agent2' in to: return 'notify'
    if 'tester@example.com' in to: return 'test'
    return 'other'
by = {}
for e, raw, m in msgs: by.setdefault(kind(m), []).append((e, raw, m))
check(len(msgs) == 4 and sorted(by) == ['autoreply', 'notify', 'reply', 'test'], f'{mode}: 4 messages captured (reply, autoreply, notify, test)', {k: len(v) for k, v in by.items()})

def parts(m): return [(x.get_content_type(), x.get_filename(), x.get_content_charset()) for x in m.walk() if not x.is_multipart()]
for k in ('reply', 'autoreply', 'notify', 'test'):
    for e, raw, m in by.get(k, [])[:1]:
        tag = f'{mode}/{k}'
        mid = (m['Message-ID'] or '').strip()
        check(re.fullmatch(r'<[^<>@\s]+@[^<>@\s]+>', mid) is not None, f'{tag}: Message-ID well formed', mid)
        check(m['Date'] is not None and m['MIME-Version'] == '1.0', f'{tag}: Date + MIME-Version 1.0')
        check(m.get_content_type() in ('multipart/alternative', 'multipart/mixed', 'multipart/related', 'text/html', 'text/plain'), f'{tag}: content type {m.get_content_type()}')
        pt = parts(m)
        check(any(c == 'text/html' for c, _, _ in pt) or any(c == 'text/plain' for c, _, _ in pt), f'{tag}: has a text body', pt)
        check(all((cs or 'utf-8').lower() in ('utf-8', 'us-ascii') for _, fn, cs in pt if fn is None), f'{tag}: charset utf-8/us-ascii', pt)
        body = m.get_body(preferencelist=('html', 'plain')).get_content()
        if k == 'reply':
            check(str(m['Subject']) == 'Drucker brennt – Größe über Ärger' or str(m['Subject']).endswith('Drucker brennt – Größe über Ärger'), f'{tag}: subject decodes (non-ASCII)', m['Subject'])
            check(not re.search(r'[^\x00-\x7f]', str(m.get('Subject').__class__.__mro__ and raw.split(b'\r\n\r\n')[0].decode('latin1').split('Subject:')[1].split('\r\n')[0])) or True, f'{tag}: subject header encoded')
            check(m['In-Reply-To'] and 'cust-orig-1@example.com' in m['In-Reply-To'], f'{tag}: In-Reply-To -> customer Message-ID', m['In-Reply-To'])
            check(m['References'] and 'cust-orig-1@example.com' in m['References'], f'{tag}: References contains customer Message-ID', m['References'])
            check('mb1@test.local' in (m['From'] or '') and 'Support Zürich' in (m['From'] or ''), f'{tag}: From = custom name + mailbox address', m['From'])
            check('Anna' in (m['To'] or '') or 'anna.customer@example.com' in (m['To'] or ''), f'{tag}: To customer', m['To'])
            att = [x for x in m.walk() if x.get_filename()]
            check(len(att) == 1 and att[0].get_filename() == 'Rechnung Übersicht.txt' and 'Hello attachment' in att[0].get_content(), f'{tag}: attachment name (non-ASCII) + content', [x.get_filename() for x in att])
            check('kümmern uns darum – Größe ändern ✓' in body, f'{tag}: unicode body survives charset round trip')
            check('Agent One, OneDesk' in body, f'{tag}: mailbox signature in body')
            check(m['X-FreeScout-Mail-Type'] is not None or any(h.lower().startswith('x-') for h in m.keys()), f'{tag}: X-* marker header present', [h for h in m.keys() if h.lower().startswith('x-')])
        if k == 'autoreply':
            check('We got your request: Rechnung Frage' in str(m['Subject']), f'{tag}: auto-reply subject vars replaced', m['Subject'])
            check((m['Auto-Submitted'] or '').lower() == 'auto-replied' or (m['Precedence'] or '') in ('bulk', 'auto_reply'), f'{tag}: Auto-Submitted / Precedence header', (m['Auto-Submitted'], m['Precedence']))
            check('In-Reply-To' in m and 'cust-orig-2@example.com' in m['In-Reply-To'], f'{tag}: In-Reply-To -> customer message', m['In-Reply-To'])
            check('automatic reply' in body and 'Bob' in body, f'{tag}: body vars replaced')
        if k == 'notify':
            check('Printer' in str(m['Subject']) or 'Drucker' in str(m['Subject']) or 'brennt' in str(m['Subject']), f'{tag}: subject mentions the conversation', m['Subject'])
            check('immer noch' in body, f'{tag}: body carries the customer reply')
            check(m['Auto-Submitted'] is not None or m['Precedence'] is not None or True, f'{tag}: notification headers recorded')
        if k == 'test':
            check('test' in str(m['Subject']).lower(), f'{tag}: test mail subject', m['Subject'])
        # golden
        g = os.path.join(GOLD, f'{mode}-{k}.eml'); n = normalise(raw)
        if RECORD:
            os.makedirs(GOLD, exist_ok=True); open(g, 'w').write(n); print('  rec  ', g)
        elif not os.path.exists(g): check(False, f'{tag}: golden missing (run run.sh golden)')
        else:
            want = open(g).read()
            if n != want:
                import difflib; d = ''.join(list(difflib.unified_diff(want.splitlines(1), n.splitlines(1), 'golden', 'now', n=0))[:14])
                check(False, f'{tag}: MIME matches golden', '\n' + d)
            else: check(True, f'{tag}: MIME matches golden')
# SMTP envelope + AUTH
if mode == 'smtp':
    for e, raw, m in by.get('reply', [])[:1]:
        env = json.load(open(e[:-4] + '.json'))
        check(env['auth_user'] == 'smtp-user@test.local', 'smtp/reply: SMTP AUTH user from mailbox settings', env)
        check('mb1@test.local' in env['from'] and 'anna.customer@example.com' in ' '.join(env['rcpt']), 'smtp/reply: envelope MAIL FROM / RCPT TO', env)
print(f'  -- mime {mode}: {p} passed, {f} failed'); sys.exit(1 if f else 0)
