#!/usr/bin/env python3
"""
Chili : cycles de production termines, centre par centre (loi 21.532 de transparence, fichiers Sernapesca).

  xlsx/chile/transparencia/Cosechas_*.xlsx       tonnes recoltees par centre et par cycle (espece, debut et fin du cycle)
  xlsx/chile/transparencia/Mortalidades_*.xlsx   poissons morts sur le cycle
  xlsx/chile/transparencia/Tratamientos_*.xlsx   kg de principe actif par cycle (antibiotiques, antiparasitaires), avec le groupe
  data/chile_sites.json                          concession -> groupe, region, commune, position

Un cycle apparait dans le semestre ou il se termine. Le nombre de poissons mis a l'eau n'est pas publie : la mortalite en %
est ESTIMEE = morts / (morts + poissons recoltes), poissons recoltes = tonnes / poids moyen suppose par espece (W ci-dessous).

    python3 scripts/build_chile_cycles.py        -> data/chile_cycles.json
"""
import collections, glob, json, os, re, statistics as S, unicodedata
import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'xlsx', 'chile', 'transparencia')
SP = {'SALMON DEL ATLANTICO': 'Atlantic', 'SALMON COHO': 'Coho', 'TRUCHA ARCOIRIS': 'Trout'}
W = {'Atlantic': 5.0, 'Coho': 3.6, 'Trout': 3.0}       # kg vif a la recolte, hypothese (pas de moyenne officielle publiee)
REG = {'10': 'Los Lagos', '11': 'Aysén', '12': 'Magallanes'}
HOLD = [('AquaChile', r'AQUACHILE|AGROSUPER|LOS FIORDOS|AGUAS CLARAS|VERLASSO'), ('Mowi', r'MOWI'), ('Cermaq', r'CERMAQ'), ('Multi X', r'MULTIEXPORT|MULTI-?X'), ('Blumar', r'BLUMAR'), ('Australis', r'AUSTRALIS'),
        ('Camanchaca', r'CAMANCHACA'), ('Salmones Austral', r'SALMONES AUSTRAL|PACIFIC STAR|TRUSAL'), ('Yadran', r'YADRAN'), ('Ventisqueros', r'VENTISQUEROS'), ('Marine Farm', r'MARINE FARM|TORNAGALEON'),
        ('Invermar', r'INVERMAR'), ('Salmones Antártica', r'ANTARTICA'), ('Salmones de Chile', r'SALMONES DE CHILE'), ('Cooke', r'COOKE'), ('Caleta Bay', r'CALETA BAY'), ('Salmones Aysén', r'SALMONES AYSEN'),
        ('Nova Austral', r'NOVA AUSTRAL'), ('Blumar', r'BLUMAR'), ('Friosur', r'FRIOSUR')]


def plain(s):
    return unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().upper().strip()


def hold(*names):
    for n in names:
        p = plain(n)
        for h, rx in HOLD:
            if re.search(rx, p):
                return h
    return None


def load(pat):
    f = sorted(glob.glob(os.path.join(SRC, pat)))
    if not f:
        return []
    rows = list(openpyxl.load_workbook(f[-1], read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows[:20]) if r and sum(c is not None for c in r) >= 5)
    hd = [plain(c) for c in rows[h]]
    out = []
    for r in rows[h + 1:]:
        d = dict(zip(hd, r))
        if isinstance(d.get('CODIGO CENTRO'), int):
            out.append(d)
    return out


def get(d, *starts):
    for k, v in d.items():
        if any(k.startswith(s) for s in starts):
            return v


def per(p):
    m = re.search(r'(\d)\w*\s+SEMESTRE\s+(\d{4})', plain(p))
    return f'{m.group(2)}H{m.group(1)}' if m else None


def med(v, d=1):
    return round(S.median(v), d) if v else None


def main():
    C, Mo, T = load('Cosechas_*.xlsx'), load('Mortalidades_*.xlsx'), load('Tratamientos_*.xlsx')
    if not C:
        print('chile cycles : fichiers absents')
        return
    sites = {}
    try:
        for s in json.load(open(os.path.join(ROOT, 'data', 'chile_sites.json')))['sites']:
            sites[s['code']] = s
    except Exception:
        pass
    key = lambda d: (d['CODIGO CENTRO'], get(d, 'MES ANO INICIO'))
    mort = {key(d): get(d, 'MORT') for d in Mo}
    tr, hmap = collections.defaultdict(lambda: collections.defaultdict(float)), {}
    for d in T:
        kg = get(d, 'CANTIDAD') or 0
        a, typ = plain(d.get('PRINCIPIO ACTIVO')), plain(d.get('TIPO FARMACO'))
        k = 'ab' if 'ANTIMICROB' in typ else 'h2o2' if 'PEROXIDO' in a else 'ap'
        tr[key(d)][k] += kg
        tr[key(d)]['a:' + a.title()] += kg
        hmap[d['CODIGO CENTRO']] = hold(d.get('HOLDING'), d.get('EMPRESA')) or plain(d.get('HOLDING')).title()
    cyc = []
    for d in C:
        t = d.get('TONELADAS COSECHADAS') or 0
        a, b = get(d, 'MES ANO INICIO'), get(d, 'MES ANO FIN')
        sp = SP.get(plain(d.get('ESPECIE')), 'Other')
        code = d['CODIGO CENTRO']
        s = sites.get(code, {})
        h = hold(d.get('EMPRESA')) or hmap.get(code) or hold(s.get('h'), s.get('t')) or 'Other'
        m = mort.get(key(d))
        x = tr.get(key(d), {})
        fish = t * 1000 / W.get(sp, 4.5) if t else 0
        c = {'code': code, 'h': h, 'co': str(d.get('EMPRESA') or '').title(), 'sp': sp, 'r': REG.get(str(code)[:2], 'Other'), 'com': (s.get('c') or '').title(), 'p': per(get(d, 'PERIODO')),
             't': round(t), 'start': a.strftime('%Y-%m') if a else None, 'end': b.strftime('%Y-%m') if b else None, 'mo': round((b - a).days / 30.44) if a and b else None,
             'dead': m, 'dpt': round(m / t, 1) if m is not None and t > 200 else None, 'mp': round(100 * m / (m + fish), 1) if m is not None and t > 200 else None,
             'ab': round(1000 * x.get('ab', 0) / t) if t > 200 else None, 'ap': round(1000 * x.get('ap', 0) / t, 1) if t > 200 else None, 'ab_kg': round(x.get('ab', 0)), 'h2o2': round(x.get('h2o2', 0))}
        cyc.append(c)
    cyc = [c for c in cyc if c['p']]
    periods = sorted({c['p'] for c in cyc})
    years = sorted({p[:4] for p in periods})

    def agg(X):
        t = sum(c['t'] for c in X)
        big = [c for c in X if c['t'] > 200]
        tb = sum(c['t'] for c in big)
        dead = sum(c['dead'] or 0 for c in big)
        fish = sum(c['t'] * 1000 / W.get(c['sp'], 4.5) for c in big)
        return {'n': len(X), 'kt': round(t / 1000, 1), 'tpc': round(t / len(X)) if X else None, 'mo': med([c['mo'] for c in big if c['mo']], 0), 'dead_m': round(dead / 1e6, 2),
                'mp': round(100 * dead / (dead + fish), 1) if fish else None, 'ab': round(1000 * sum(c['ab_kg'] for c in big) / tb) if tb else None,
                'ab_t': round(sum(c['ab_kg'] for c in X) / 1000, 1), 'noab': round(100 * sum(c['ab_kg'] == 0 for c in big) / len(big)) if big else None}
    out = {'meta': {'source': 'Sernapesca, transparency files of law 21.532 (harvest, mortality and treatments per farm and per finished cycle)', 'weights': W, 'periods': periods, 'years': years,
                    'note': 'A cycle is counted in the half-year in which it ends. Mortality % is our estimate: dead fish / (dead fish + harvested fish), harvested fish = tonnes / assumed live weight per species. Cycles under 200 t are left out of the ratios.'},
           'species': {sp: {p: agg([c for c in cyc if c['sp'] == sp and c['p'] == p]) for p in periods} for sp in ('Atlantic', 'Coho', 'Trout')},
           'species_year': {sp: {y: agg([c for c in cyc if c['sp'] == sp and c['p'][:4] == y]) for y in years} for sp in ('Atlantic', 'Coho', 'Trout')},
           'regions': {r: {y: agg([c for c in cyc if c['r'] == r and c['sp'] == 'Atlantic' and c['p'][:4] == y]) for y in years} for r in ('Los Lagos', 'Aysén', 'Magallanes')}}
    hs = collections.Counter()
    for c in cyc:
        hs[c['h']] += c['t']
    out['holdings'] = [{'h': h, 'kt': round(v / 1000, 1), 'atl': {y: agg([c for c in cyc if c['h'] == h and c['sp'] == 'Atlantic' and c['p'][:4] == y]) for y in years},
                        'coho': {y: agg([c for c in cyc if c['h'] == h and c['sp'] == 'Coho' and c['p'][:4] == y]) for y in years},
                        'all': {y: agg([c for c in cyc if c['h'] == h and c['p'][:4] == y]) for y in years}} for h, v in hs.most_common(16) if h != 'Other']
    # principes actifs par annee (tonnes), et par tonne recoltee
    act = collections.defaultdict(lambda: collections.defaultdict(float))
    for d in T:
        p = per(get(d, 'PERIODO'))
        if p:
            act[plain(d.get('PRINCIPIO ACTIVO')).title()][p[:4]] += (get(d, 'CANTIDAD') or 0) / 1000
    out['actives'] = [{'a': a, 'y': {y: round(v.get(y, 0), 2) for y in years}} for a, v in sorted(act.items(), key=lambda z: -sum(z[1].values())) if sum(v.values()) > 0.05]
    # liens : mortalite contre duree et antibiotiques (Atlantique, cycles > 1000 t)
    A = [c for c in cyc if c['sp'] == 'Atlantic' and c['t'] > 1000 and c['mp'] is not None and c['mo']]

    def cor(a, b):
        n = len(a); ma, mb = sum(a) / n, sum(b) / n
        va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
        return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** .5, 2) if va and vb else None
    out['links'] = {'n': len(A), 'mort_len': cor([c['mp'] for c in A], [c['mo'] for c in A]), 'mort_ab': cor([c['mp'] for c in A], [c['ab'] for c in A]), 'mort_size': cor([c['mp'] for c in A], [c['t'] for c in A]),
                    'bands': [{'lab': lab, 'n': len(X), 'mo': med([c['mo'] for c in X], 0), 't': med([c['t'] for c in X], 0), 'ab': med([c['ab'] for c in X], 0)} for lab, X in
                              (('under 5 %', [c for c in A if c['mp'] < 5]), ('5 to 10 %', [c for c in A if 5 <= c['mp'] < 10]), ('10 to 20 %', [c for c in A if 10 <= c['mp'] < 20]), ('20 % and more', [c for c in A if c['mp'] >= 20]))]}
    # rotation : ecart entre deux fins de cycle sur le meme centre
    bc = collections.defaultdict(list)
    for c in cyc:
        if c['end']:
            bc[c['code']].append(c)
    g, fa = collections.defaultdict(list), collections.defaultdict(list)
    ym = lambda s: int(s[:4]) * 12 + int(s[5:])
    for v in bc.values():
        v.sort(key=lambda c: c['end'])
        for a, b in zip(v, v[1:]):
            if a['sp'] == b['sp']:
                g[a['sp']].append(ym(b['end']) - ym(a['end'])); fa[a['sp']].append(ym(b['start']) - ym(a['end']))
    out['rotation'] = {sp: {'n': len(g[sp]), 'gap': med(g[sp], 0), 'fallow': med(fa[sp], 0)} for sp in g}
    out['centres'] = len(bc)
    last = years[-1]
    out['cycles'] = sorted(([c[k] for k in ('code', 'h', 'sp', 'r', 'com', 'p', 't', 'mo', 'mp', 'ab', 'ap', 'start', 'end')] for c in cyc if c['p'][:4] == last and c['t'] > 200), key=lambda r: -r[6])
    out['cycle_cols'] = ['code', 'h', 'sp', 'r', 'com', 'p', 't', 'mo', 'mp', 'ab', 'ap', 'start', 'end']
    json.dump(out, open(os.path.join(ROOT, 'data', 'chile_cycles.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f"chile_cycles.json : {len(cyc)} cycles, {len(bc)} centres, {periods[0]} -> {periods[-1]}")


if __name__ == '__main__':
    main()
