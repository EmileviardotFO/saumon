import requests, re, os, subprocess, collections, io
import openpyxl
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
r = requests.get('https://datos.gob.cl/api/3/action/package_show', params={'id': 'registro-de-exportacion-2026'}, headers=H, timeout=60)
res = r.json()['result']['resources']
meta = next(x for x in res if 'Metadata' in x['name'])
wb = openpyxl.load_workbook(io.BytesIO(requests.get(meta['url'], headers=H, timeout=120).content), read_only=True)
print('===== DICTIONNAIRE')
for ws in wb.worksheets:
    print('--', ws.title)
    for row in ws.iter_rows(values_only=True):
        if any(row): print(' | '.join(str(c)[:90] for c in row if c is not None))
main = [x for x in res if re.fullmatch(r'Exportaciones \w+ 2026', x['name'].strip())][-1]
print('===== FICHIER', main['name'])
subprocess.run('sudo apt-get install -y -qq p7zip-full p7zip-rar >/dev/null 2>&1', shell=True)
os.makedirs('/tmp/a', exist_ok=True); fn = '/tmp/a/m' + os.path.splitext(main['url'])[1]
open(fn, 'wb').write(requests.get(main['url'], headers=H, timeout=600).content)
subprocess.run(['7z', 'x', '-y', '-o/tmp/a/x', fn], capture_output=True)
p = [os.path.join(r_, f) for r_, _, fs in os.walk('/tmp/a/x') for f in fs][0]; print('FILE', p, os.path.getsize(p))
lines = open(p, encoding='latin-1').read().splitlines(); print('lines', len(lines)); print('\n'.join(l[:700] for l in lines[:3]))
# trouver la colonne du code SH (8 chiffres) qui commence par 0302/0303/0304/0305
rows = [l.split(';') for l in lines]
ncol = collections.Counter(len(x) for x in rows).most_common(1)[0][0]; print('ncol', ncol)
hs_col = None
for j in range(ncol):
    vals = [x[j].strip() for x in rows[:3000] if len(x) > j]
    if sum(bool(re.fullmatch(r'\d{8}', v)) for v in vals) > 2000: hs_col = j; print('HS col', j, vals[:5]); break
sal = [x for x in rows if len(x) > hs_col and re.match(r'030(2(11|13|14)|3(12|13|14)|4(41|81)|5(41|43))', x[hs_col].strip())]
print('SALMON ROWS', len(sal))
for x in sal[:6]: print(' | '.join(f'{j}:{v.strip()[:40]}' for j, v in enumerate(x) if v.strip()))
for j in range(ncol):
    c = collections.Counter(x[j].strip() for x in sal)
    if 1 < len(c) < 400: print('COL', j, len(c), c.most_common(12))
