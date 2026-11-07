#!/usr/bin/env python3
"""
data/chile_customs.json : exportations chiliennes de salmonides, chaque mois, d'apres les declarations d'exportation
(DUS) publiees en donnees ouvertes par le Servicio Nacional de Aduanas (datos.gob.cl, un fichier par mois, environ
un mois apres le mois concerne).

Les donnees sont anonymisees : pas de nom ni de RUT. L'exportateur a un numero unique... renumerote chaque mois.
On relie donc un meme exportateur d'un mois a l'autre par ses codes produits internes (references d'articles qu'il
ecrit devant la description : « 24094 », « 3000056 », « S-A-POR-6-OZ »...) : deux exportateurs-mois qui partagent
une reference sont le meme. Chaque groupe recoit un identifiant stable (EXP-xxx) ; le nom n'est pas connu.

Sorties par mois : volumes (kg nets) et FOB (USD) par espece et forme, par pays de destination, par region d'origine,
par voie (avion / bateau / route), et par groupe d'exportateurs (avec ses references, regions, destinations).

    python3 scripts/build_chile_customs.py [--depuis 2023]
"""
import collections, io, json, os, re, subprocess, sys, tempfile, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'chile_customs.json')
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
API = 'https://datos.gob.cl/api/3/action/package_show'
MOIS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
DEPUIS = int(sys.argv[sys.argv.index('--depuis') + 1]) if '--depuis' in sys.argv else 2023
SAL = re.compile(r'^030(2(11|13|14)|3(12|13|14)|4(41|42|81|82|99)|5(41|43|39|49))')
REG = {'10': 'Los Lagos', '11': 'Aysén', '12': 'Magallanes', '14': 'Los Ríos', '8': 'Biobío', '13': 'Metropolitana'}
VIA = {'1': 'sea', '4': 'air', '7': 'road', '5': 'road'}
C_EXP, C_COM, C_REG, C_VIA, C_DEST, C_NOM, C_HS, C_QTY, C_FOB = 5, 7, 14, 16, 20, 62, 69, 71, 73


def species(desc, hs):
    d = desc.upper()
    if 'TRUCHA' in d: return 'trout'
    if 'COHO' in d or 'PLATEADO' in d: return 'coho'
    if 'ATL' in d or 'SALAR' in d: return 'atlantic'
    return {'030211': 'trout', '030314': 'trout', '030442': 'trout', '030482': 'trout', '030543': 'trout',
            '030213': 'coho', '030312': 'coho'}.get(hs[:6], 'atlantic' if hs[:6] in ('030214', '030313') else 'salmon')


def form(hs, desc):
    h, d = hs[:4], desc.upper()
    if h == '0305': return 'smoked/salted'
    if h == '0302': return 'fresh whole'
    if h == '0303': return 'frozen whole'
    if hs[:6] in ('030441', '030442'): return 'fresh fillets'
    if hs[:6] in ('030481', '030482'): return 'frozen fillets'
    return 'other'


def resources():
    out = {}
    for y in range(DEPUIS, int(time.strftime('%Y')) + 1):
        for slug in (f'registro-de-exportacion-{y}', f'registro-de-exportaciones-{y}', f'registros-de-exportacion-{y}'):
            try:
                r = requests.get(API, params={'id': slug}, headers=H, timeout=60)
                if not r.ok or not r.json().get('success'): continue
            except Exception:  # noqa: BLE001
                continue
            for x in r.json()['result']['resources']:
                m = re.fullmatch(r'(?i)exportaciones\s+(\w+)\s+(\d{4})', x['name'].strip())
                if m and m.group(1).lower() in MOIS:
                    out[int(m.group(2)) * 100 + MOIS.index(m.group(1).lower()) + 1] = {'url': x['url'], 'mod': x.get('last_modified') or x.get('created')}
            break
    return out


def read_month(url):
    d = tempfile.mkdtemp()
    fn = os.path.join(d, 'f' + os.path.splitext(url)[1])
    open(fn, 'wb').write(requests.get(url, headers=H, timeout=900).content)
    subprocess.run(['7z', 'x', '-y', '-o' + d + '/x', fn], capture_output=True, check=False)
    files = [os.path.join(a, f) for a, _, fs in os.walk(d + '/x') for f in fs if f.lower().endswith('.txt')]
    rows = []
    for p in files:
        with open(p, encoding='latin-1') as fh:
            for line in fh:
                x = line.rstrip('\n').split(';')
                if len(x) > C_FOB and SAL.match(x[C_HS].strip()): rows.append(x)
    subprocess.run(['rm', '-rf', d])
    return rows


CAL = re.compile(r'(?<![\d])(\d{1,2}(?:[.,]\d)?)\s*(?:-|/|A|TO)\s*(\d{1,2}(?:[.,]\d)?)\s*(LBS?|LIBRAS?|K(?:GS?|ILOS?)?)\b')
CALG = re.compile(r'(?<![\d.,])(\d{3,4})\s*(?:-|/|A|TO)\s*(\d{3,4})\s*(?:GRS?|GRAMOS|G)\b')
LB_BINS = ['1-2', '2-3', '3-4', '4-5', '5-6', '6+']   # classes de filets en livres (milieu de la classe declaree)
# producteur nomme dans la description (« AQUACHILE-F », « MULTI X S.A.-F » : F = fabricant) ; du plus precis au plus general
PRODUCERS = [('AQUACHILE', 'AquaChile'), ('MULTI X', 'Multi X'), ('MULTIX', 'Multi X'), ('MUTLI X', 'Multi X'), ('VENTISQUERO', 'Ventisqueros'), ('SALMONES PACIFIC', 'Pacific Star'), ('SOUTH WIND', 'South Wind'), ('SOUTH W IND', 'South Wind'), ('MULTIEXPORT', 'Multi X'), ('CERMAQ', 'Cermaq'), ('MOWI', 'Mowi'),
             ('MARINE HARVEST', 'Mowi'), ('CAMANCHACA', 'Camanchaca'), ('BLUMAR', 'Blumar'), ('LOS FIORDOS', 'Los Fiordos'), ('VENTISQUEROS', 'Ventisqueros'),
             ('AUSTRALIS', 'Australis'), ('NOVA AUSTRAL', 'Nova Austral'), ('SALMONES AUSTRAL', 'Salmones Austral'), ('YADRAN', 'Yadrán'), ('TRUSAL', 'Trusal'),
             ('INVERMAR', 'Invermar'), ('TORNAGALEONES', 'Tornagaleones'), ('SALMONES AYSEN', 'Salmones Aysén'), ('PACIFIC STAR', 'Pacific Star'),
             ('ANTARTICA', 'Salmones Antártica'), ('CALETA BAY', 'Caleta Bay'), ('COOKE', 'Cooke'), ('HUMBOLDT', 'Humboldt'), ('SOUTHERN CROSS', 'Southern Cross'),
             ('MARINE FARM', 'Marine Farm'), ('SALMONES DE CHILE', 'Salmones de Chile'), ('CHILOE', 'Cultivos Marinos Chiloé'), ('ACUIMAG', 'Acuimag'),
             ('CUPQUELAN', 'Cupquelan'), ('ICH-F', 'ICH'), ('ICH -F', 'ICH'), ('ACME', 'ACME'), ('AQUALINK', 'Aqualink'), ('SALMONOIL', 'Salmonoil'),
             ('PURE NATURE', 'Pure Nature'), ('OCEAN TRADE', 'Ocean Trade'), ('LA SIRENA', 'La Sirena'), (' NOVA ', 'Nova (brand)')]
FAB = re.compile(r'([A-Z][A-Z0-9 .&]{2,40}?)\s*-\s*F\b')


def producer(t1, t2):
    for k, v in PRODUCERS:
        if k in t1 or k.replace(' ', '') in t2.replace(' ', ''): return v
    m = FAB.search(t1)
    if m:
        w = re.sub(r'\b(S\.?A\.?|SPA|LTDA\.?|LIMITADA)\b', ' ', t1[:m.end() - 1].rstrip(' -')).replace('~', ' ').split()
        STOP = {'FILETE', 'FILETES', 'DE', 'DEL', 'SALMON', 'ATLANTICO', 'COHO', 'PLATEADO', 'O', 'TRUCHA', 'ARCOIRIS', 'FRESCO', 'CONGELADO', 'ENTERO', 'HON',
                'PORCIONES', 'CRUDO', 'IQF', 'HG', 'SIN', 'CABEZA', 'LOMO', 'LOMOS', 'PULPA', 'CARNE'}
        i = max([j for j, x in enumerate(w) if x.strip('.,') in STOP] + [-1])
        n = ' '.join(w[i + 1:][-4:]).strip(' .,')
        if len(n) >= 3: return n.title()
    return 'not stated'


def grade(t):
    if 'SUPER PREMIUM' in t or 'SUPERPREMIUM' in t: return 'super premium'
    if 'INDUSTRIAL' in t: return 'premium/industrial' if 'PREMIUM' in t else 'industrial'
    if re.search(r'PRODUCC?I[OÓ]N|PRODUCTION', t): return 'production'
    if 'STANDARD' in t or 'ESTANDAR' in t: return 'standard'
    if 'SUPERIOR' in t: return 'superior'
    if 'PREMIU' in t: return 'premium'
    m = re.search(r'GRAD[OE]\s*([A-C1-3])\b', t)
    if m: return 'grade ' + m.group(1)
    return 'not stated'


def trim(t):
    m = re.search(r'TRIM\s*-?\s*([A-E])\b', t)
    return m.group(1) if m else ('E' if 'SIN PIEL' in t and 'FILETE' in t else 'not stated')


def kind(t):
    if 'PORCION' in t: return 'portions'
    if 'PULPA' in t or 'BLOQUE' in t or 'CARNE' in t: return 'blocks, minced'
    if 'LOMO' in t: return 'loins'
    return 'fillets'
CLS = [2, 3, 4, 5, 6, 7]   # bornes des classes de calibre (kg)


def calibre(text):
    """Classe de poids ecrite dans la description (« CALIBRE 12-14 LB », « 6-7 KGS ») -> milieu en kg, ou None.
    Une seule valeur (« CAJA DE 10 KGS ») n'est pas un calibre : on exige un intervalle."""
    t = text.upper()
    for m in CAL.finditer(t):
        a, b = float(m.group(1).replace(',', '.')), float(m.group(2).replace(',', '.'))
        k = 0.4536 if m.group(3).startswith('L') else 1.0
        a, b = a * k, b * k
        if 0.3 <= a < b <= 13 and b - a <= 4: return (a + b) / 2
    for m in CALG.finditer(t):   # « 800-2200 GRS », « 1500-2000 GRAMOS » ; les portions (60-85 g) sont exclues par le minimum
        a, b = int(m.group(1)) / 1000, int(m.group(2)) / 1000
        if 0.3 <= a < b <= 4: return (a + b) / 2
    return None


def num(v):
    try: return float(v.strip().replace(',', '.') or 0)
    except ValueError: return 0.0


def aggregate(rows):
    agg = {'total': [0, 0], 'species_form': collections.defaultdict(lambda: [0, 0]), 'dest': collections.defaultdict(lambda: [0, 0]),
           'region': collections.defaultdict(lambda: [0, 0]), 'via': collections.defaultdict(lambda: [0, 0])}
    sizes = collections.defaultdict(lambda: {'kg': 0.0, 'kg_sized': 0.0, 'w': 0.0, 'hist': [0.0] * (len(CLS) + 1)})
    fil = collections.defaultdict(lambda: {'grade': collections.Counter(), 'trim': collections.Counter(), 'kind': collections.Counter(), 'lb': [0.0] * len(LB_BINS),
                                           'grade_usd': collections.Counter()})
    prod = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
    ex = {}
    for x in rows:
        kg, fob = num(x[C_QTY]), num(x[C_FOB])
        nom = x[C_NOM]; ref, _, desc = nom.partition('~'); ref = ref.strip()
        sp, fo = species(desc, x[C_HS].strip()), form(x[C_HS].strip(), desc)
        t1 = ' '.join(c.strip() for c in x[C_NOM:C_NOM + 6]).upper(); t2 = ''.join(x[C_NOM:C_NOM + 6]).upper()
        reg = REG.get(x[C_REG].strip(), 'other'); dest = x[C_DEST].strip().title(); via = VIA.get(x[C_VIA].strip(), 'other')
        for key, k in (('species_form', f'{sp}|{fo}'), ('dest', dest), ('region', reg), ('via', via)):
            agg[key][k][0] += kg; agg[key][k][1] += fob
        agg['total'][0] += kg; agg['total'][1] += fob
        if fo in ('fresh whole', 'frozen whole', 'fresh fillets', 'frozen fillets') and sp in ('atlantic', 'coho', 'trout'):
            z = sizes[f'{sp}|{fo}']; z['kg'] += kg; c = calibre(t1)
            if c: z['kg_sized'] += kg; z['w'] += c * kg; z['hist'][sum(c >= b for b in CLS)] += kg
            if 'fillets' in fo:
                f = fil[f'{sp}|{fo}']; g = grade(t1); f['grade'][g] += kg; f['grade_usd'][g] += fob; f['trim'][trim(t1)] += kg; f['kind'][kind(t1)] += kg
                if c: lb = c / 0.4536; f['lb'][min(len(LB_BINS) - 1, max(0, int(lb) - 1))] += kg
        pr = producer(t1, t2); prod[pr][f'{sp}|{fo}'][0] += kg; prod[pr][f'{sp}|{fo}'][1] += fob
        e = ex.setdefault(x[C_EXP].strip(), {'kg': 0, 'fob': 0, 'refs': collections.Counter(), 'sp': collections.Counter(), 'reg': collections.Counter(),
                                               'dest': collections.Counter(), 'comuna': collections.Counter(), 'prod': collections.Counter()})
        e['kg'] += kg; e['fob'] += fob; e['sp'][f'{sp}|{fo}'] += kg; e['reg'][reg] += kg; e['dest'][dest] += kg; e['comuna'][x[C_COM].strip()] += kg; e['prod'][pr] += kg
        if ref and ref.upper() != 'SIN-CODIGO' and len(ref) >= 3: e['refs'][ref] += 1
    r = lambda d: {k: [round(v[0] / 1000, 1), round(v[1] / 1000, 1)] for k, v in sorted(d.items(), key=lambda kv: -kv[1][0])}
    return {'t_kusd': [round(agg['total'][0] / 1000, 1), round(agg['total'][1] / 1000, 1)], 'species_form': r(agg['species_form']), 'dest': r(agg['dest']),
            'region': r(agg['region']), 'via': r(agg['via']),
            'sizes': {k: {'t': round(z['kg'] / 1000, 1), 't_sized': round(z['kg_sized'] / 1000, 1), 'mean_kg': round(z['w'] / z['kg_sized'], 2) if z['kg_sized'] else None,
                          'hist_t': [round(v / 1000, 1) for v in z['hist']]} for k, z in sizes.items()},
            'fillets': {k: {'grade': {g: [round(v / 1000, 1), round(f['grade_usd'][g] / 1000, 1)] for g, v in f['grade'].most_common()},
                            'trim': {g: round(v / 1000, 1) for g, v in f['trim'].most_common()}, 'kind': {g: round(v / 1000, 1) for g, v in f['kind'].most_common()},
                            'lb_t': [round(v / 1000, 1) for v in f['lb']]} for k, f in fil.items()},
            'producers': {n: {k: [round(v[0] / 1000, 1), round(v[1] / 1000, 1)] for k, v in sorted(d.items(), key=lambda kv: -kv[1][0]) if v[0] >= 2000}
                          for n, d in sorted(prod.items(), key=lambda kv: -sum(v[0] for v in kv[1].values())) if sum(v[0] for v in d.values()) >= 20000}}, ex


def link_exporters(months):
    """Chainage mois apres mois (pas de fusion transitive) : chaque exportateur-mois est rattache a la chaine la plus
    ressemblante des deux mois precedents — references produits communes surtout, puis commune, especes/formes,
    destinations, regions d'origine et volume. Une chaine = un exportateur suivi dans le temps."""
    import math
    def norm(c):
        t = sum(c.values()) or 1; return {k: v / t for k, v in c.items()}
    def cos(a, b):
        n = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) | set(b)); da = math.sqrt(sum(v * v for v in a.values())); db = math.sqrt(sum(v * v for v in b.values()))
        return n / (da * db) if da and db else 0
    F = {ym: {k: {'refs': {r for r in e['refs'] if len(r) >= 4}, 'kg': e['kg'], 'sp': norm(e['sp']), 'dest': norm(e['dest']), 'reg': norm(e['reg']),
                  'com': max(e['comuna'], key=e['comuna'].get) if e['comuna'] else ''} for k, e in ex.items() if e['kg'] > 0} for ym, ex in months.items()}
    def score(a, b):
        jr = len(a['refs'] & b['refs']) / len(a['refs'] | b['refs']) if a['refs'] and b['refs'] else 0
        s = 4 * jr + (0.6 if a['com'] == b['com'] else 0) + cos(a['sp'], b['sp']) + cos(a['dest'], b['dest']) + 0.5 * cos(a['reg'], b['reg']) \
            - 0.35 * abs(math.log(max(a['kg'], 1) / max(b['kg'], 1)))
        return s, jr
    order = sorted(F); chain, last, nid = {}, {}, 0
    for i, ym in enumerate(order):
        active = [c for c, (lm, _) in last.items() if order.index(lm) >= i - 2]
        cands = []
        for eid, fe in F[ym].items():
            for c in active:
                lm, le = last[c]; s, jr = score(fe, F[lm][le])
                if jr >= 0.15 or (s >= 3.3 and not (fe['refs'] and F[lm][le]['refs'] and jr == 0)): cands.append((s + 2 * jr, eid, c))
        ue, uc = set(), set()
        for s, eid, c in sorted(cands, reverse=True):
            if eid in ue or c in uc: continue
            chain[(ym, eid)] = c; last[c] = (ym, eid); ue.add(eid); uc.add(c)
        for eid in F[ym]:
            if eid not in ue: nid += 1; chain[(ym, eid)] = f'n{nid}'; last[f'n{nid}'] = (ym, eid)
    groups = collections.defaultdict(list)
    for node, c in chain.items(): groups[c].append(node)
    return groups


def main():
    t0 = time.time()
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    res = resources()
    print('mois publies :', len(res), 'dernier', max(res) if res else None)
    months_agg, months_ex = dict(old.get('months', {})), {}
    CACHE = OUT.replace('.json', '_cache.json')
    raw_cache = old.get('_exporters_raw') or (json.load(open(CACHE)) if os.path.exists(CACHE) else {})
    for ym in sorted(res):
        key = str(ym)
        if key in months_agg and key in raw_cache and old.get('mods', {}).get(key) == res[ym]['mod'] and ('--relire' not in sys.argv or 'producers' in months_agg[key]):
            months_ex[ym] = {k: {**v, 'refs': collections.Counter(v['refs']), 'sp': collections.Counter(v['sp']), 'reg': collections.Counter(v['reg']),
                                 'dest': collections.Counter(v['dest']), 'comuna': collections.Counter(v['comuna']), 'prod': collections.Counter(v.get('prod', {}))} for k, v in raw_cache[key].items()}
            continue
        try:
            rows = read_month(res[ym]['url'])
        except Exception as e:  # noqa: BLE001
            print(f'  {ym}: ERREUR {e}'); continue
        months_agg[key], months_ex[ym] = aggregate(rows)
        print(f"  {ym}: {len(rows)} lignes saumon, {months_agg[key]['t_kusd'][0]:,.0f} t, {len(months_ex[ym])} exportateurs")
    groups = link_exporters(months_ex)
    # identifiants stables : par taille totale
    G = []
    for nodes in groups.values():
        series = collections.defaultdict(lambda: [0, 0]); refs, sp, reg, dest, com, prd = (collections.Counter() for _ in range(6))
        for ym, eid in nodes:
            e = months_ex[ym][eid]; series[str(ym)][0] += e['kg']; series[str(ym)][1] += e['fob']
            refs.update(e['refs']); sp.update(e['sp']); reg.update(e['reg']); dest.update(e['dest']); com.update(e['comuna']); prd.update(e.get('prod', {}))
        tot = sum(v[0] for v in series.values())
        G.append({'kg': tot, 'months': {k: [round(v[0] / 1000, 1), round(v[1] / 1000, 1)] for k, v in sorted(series.items())},
                  'refs': [r for r, _ in refs.most_common(8)], 'mix': {k: round(100 * v / tot, 1) for k, v in sp.most_common(6)} if tot else {},
                  'regions': {k: round(100 * v / tot, 1) for k, v in reg.most_common(3)} if tot else {},
                  'dest': {k: round(100 * v / tot, 1) for k, v in dest.most_common(5)} if tot else {}, 'comuna': com.most_common(1)[0][0] if com else '',
                  'producers': {k: round(100 * v / tot, 1) for k, v in prd.most_common(3)} if tot else {}})
    G.sort(key=lambda g: -g['kg'])
    for i, g in enumerate(G): g['id'] = f'EXP-{i + 1:03d}'; g['t'] = round(g.pop('kg') / 1000)
    out = {'meta': {'built': time.strftime('%Y-%m-%d'), 'last': max(res) if res else None, 'first': min(res) if res else None,
                    'source': 'Servicio Nacional de Aduanas, export declarations (DUS), open data on datos.gob.cl — anonymised: no exporter name',
                    'url': 'https://datos.gob.cl/organization/servicio_nacional_de_aduanas', 'unit': 'tonnes net product weight, thousand USD FOB',
                    'linking': 'exporters are renumbered every month; each one is chained from month to month by its own product reference codes, then by its town, species and forms, destinations, regions of origin and size. A chain may break when an exporter changes its references: read it as a likely continuity, not a certainty.',
                    'size_classes_kg': CLS, 'sizes_note': 'weight class written in the product description (calibre), mid-point, converted from lb when needed; whole fish are mostly gutted head-on (HON) weight; fillets are fillet weight',
                    'groups': len(G), 'linked_share_pct': round(100 * sum(g['t'] for g in G if len(g['months']) > 1) / max(1, sum(g['t'] for g in G)), 1)},
           'months': dict(sorted(months_agg.items())), 'mods': {str(k): v['mod'] for k, v in res.items()}, 'exporters': [g for g in G if g['t'] >= 50],
           }
    raw = {str(ym): {k: {**v, 'refs': dict(v['refs'].most_common(30))} for k, v in ex.items()} for ym, ex in months_ex.items()}
    json.dump(raw, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))   # cache de chainage, lu par le script seulement
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f"ecrit {OUT} ({os.path.getsize(OUT) // 1024} ko) : {len(months_agg)} mois, {len(G)} groupes d'exportateurs, "
          f"{out['meta']['linked_share_pct']} % du volume relie sur plusieurs mois, en {time.time() - t0:.0f} s")


if __name__ == '__main__':
    main()
