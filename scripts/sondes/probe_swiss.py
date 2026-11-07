"""Sonde : fichier ouvert des douanes suisses (BAZG), importations par numero de tarif et pays, mensuel."""
import io, zipfile, requests, csv
for lang in ('en', 'fr'):
    u = f'https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_IMP_{lang}/TN8_IMP_{lang}.zip'
    r = requests.get(u, timeout=300, headers={'User-Agent': 'Mozilla/5.0 salmon-dashboard'})
    print(u, r.status_code, len(r.content), r.headers.get('content-type'))
    if not r.ok: continue
    z = zipfile.ZipFile(io.BytesIO(r.content))
    for n in z.namelist(): print('  ', n, z.getinfo(n).file_size)
    for n in z.namelist()[:3]:
        with z.open(n) as f:
            txt = io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace')
            head = [next(txt) for _ in range(4)]
            print('HEAD', n); [print('   ', h.strip()[:400]) for h in head]
            periods = set(); hits = 0
            for line in txt:
                if '0302' in line[:200] or '03021400' in line:
                    hits += 1
                    if hits <= 8: print('   HIT', line.strip()[:300])
            print('   hits', hits)
    break
