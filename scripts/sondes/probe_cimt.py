"""Sonde CIMT : structure des fichiers annuels d'exportations (SH, pays, province, mensuel) et lignes saumon."""
import re, requests, json, zipfile, io, csv, time
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
p = requests.get('https://open.canada.ca/data/api/3/action/package_show', params={'id': '2909a648-5753-4924-878a-b069392d9cde'}, headers=H, timeout=60).json()['result']
for x in p['resources']: print('RES', x.get('format'), x.get('url'))
u = 'https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Dom_Exp_2026.zip'
t0 = time.time(); r = requests.get(u, headers=H, timeout=600); print('GET', u, r.status_code, len(r.content), round(time.time() - t0))
if not r.ok:
    u = u.replace('2026', '2025'); r = requests.get(u, headers=H, timeout=600); print('GET', u, r.status_code, len(r.content))
z = zipfile.ZipFile(io.BytesIO(r.content))
for n in z.namelist(): print('FILE', n, z.getinfo(n).file_size)
for n in [x for x in z.namelist() if x.endswith('.csv') or 'Prov' in x]:
    with z.open(n) as f:
        tx = io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace')
        head = [next(tx, '') for _ in range(5)]
        print('HEAD', n, ''.join(head)[:1500])
        k = 0
        for line in tx:
            if re.search(r'"03021411"|"030214"|"0304411\d"|"030441"', line):
                print('ROW', n, line.strip()[:300]); k += 1
                if k > 15: break
