"""Wellboats et navires de service au Chili (Global Fishing Watch, AIS) : escales 2023 -> aujourd'hui.

Source : API Global Fishing Watch v3, jeu 'public-global-port-visits-events' (escales detectees par GFW a
partir de l'AIS ; les 'anchorages' incluent les usines, les ports et les points d'arret pres des fermes).
On garde les navires classes 'carrier' et 'cargo' par GFW dans la zone salmonicole (41-55.5 S).
Sortie : data/chile_wellboats_raw.json (escales compactes + fiche des navires). Les mois anciens sont
gardes en cache, seuls les 2 derniers mois sont relus.
"""
import os, re, json, math, time, datetime as dt, requests
from collections import Counter, defaultdict

OUT = 'data/chile_wellboats_raw.json'
B = 'https://gateway.api.globalfishingwatch.org/v3'
PV = 'public-global-port-visits-events:latest'
POLY = {'type': 'Polygon', 'coordinates': [[[-75.8, -55.5], [-69.5, -55.5], [-69.5, -40.9], [-75.8, -40.9], [-75.8, -55.5]]]}
START = (2023, 1)


def token():
    for k in ('GFW_TOKEN', 'GGLOBALFISHING_KEY', 'GLOBALFISHING_KEY', 'S_GGLOBALFISHING_KEY'):
        if os.environ.get(k):
            return os.environ[k].strip()
    raise SystemExit('pas de cle GFW')


H = {'Authorization': f'Bearer {token()}'}


def req(method, path, **kw):
    for i in range(5):
        try:
            r = requests.request(method, B + path, headers=H, timeout=180, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(10 * (i + 1)); continue
            return r
        except requests.RequestException:
            time.sleep(10 * (i + 1))
    return r


def month_events(y, m, vt):
    a = dt.date(y, m, 1); b = (a + dt.timedelta(days=32)).replace(day=1)
    out, off = [], 0
    while True:
        r = req('POST', '/events', params={'limit': 500, 'offset': off},
                json={'datasets': [PV], 'startDate': a.isoformat(), 'endDate': b.isoformat(), 'geometry': POLY, 'vesselTypes': [vt]})
        if not r.ok:
            raise RuntimeError(f'{y}-{m} {vt} HTTP {r.status_code} {r.text[:200]}')
        j = r.json(); out += j.get('entries', [])
        if not j.get('entries') or not j.get('nextOffset'):
            return out
        off = j['nextOffset']


def main():
    old = json.load(open(OUT)) if os.path.exists(OUT) else {'months': {}, 'vessels': {}}
    today = dt.date.today()
    keep_until = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)  # mois precedent relu aussi
    months, vessels = old.get('months', {}), old.get('vessels', {})
    y, m = START
    while (y, m) <= (today.year, today.month):
        key = f'{y}-{m:02d}'
        if key in months and dt.date(y, m, 1) < keep_until:
            pass
        else:
            rows = []
            for vt in ('CARRIER', 'CARGO'):
                for e in month_events(y, m, vt):
                    v = e.get('vessel') or {}; pv = e.get('port_visit') or {}
                    an = pv.get('intermediateAnchorage') or pv.get('startAnchorage') or {}
                    p = e.get('position') or {}
                    if e.get('start', '')[:7] != key:
                        continue  # evite les doublons entre mois
                    vessels.setdefault(v.get('id'), {'name': v.get('name'), 'ssvid': v.get('ssvid'), 'flag': v.get('flag'), 'type': v.get('type')})
                    rows.append([v.get('id'), e.get('start', '')[:16], e.get('end', '')[:16], round(p.get('lat', 0), 3), round(p.get('lon', 0), 3),
                                 an.get('name'), an.get('id'), round(pv.get('durationHrs') or 0, 1)])
            months[key] = rows
            print(key, len(rows), 'escales')
        m += 1
        if m == 13:
            y, m = y + 1, 1
    # fiche registre (tonnage, longueur) pour les navires qui n'en ont pas
    for vid, v in vessels.items():
        if 'gt' in v or not vid:
            continue
        r = req('GET', f'/vessels/{vid}', params={'dataset': 'public-global-vessel-identity:latest'})
        gt = ln = imo = built = None
        if r is not None and r.ok:
            j = r.json()
            for ri in j.get('registryInfo') or []:
                gt = gt or ri.get('tonnageGt'); ln = ln or ri.get('lengthM'); imo = imo or ri.get('imo')
        v.update(gt=gt, len=ln, imo=imo)
    json.dump({'meta': {'source': 'Global Fishing Watch API v3, public-global-port-visits-events (AIS)', 'url': 'https://globalfishingwatch.org/our-apis/',
                        'built': today.isoformat(), 'fields': ['vessel_id', 'start', 'end', 'lat', 'lon', 'anchorage', 'anchorage_id', 'hours']},
               'vessels': vessels, 'months': months}, open(OUT, 'w'), separators=(',', ':'))
    print('navires', len(vessels), 'escales', sum(len(x) for x in months.values()))
    summarize()


WBRE = re.compile(r'^(PATAGON|GRIP |ORCA |RONIA|RONJA|SEI|INTER |RIO DULCE|CACIQUE|ALCANTARA|LOKI|FORSETI|VALI|TYR|SAGA|BRUDANES|BUCALEMU|DON LUIS|FAEROY|DONA CLAUDINA)')
SERIES = (('PATAGON', 'Patagon series'), ('ORCA', 'Naviera Orca'), ('GRIP', 'Grip (Aquaship)'), ('RONIA', 'Ronja (Sølvtrans)'), ('RONJA', 'Ronja (Sølvtrans)'),
          ('SEI', 'Sei- series'), ('INTER', 'Inter series'), ('RIO DULCE', 'Rio Dulce'))


def region(lat):
    return 'LL' if lat > -43.75 else ('AY' if lat > -49 else 'MA')


def fit(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def corr(a, b):
    n = len(a); ma = sum(a) / n; mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((y - mb) ** 2 for y in b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def summarize():
    """data/chile_wellboats.json : ce que la page affiche (escales par region, pouls hebdomadaire, estimation de la
    recolte des usines de Los Lagos, points les plus frequentes, flotte)."""
    d = json.load(open(OUT)); V = d['vessels']
    wb = {k for k, v in V.items() if v.get('flag') == 'CHL' and (v.get('type') == 'carrier' or WBRE.match(v.get('name') or ''))}
    ev = sorted([e for m in d['months'].values() for e in m if e[0] in wb], key=lambda e: e[1])
    last = max(e[2] for e in ev); lastd = dt.datetime.fromisoformat(last)
    cur_month = last[:7]
    mon = {r: Counter() for r in ('LL', 'AY', 'MA')}; wk = {r: Counter() for r in ('LL', 'AY', 'MA')}
    for e in ev:
        r = region(e[3]); mon[r][e[1][:7]] += 1
        y, w, _ = dt.date.fromisoformat(e[1][:10]).isocalendar(); wk[r][f'{y}-W{w:02d}'] += 1
    R = json.load(open('data/chile_regional.json'))
    LL = {k: sum(v['t'].values()) for k, v in R['los_lagos'].items()}
    MA = {k: sum(v['t'].values()) for k, v in R['magallanes'].items()}
    ks = sorted(k for k in LL if mon['LL'][k]); xs = [mon['LL'][k] for k in ks]; ys = [LL[k] for k in ks]
    a, b = fit(xs, ys)
    # estimation : moyenne de l'ajustement et de l'evolution sur un an ; erreur testee mois par mois a l'aveugle
    errs = []
    for i, k in enumerate(ks):
        ly = f'{int(k[:4]) - 1}{k[4:]}'
        if ly not in LL or not mon['LL'][ly]:
            continue
        a2, b2 = fit(xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:])
        e = ((a2 + b2 * xs[i]) + LL[ly] * xs[i] / mon['LL'][ly]) / 2
        errs.append(abs(e / ys[i] - 1))
    est = {}
    for k in sorted(mon['LL']):
        if k in LL or k >= cur_month or k < max(LL):
            continue
        ly = f'{int(k[:4]) - 1}{k[4:]}'
        g = a + b * mon['LL'][k]
        est[k] = round((g + LL[ly] * mon['LL'][k] / mon['LL'][ly]) / 2) if ly in LL and mon['LL'][ly] else round(g)
    km = sorted(k for k in MA if mon['MA'][k])
    # points d'escale : 30 derniers jours contre la meme fenetre un an plus tot, concessions voisines
    S = [s for s in json.load(open('data/chile_sites.json'))['sites'] if s['lat'] < -40.5]
    def holders(la, lo, km_=6):
        c = Counter()
        for s in S:
            if abs(s['lat'] - la) > 0.1:
                continue
            if math.hypot((s['lon'] - lo) * 111 * math.cos(math.radians(la)), (s['lat'] - la) * 111) < km_ and s['h'] != 'Other':
                c[s['h']] += 1
        return [h for h, _ in c.most_common(3)]
    cur, prv, pos = Counter(), Counter(), {}
    for e in ev:
        age = (lastd - dt.datetime.fromisoformat(e[1])).days
        if age < 30: cur[e[5]] += 1
        elif 365 <= age < 395: prv[e[5]] += 1
        pos[e[5]] = (e[3], e[4])
    hot = [{'a': x, 'reg': region(pos[x][0]), 'cur': cur[x], 'prv': prv[x], 'lat': pos[x][0], 'lon': pos[x][1], 'near': holders(*pos[x])}
           for x in set(cur) | set(prv) if x and cur[x] + prv[x] >= 8]
    hot.sort(key=lambda h: -(h['cur'] + h['prv']))
    # flotte par serie de noms
    fl = defaultdict(lambda: {'boats': [], 'active': 0, 'cur': 0, 'prv': 0})
    by = defaultdict(list)
    for e in ev: by[e[0]].append(e)
    for vid, es in by.items():
        n = V[vid].get('name') or V[vid].get('ssvid')
        ser = next((lab for p, lab in SERIES if (n or '').startswith(p)), 'Others')
        c = sum(1 for e in es if (lastd - dt.datetime.fromisoformat(e[1])).days < 30)
        p = sum(1 for e in es if 365 <= (lastd - dt.datetime.fromisoformat(e[1])).days < 395)
        f = fl[ser]; f['boats'].append([n, c]); f['active'] += c > 0; f['cur'] += c; f['prv'] += p
    for f in fl.values(): f['boats'].sort(key=lambda x: -x[1])
    out = {'meta': {'built': dt.date.today().isoformat(), 'last': last, 'boats': len(by), 'source': d['meta']['source'],
                    'note': 'Wellboat stops (port visits detected from AIS by Global Fishing Watch) in the Chilean salmon area, 41-55.5 S.'},
           'stops': {r: dict(sorted(c.items())) for r, c in mon.items()}, 'weeks': {r: dict(sorted(c.items())) for r, c in wk.items()},
           'll_official': LL, 'll_estimate': est,
           'll_fit': {'r': round(corr(xs, ys), 3), 'n': len(ks), 'mape': round(sum(errs) / len(errs), 3) if errs else None, 'n_test': len(errs)},
           'ma_official': MA, 'ma_fit': {'r': round(corr([mon['MA'][k] for k in km], [MA[k] for k in km]), 3), 'n': len(km)} if len(km) > 3 else None,
           'hot': hot[:25], 'fleet': dict(sorted(fl.items(), key=lambda x: -x[1]['cur']))}
    json.dump(out, open('data/chile_wellboats.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print('resume ecrit : estimation', est, 'r', out['ll_fit'])


if __name__ == '__main__':
    import sys
    summarize() if '--resume' in sys.argv else main()
