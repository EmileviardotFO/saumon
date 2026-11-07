import requests, re, json, io, os, subprocess, csv, collections, zipfile
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
def get(u, **k):
    try: return requests.get(u, headers=H, timeout=300, **k)
    except Exception as e: print('ERR', u, e); return None
print('===== Aduanas 2026 resources')
r = get('https://datos.gob.cl/api/3/action/package_show', params={'id': 'registro-de-exportacion-2026'})
res = r.json()['result']['resources']
for x in res: print(x['name'], '|', x.get('format'), '|', x.get('size'), '|', x['url'], '|', x.get('last_modified') or x.get('created'))
# dernier fichier mensuel
cand = [x for x in res if re.search(r'(?i)export', x['name']) and x['url'].lower().endswith(('.rar', '.zip', '.csv', '.txt', '.7z'))]
x = cand[-1] if cand else res[-1]
print('DOWNLOAD', x['name'], x['url'])
subprocess.run('sudo apt-get install -y -qq p7zip-full p7zip-rar unrar >/dev/null 2>&1 || sudo apt-get install -y -qq p7zip-full >/dev/null 2>&1', shell=True)
os.makedirs('/tmp/adu', exist_ok=True)
b = get(x['url']).content; fn = '/tmp/adu/f' + os.path.splitext(x['url'])[1]; open(fn, 'wb').write(b); print('bytes', len(b))
print(subprocess.run(['7z', 'x', '-y', '-o/tmp/adu/x', fn], capture_output=True, text=True).stdout[-500:])
for root, _, files in os.walk('/tmp/adu/x'):
    for f in files:
        p = os.path.join(root, f); print('FILE', p, os.path.getsize(p))
        with open(p, 'rb') as fh: head = fh.read(3000)
        print(head.decode('latin-1')[:1500])
        # salmon rows: codes 0302 11/13/14, 0303 12/13/14, 0304 41/81, 0305 41
        n = 0; cnt = collections.Counter(); samp = []
        with open(p, encoding='latin-1') as fh:
            for line in fh:
                if re.search(r'[;|,\t](0302(11|13|14)|0303(12|13|14)|0304(41|81)|0305(41|43))\d{2}[;|,\t]', line):
                    n += 1
                    if len(samp) < 8: samp.append(line.strip()[:600])
        print('SALMON LINES', n); print('\n'.join(samp))
