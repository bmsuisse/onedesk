#!/usr/bin/env python3
"""Minimal SMTP sink for the e2e `send` case (stdlib only, python:3.12-slim). Listens on :2525, accepts every message and writes it
raw to /sink/NNNN.eml plus /sink/NNNN.json (envelope + AUTH user). Optionally advertises STARTTLS-less AUTH PLAIN/LOGIN and accepts any credentials."""
import asyncio, base64, itertools, json, os
N = itertools.count(1)
async def handle(r, w):
    async def say(s): w.write((s + '\r\n').encode()); await w.drain()
    env = {'from': None, 'rcpt': [], 'auth_user': None}
    await say('220 sink ESMTP')
    try:
        while True:
            line = (await r.readline()).decode('utf8', 'replace').rstrip('\r\n')
            if not line: break
            cmd = line.upper()
            if cmd.startswith('EHLO'):
                w.write(b'250-sink\r\n250-8BITMIME\r\n250-SIZE 52428800\r\n250 AUTH PLAIN LOGIN\r\n'); await w.drain()
            elif cmd.startswith('HELO'): await say('250 sink')
            elif cmd.startswith('AUTH PLAIN'):
                parts = line.split(' ', 2)
                if len(parts) < 3: await say('334 '); parts.append((await r.readline()).decode().strip())
                env['auth_user'] = base64.b64decode(parts[2]).split(b'\0')[1].decode(); await say('235 ok')
            elif cmd.startswith('AUTH LOGIN'):
                await say('334 VXNlcm5hbWU6'); env['auth_user'] = base64.b64decode((await r.readline()).strip()).decode()
                await say('334 UGFzc3dvcmQ6'); await r.readline(); await say('235 ok')
            elif cmd.startswith('MAIL FROM'): env['from'] = line[10:].strip(); env['rcpt'] = []; await say('250 ok')
            elif cmd.startswith('RCPT TO'): env['rcpt'].append(line[8:].strip()); await say('250 ok')
            elif cmd == 'DATA':
                await say('354 go')
                buf = []
                while True:
                    l = await r.readline()
                    if l in (b'.\r\n', b'.\n', b''): break
                    buf.append(l[1:] if l.startswith(b'..') else l)
                i = next(N); base = f'/sink/{int(os.environ.get("T0", 0)) + i:04d}'
                open(base + '.eml', 'wb').write(b''.join(buf)); open(base + '.json', 'w').write(json.dumps(env))
                await say(f'250 2.0.0 Ok: queued as SINKQ{i:04d}')
            elif cmd == 'RSET': env.update(from_=None); await say('250 ok')
            elif cmd == 'NOOP': await say('250 ok')
            elif cmd == 'QUIT': await say('221 bye'); break
            else: await say('502 unsupported')
    finally:
        w.close()
async def main():
    s = await asyncio.start_server(handle, '0.0.0.0', 2525); await s.serve_forever()
asyncio.run(main())
