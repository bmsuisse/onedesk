#!/usr/bin/env python3
"""Browser smoke of the OneDesk web UI against odtest-web (real Chrome via Playwright).
usage: web.py BASE_URL IDS_JSON [--html-dir DIR]   (--html-dir: also write the normalised HTML of every page, used by golden / golden-check)
Exit 0 = all assertions ok. Prints one line per check, last line `-- web: N passed, M failed`."""
import json, re, sys, os, subprocess
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip('/'); ID = json.loads(sys.argv[2])
HTML_DIR = sys.argv[sys.argv.index('--html-dir') + 1] if '--html-dir' in sys.argv else None
passes = fails = 0
def ok(m):
    global passes; passes += 1; print('  ok  ', m)
def bad(m):
    global fails; fails += 1; print('  FAIL', m)
def check(c, m, detail=''):
    ok(m) if c else bad(m + (' :: ' + str(detail)[:300] if detail else ''))
def sql(q):
    return subprocess.run(['docker', 'exec', 'odtest-db', 'mariadb', '-ue2e', '-pe2e', 'e2e', '-N', '-e', q], capture_output=True, text=True).stdout.strip()

def normalise(h):
    h = re.sub(r'(name="_token"[^>]*value=")[^"]*', r'\1<TOKEN>', h)
    h = re.sub(r'(<meta name="csrf-token" content=")[^"]*', r'\1<TOKEN>', h)
    h = re.sub(r'(csrf[-_]token["\']?\s*[:=]\s*["\'])[^"\']*', r'\1<TOKEN>', h, flags=re.I)
    h = re.sub(r'nonce="[^"]*"', 'nonce="<NONCE>"', h)
    h = re.sub(r'\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?', '<TS>', h)
    h = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '<DATE>', h)
    h = re.sub(r'\b[0-9a-f]{32,64}\b', '<HASH>', h)
    h = re.sub(r'([?&](?:v|id|ver|version)=)[0-9a-zA-Z._-]+', r'\1<V>', h)
    h = re.sub(r'(?i)\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? [A-Z][a-z]{2,8} \d{1,2}(, \d{4})?', '<DAYDATE>', h)
    h = re.sub(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(, \d{4})?( at \d{1,2}:\d{2} ?[AP]M)?', '<DAYDATE>', h)
    h = re.sub(r'\b\d+ (?:seconds?|minutes?|hours?|days?) ago|just now|a few seconds ago|\d{1,2}:\d{2} ?[AP]M', '<AGO>', h, flags=re.I)
    h = re.sub(re.escape(HOST), '<HOST>', h)
    h = re.sub(r'\n\s*\n+', '\n', h)
    return h

# (name, path, expected final status, text that must appear)
P = [
 ('login', '/login', 200, None),   # anonymous
]
AUTH = [
 ('dashboard', '/', 200, None),
 ('mailboxes', '/mailboxes', 200, 'MB1'),
 ('mailbox-view', f"/mailbox/{ID['mailbox']}", 200, 'Printer on fire'),
 ('mailbox-folder', f"/mailbox/{ID['mailbox']}/{ID['folder']}", 200, None),
 ('conversation', f"/conversation/{ID['conv1']}", 200, 'printer is on fire'),
 ('conversation-2', f"/conversation/{ID['conv2']}", 200, 'invoice'),
 ('new-ticket', f"/mailbox/{ID['mailbox']}/new-ticket", 200, None),
 ('customer', f"/customers/{ID['customer1']}", 200, 'Anna'),
 ('customer-edit', f"/customers/{ID['customer1']}/edit", 200, None),
 ('customer-merge', f"/customers/{ID['customer1']}/merge", 200, None),
 ('search', '/search?q=printer', 200, 'Printer on fire'),
 ('search-customers', '/search?q=anna&mode=customers', 200, 'Anna'),
 ('users', '/users', 200, 'Agent'),
 ('user-new', '/users/wizard', 200, None),
 ('profile', f"/users/profile/{ID['user']}", 200, None),
 ('user-permissions', f"/users/permissions/{ID['user']}", 200, None),
 ('user-notifications', f"/users/notifications/{ID['user']}", 200, None),
 ('user-password', f"/users/password/{ID['user']}", 200, None),
 ('mailbox-settings', f"/mailbox/settings/{ID['mailbox']}", 200, None),
 ('mailbox-permissions', f"/mailbox/permissions/{ID['mailbox']}", 200, None),
 ('mailbox-outgoing', f"/mailbox/connection-settings/{ID['mailbox']}/outgoing", 200, None),
 ('mailbox-incoming', f"/mailbox/connection-settings/{ID['mailbox']}/incoming", 200, None),
 ('mailbox-autoreply', f"/mailbox/settings/{ID['mailbox']}/auto-reply", 200, None),
 ('mailbox-new', '/mailbox/new', 200, None),
 ('settings-general', '/app-settings', 200, None),
 ('settings-emails', '/app-settings/emails', 200, None),
 ('settings-alerts', '/app-settings/alerts', 200, None),
 ('system-status', '/system/status', 200, None),
 ('system-tools', '/system/tools', 200, None),
 ('modules', '/modules/list', 200, None),
 ('logs', '/app-logs/app', 200, None),
 ('translations', '/translations', 200, None),
 ('customers-ajax-search', '/customers/ajax-search?q=anna', 200, None),
]
HOST = BASE.split('//')[1]

with sync_playwright() as p:
    b = p.chromium.launch(channel='chrome'); ctx = b.new_context(); ctx.set_default_timeout(60000); ctx.set_default_navigation_timeout(90000); pg = ctx.new_page()
    errs = []
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)[:200] + ' @' + pg.url))
    def on_console(m):
        if m.type == 'error':
            u = (m.location or {}).get('url', '')
            if u and HOST not in u:
                return   # external resource (gravatar, fonts): the e2e network has no internet
            errs.append('console.error: ' + m.text[:200] + ' @' + pg.url)
    pg.on('console', on_console)
    def visit(name, path, want, needle):
        n0 = len(errs)
        r = pg.goto(BASE + path, wait_until='load')
        try: pg.wait_for_load_state('networkidle', timeout=8000)
        except Exception: pass
        h = pg.content()
        status = r.status if r else 0
        pat = r'<title>[^<]*(Whoops|Error)' if name == 'logs' else r'Whoops|ErrorException|Deprecated|Stack trace|Undefined (variable|index|array key|offset)'   # the log viewer legitimately shows old log lines
        good = status == want and not re.search(pat, h)
        check(good, f'GET {path} -> {status}', re.findall(r'Whoops|ErrorException|Deprecated|Undefined \w+', h)[:3])
        if needle: check(needle.lower() in h.lower(), f'{name}: shows "{needle}"')
        check(len(errs) == n0, f'{name}: no browser console errors', errs[n0:])
        if HTML_DIR and good and name != 'logs':
            os.makedirs(HTML_DIR, exist_ok=True)
            open(f'{HTML_DIR}/{name}.html', 'w').write(normalise(h))
        return r

    # --- anonymous
    r = visit('login', '/login', 200, 'password')
    r = pg.goto(BASE + '/mailboxes'); check('/login' in pg.url, 'anonymous /mailboxes redirects to /login', pg.url)
    r = pg.goto(BASE + '/system/status'); check('/login' in pg.url, 'anonymous /system/status redirects to /login', pg.url)
    # --- wrong password
    pg.goto(BASE + '/login'); pg.fill('input[name=email]', 'agent1@helpdesk.example'); pg.fill('input[name=password]', 'wrong'); pg.click('button[type=submit]'); pg.wait_for_load_state('networkidle')
    check('/login' in pg.url and 'credentials' in pg.content().lower(), 'wrong password rejected with message', pg.url)
    # --- login (CSRF-protected form POST)
    pg.goto(BASE + '/login'); pg.fill('input[name=email]', 'agent1@helpdesk.example'); pg.fill('input[name=password]', 'secret')
    with pg.expect_navigation(): pg.click('button[type=submit]')
    check('/login' not in pg.url, 'login with throwaway password succeeds', pg.url)
    check(any(c['name'].lower().endswith('_session') or 'session' in c['name'].lower() for c in ctx.cookies()), 'session cookie set', [c['name'] for c in ctx.cookies()])
    for name, path, want, needle in AUTH:
        visit(name, path, want, needle)

    # --- CSRF: a POST without token must be rejected, with the page token must work
    pg.goto(BASE + '/mailboxes')
    tok = pg.evaluate("document.querySelector('meta[name=csrf-token]').content")
    st = pg.evaluate("async (u) => (await fetch(u, {method:'POST', headers:{'X-Requested-With':'XMLHttpRequest'}, body:new URLSearchParams({action:'x'})})).status", BASE + '/conversation/ajax')
    check(st == 419, f'POST without CSRF token rejected (419)', st)
    st = pg.evaluate("async ([u,t]) => (await fetch(u, {method:'POST', headers:{'X-CSRF-TOKEN':t,'X-Requested-With':'XMLHttpRequest'}, body:new URLSearchParams({action:'x'})})).status", [BASE + '/conversation/ajax', tok])
    check(st != 419, 'POST with X-CSRF-TOKEN accepted by the CSRF layer', st)

    # --- profile form POST (changes a field)
    pg.goto(BASE + f"/users/profile/{ID['user']}")
    pg.fill('input[name=job_title]', 'E2E Tester')
    with pg.expect_navigation(): pg.click('form.form-horizontal button[type=submit], button.btn-primary[type=submit]')
    check(sql(f"select job_title from users where id={ID['user']}") == 'E2E Tester', 'profile POST persisted job_title', sql(f"select job_title from users where id={ID['user']}"))
    check('Whoops' not in pg.content(), 'profile POST page renders')

    # --- settings POST (general: company name)
    pg.goto(BASE + '/app-settings')
    pg.fill('input[name="settings[company_name]"]', 'E2E Company')
    with pg.expect_navigation(): pg.click('button.btn-primary[type=submit]')
    check(sql("select value from options where name='company_name'") == 'E2E Company', 'settings POST persisted company_name', sql("select value from options where name='company_name'"))

    # --- reply to a conversation through the real UI (summernote + ajax send_reply) -> new thread
    th0 = int(sql(f"select count(*) from threads where conversation_id={ID['conv1']} and type=2"))
    pg.goto(BASE + f"/conversation/{ID['conv1']}", wait_until='networkidle')
    pg.click('.conv-reply'); pg.wait_for_selector('#body + .note-editor, .note-editable', state='visible', timeout=10000)
    pg.evaluate("$('#body').summernote('code', '<p>Reply from the e2e browser test</p>')")
    pg.click('.btn-reply-submit')
    try: pg.wait_for_function("window.fs_processing_send_reply === false && document.body.innerText.includes('Reply from the e2e browser test')", timeout=20000)
    except Exception: pass
    pg.wait_for_timeout(1500)
    th1 = int(sql(f"select count(*) from threads where conversation_id={ID['conv1']} and type=2 and body like '%Reply from the e2e browser test%'"))
    check(th1 == 1, 'agent reply POST created exactly one message thread', th1)

    # --- new conversation through the UI
    pg.goto(BASE + f"/mailbox/{ID['mailbox']}/new-ticket", wait_until='networkidle')
    pg.evaluate("""() => { var to = $('#to'); if (to[0] && to[0].selectize) { to[0].selectize.createItem('new.person@example.com'); } }""")
    pg.fill('input[name=subject]', 'New conversation from e2e')
    pg.evaluate("$('#body').summernote('code', '<p>Body of the new conversation</p>')")
    pg.click('.btn-reply-submit')
    pg.wait_for_timeout(5000)
    n = sql("select count(*) from conversations where subject='New conversation from e2e'")
    check(n == '1', 'new-conversation POST created a conversation', n)
    if n == '1':
        t = sql("select count(*) from threads t join conversations c on c.id=t.conversation_id where c.subject='New conversation from e2e' and t.body like '%Body of the new conversation%'")
        check(t == '1', 'new conversation has its thread', t)

    # --- logout (POST + CSRF)
    pg.goto(BASE + '/', wait_until='networkidle')
    with pg.expect_navigation(): pg.evaluate("document.getElementById('logout-form').submit()")
    check('/login' in pg.url or pg.url.rstrip('/') == BASE, 'logout POST redirects', pg.url)
    pg.goto(BASE + '/mailboxes'); check('/login' in pg.url, 'after logout /mailboxes redirects to /login', pg.url)
    b.close()
print(f'  -- web: {passes} passed, {fails} failed')
sys.exit(1 if fails else 0)
