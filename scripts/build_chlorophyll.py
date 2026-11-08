#!/usr/bin/env python3
"""
Chlorophylle a la surface (quantite d'algues), vue par satellite, pres des fermes : alerte precoce de floraison.

    python3 scripts/build_chlorophyll.py      -> data/chlorophyll.json

Source : NOAA CoastWatch ERDDAP (coastwatch.noaa.gov), chlorophylle-a des satellites VIIRS (SNPP / NOAA-20), produit
global sans trous (DINEOF) quand il existe, sinon composite 8 jours ; donnees du gouvernement americain, domaine public.
Le jeu de donnees est cherche dans le catalogue a chaque passage (les identifiants changent avec les versions).

Lecture : la chlorophylle mesure la QUANTITE d'algues, pas leur toxicite. Un niveau tres au-dessus de la normale des memes
semaines est un signal a surveiller (eau riche, calme, ensoleillee), pas la preuve d'un bloom nocif.
"""
import datetime as dt
import io
import json
import os
import re
import statistics as S
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'chlorophyll.json')
ERD = 'https://coastwatch.noaa.gov/erddap'
UA = {'User-Agent': 'salmon-outlook (chlorophyll)'}
# points en mer interieure / fjords exposes aux blooms (2016 Reloncavi-Chiloe, 2021 Comau, 2019 Nord-Norge)
POINTS = [
    ('CL', 'Chile', 'cl_reloncavi', 'Chile · Reloncaví Sound', -41.70, -72.85),
    ('CL', 'Chile', 'cl_chiloe_in', 'Chile · Chiloé inner sea', -42.60, -73.25),
    ('CL', 'Chile', 'cl_aysen', 'Chile · Aysén fjords', -45.40, -73.80),
    ('CL', 'Chile', 'cl_magallanes', 'Chile · Magallanes', -52.80, -72.80),
    ('NO', 'Norway', 'no_west', 'Norway · west coast (zone 3–4)', 60.60, 4.70),
    ('NO', 'Norway', 'no_mid', 'Norway · Frøya–Hitra (zone 6)', 63.90, 8.40),
    ('NO', 'Norway', 'no_north', 'Norway · Vestfjorden (zone 9)', 68.10, 14.40),
    ('NO', 'Norway', 'no_troms', 'Norway · Troms (zone 10–11)', 69.80, 18.60),
    ('GB', 'Scotland', 'gb_west', 'Scotland · West Highlands', 57.30, -6.40),
    ('FO', 'Faroe Islands', 'fo', 'Faroe Islands', 62.00, -6.60),
    ('AU', 'Tasmania', 'au_storm', 'Tasmania · Storm Bay', -43.20, 147.45),
]
DEC = [(0, 0), (0, -.1), (0, .1), (.1, 0), (-.1, 0), (0, -.2), (0, .2), (.2, 0), (-.2, 0), (0, -.35), (0, .35), (.35, 0), (-.35, 0)]


def http(url, timeout=120):
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if '404' in str(e) or '400' in str(e): break
            time.sleep(4 * (i + 1))
    raise RuntimeError(f'{url[:150]} : {last}')


def catalogue():
    """Jeux de donnees chlorophylle mondiaux du catalogue, du plus utile au moins utile."""
    raw = http(ERD + '/search/index.json?' + urllib.parse.urlencode({'page': 1, 'itemsPerPage': 300, 'searchFor': 'chlorophyll global VIIRS'}))
    t = json.loads(raw)['table']; c = t['columnNames']; rows = [dict(zip(c, r)) for r in t['rows']]
    ok = [r for r in rows if r.get('griddap') and re.search(r'chl', r['Dataset ID'], re.I)]
    def rang(r):
        i, ti = r['Dataset ID'], r.get('Title', '')
        return (0 if re.search(r'DINEOF', i + ti, re.I) and re.search(r'daily', i + ti, re.I) else 1 if re.search(r'8.?day', i + ti, re.I) else 2 if re.search(r'daily', i + ti, re.I) else 3,
                0 if re.search(r'NPPN20|N20|multi', i, re.I) else 1, 0 if re.search(r'9km|4km', i + ti, re.I) else 1)
    ok.sort(key=rang)
    print('catalogue chlorophylle :', [r['Dataset ID'] for r in ok[:12]], flush=True)
    return ok


def axes(did):
    raw = json.loads(http(f'{ERD}/info/{did}/index.json'))
    t = raw['table']; dims, var = [], None
    for row in t['rows']:
        if row[0] == 'dimension': dims.append(row[1])
        if row[0] == 'variable' and re.search(r'chl', row[1], re.I) and var is None: var = row[1]
    return dims, var


def serie(did, dims, var, la, lo, debut):
    sel = []
    for d in dims:
        if d == 'time': sel.append(f'[({debut}T00:00:00Z):1:(last)]')
        elif d in ('latitude', 'lat'): sel.append(f'[({la})]')
        elif d in ('longitude', 'lon'): sel.append(f'[({lo})]')
        else: sel.append('[0]')
    q = f'{ERD}/griddap/{did}.csv?{var}' + ''.join(sel)
    raw = http(urllib.parse.quote(q, safe=':/?[]():,.=-'), timeout=180).decode('utf-8', 'replace').splitlines()[2:]
    out = {}
    for l in raw:
        c = l.split(',')
        try:
            v = float(c[-1])
            if v > 0 and v < 200: out[c[0][:10]] = v
        except ValueError: pass
    return out


def main():
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    try:
        cands = catalogue()
    except Exception as e:  # noqa: BLE001
        print('chlorophylle : catalogue illisible,', str(e)[:200]); return
    pts, err, used = [], [], None
    for c in cands[:4]:
        try:
            dims, var = axes(c['Dataset ID'])
            if not var or 'time' not in dims: continue
            used = (c['Dataset ID'], c.get('Title', ''), dims, var); break
        except Exception as e:  # noqa: BLE001
            err.append(f'{c["Dataset ID"]}: {str(e)[:100]}')
    if not used:
        print('chlorophylle : aucun jeu utilisable', err); return
    did, title, dims, var = used
    print('jeu retenu :', did, '|', title, dims, var, flush=True)
    debut = (dt.date.today() - dt.timedelta(days=365 * 6)).isoformat()
    for b, bn, pid, lab, la, lo in POINTS:
        try:
            s = {}
            for a, o in DEC:
                s = serie(did, dims, var, round(la + a, 3), round(lo + o, 3), debut)
                if len(s) > 30: break
                time.sleep(1)
            if len(s) < 30: raise RuntimeError('pas de donnees (maille terrestre ou nuages)')
            jours = sorted(s); last = jours[-1]; l0 = (dt.date.fromisoformat(last) - dt.timedelta(days=13)).isoformat()
            rec = [s[d] for d in jours if d >= l0]
            # normale : meme fenetre de 14 jours les annees precedentes (moyenne des valeurs disponibles)
            hist = []
            for y in range(1, 7):
                a0 = (dt.date.fromisoformat(l0) - dt.timedelta(days=365 * y)).isoformat(); a1 = (dt.date.fromisoformat(last) - dt.timedelta(days=365 * y)).isoformat()
                v = [s[d] for d in jours if a0 <= d <= a1]
                if v: hist.append(S.median(v))
            now = S.median(rec) if rec else None
            norm = S.median(hist) if len(hist) >= 2 else None
            pts.append({'basin': b, 'basin_name': bn, 'id': pid, 'label': lab, 'lat': la, 'lon': lo, 'last': last, 'period': f'{l0} to {last}', 'now': round(now, 2) if now else None,
                        'normal': round(norm, 2) if norm else None, 'years': len(hist), 'anom_pct': round(100 * (now / norm - 1)) if now and norm else None,
                        'recent': [[d, round(s[d], 2)] for d in jours[-60:]]})
            print(f'  {pid:14s} {now} mg/m3, normale {norm}, ecart {pts[-1]["anom_pct"]} %', flush=True)
        except Exception as e:  # noqa: BLE001
            err.append(f'{pid}: {str(e)[:120]}')
            o = next((p for p in ancien.get('points', []) if p['id'] == pid), None)
            if o: pts.append(o)
    if not pts:
        print('chlorophylle : rien de lu', err); return
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'), 'dataset': did, 'title': title,
        'source': 'NOAA CoastWatch ERDDAP, VIIRS ocean colour chlorophyll-a (public domain)', 'unit': 'mg/m3',
        'note': 'Chlorophyll measures the amount of algae, not their toxicity. A level far above the same weeks of past years is a sign to watch, not a harmful bloom.', 'errors': err},
        'points': pts}, ensure_ascii=False, separators=(',', ':')))
    print(f'data/chlorophyll.json : {len(pts)} points, {len(err)} erreurs')


if __name__ == '__main__':
    main()
