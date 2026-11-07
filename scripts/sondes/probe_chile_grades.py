"""Sonde : vocabulaire des descriptions de filets chiliens (DUS 2026-09 et 2026-03) — grades de qualite, trims, classes de taille."""
import collections, re, subprocess, sys
sys.path.insert(0, 'scripts')
subprocess.run('sudo apt-get install -y -qq p7zip-full p7zip-rar >/dev/null 2>&1', shell=True)
import build_chile_customs as B
res = B.resources()
for ym in sorted(res)[-1:] + [sorted(res)[-7]]:
    rows = B.read_month(res[ym]['url'])
    tok = collections.Counter(); ex = collections.defaultdict(list); big = collections.Counter()
    for x in rows:
        hs = x[B.C_HS].strip()
        if hs[:4] != '0304': continue
        kg = B.num(x[B.C_QTY]); txt = ' '.join(x[B.C_NOM:B.C_NOM + 6]).upper()
        fo = 'fresh' if hs[:5] == '03044' else 'frozen'
        for w in set(re.findall(r'[A-Z]{3,}(?:\s+[A-Z])?', txt)): tok[(fo, w)] += kg
        for k in ('TRIM', 'GRAD', 'CALID', 'PREM', 'INDUS', 'PRODUC', 'SUPER', 'STANDARD', 'ESTANDAR', 'SELECT', 'ORDIN', 'COMMERC', 'COMERC', 'REGULAR', 'EXTRA', 'SEGUND'):
            if k in txt and len(ex[(fo, k)]) < 6: ex[(fo, k)].append(f'{kg / 1000:.1f}t {txt[:150]}')
        big[(fo, txt[:120])] += kg
    print('=====', ym)
    for fo in ('fresh', 'frozen'):
        print('--', fo, 'mots les plus lourds (t)')
        print(', '.join([f'{w}:{v / 1000:.0f}' for (f, w), v in tok.most_common(400) if f == fo][:120]))
        for (f, k), v in ex.items():
            if f == fo: print('  ', k, '|', ' || '.join(v))
        print('-- descriptions les plus lourdes', fo)
        for (f, t), v in big.most_common(300):
            if f == fo and v > 30000: print(f'  {v / 1000:7.1f} t  {t}')
