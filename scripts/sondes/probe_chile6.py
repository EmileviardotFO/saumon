import requests, re, os, subprocess, collections
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
subprocess.run('sudo apt-get install -y -qq p7zip-full p7zip-rar >/dev/null 2>&1', shell=True)
r = requests.get('https://datos.gob.cl/api/3/action/package_show', params={'id': 'registro-de-exportacion-2026'}, headers=H, timeout=60)
res = {x['name'].strip(): x for x in r.json()['result']['resources']}
SAL = re.compile(r'^030(2(11|13|14)|3(12|13|14)|4(41|81|42|82)|5(41|43))')
def load(name):
    x = res[name]; d = '/tmp/' + re.sub(r'\W', '', name); os.makedirs(d, exist_ok=True); fn = d + '/f' + os.path.splitext(x['url'])[1]
    open(fn, 'wb').write(requests.get(x['url'], headers=H, timeout=600).content)
    subprocess.run(['7z', 'x', '-y', '-o' + d + '/x', fn], capture_output=True)
    p = [os.path.join(a, f) for a, _, fs in os.walk(d + '/x') for f in fs][0]
    rows = [l.split(';') for l in open(p, encoding='latin-1').read().splitlines()]
    return rows
out = {}
for name in ['Exportaciones enero 2026', 'Exportaciones septiembre 2026']:
    rows = load(name)
    # colonne du code SH : la plus frequente parmi les champs de 8 chiffres commencant par 0-9 et pas une date du mois
    hs = None
    for j in range(60, 84):
        vals = [x[j].strip() for x in rows[:5000] if len(x) > j]
        if sum(bool(re.fullmatch(r'\d{8}', v)) for v in vals) > 3000: hs = j; break
    sal = [x for x in rows if len(x) > hs and SAL.match(x[hs].strip())]
    print('=====', name, 'rows', len(rows), 'HS col', hs, 'salmon rows', len(sal))
    for x in sal[:4]: print(' | '.join(f'{j}:{v.strip()[:35]}' for j, v in enumerate(x) if v.strip()))
    # colonnes : 5 = NRO_EXPORTADOR, 7 = comuna, 14 = region origine, 20 = pays ; quantite/FOB : chercher apres hs
    print('cols after hs:', [ (j, sal[0][j]) for j in range(hs, min(hs+6, len(sal[0])))])
    q = hs + 2; fob = hs + 4
    num = lambda v: float(v.replace(',', '.') or 0)
    exp = collections.defaultdict(lambda: [0.0, 0.0, collections.Counter(), collections.Counter()])
    for x in sal:
        e = exp[x[5]]; e[0] += num(x[q]); e[1] += num(x[fob]); e[2][x[14]] += num(x[q]); e[3][(x[hs+ -0 -0 - 0 - 0 -  - 0][:0]) or x[hs-7][:30]] += 1
    tot = sum(v[0] for v in exp.values())
    print('exporters', len(exp), 'total qty', round(tot), 'FOB', round(sum(v[1] for v in exp.values())))
    for k, v in sorted(exp.items(), key=lambda kv: -kv[1][0])[:25]:
        print('EXP', k, round(v[0]), f'{100*v[0]/tot:.1f}%', 'FOB', round(v[1]), 'regions', dict(v[2].most_common(3)), 'desc', v[3].most_common(2))
    out[name] = {k: v[0] for k, v in exp.items()}
    print('regions', collections.Counter(x[14] for x in sal).most_common(10)); print('units', collections.Counter(x[hs+1] for x in sal).most_common(5))
    print('desc samples', collections.Counter(x[hs-7].strip()[:50] for x in sal).most_common(15))
a, b = out['Exportaciones enero 2026'], out['Exportaciones septiembre 2026']
print('IDs in both', len(set(a) & set(b)), 'of', len(a), len(b))
