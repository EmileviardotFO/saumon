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
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'chlorophyll.json')
SERVEURS = ['https://coastwatch.noaa.gov/erddap', 'https://polarwatch.noaa.gov/erddap', 'https://oceanwatch.pifsc.noaa.gov/erddap', 'https://erddap.marine.ie/erddap']
ERD = SERVEURS[0]
BASE = {}
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
        except urllib.error.HTTPError as e:
            body = re.sub(r'<[^>]+>|\s+', ' ', e.read()[:4000].decode('utf-8', 'replace'))
            m = re.search(r'message="?([^"]{0,200})', body)
            last = f'{e.code} {m.group(1) if m else body[-200:]}'
            if e.code in (400, 404, 413): break
            time.sleep(4 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f'{last} <- {url[-90:]}')


def catalogue(ERD):
    """Jeux de donnees chlorophylle mondiaux du catalogue, du plus utile au moins utile."""
    raw = http(ERD + '/search/index.json?' + urllib.parse.urlencode({'page': 1, 'itemsPerPage': 300, 'searchFor': 'chlorophyll VIIRS'}))
    t = json.loads(raw)['table']; c = t['columnNames']; rows = [dict(zip(c, r)) for r in t['rows']]
    ok = [r for r in rows if r.get('griddap') and re.search(r'chl', r['Dataset ID'], re.I)]
    def rang(r):
        i, ti = r['Dataset ID'], r.get('Title', '')
        return (0 if re.search(r'DINEOF', i + ti, re.I) and re.search(r'daily', i + ti, re.I) else 1 if re.search(r'8.?day', i + ti, re.I) else 2 if re.search(r'daily', i + ti, re.I) else 3,
                0 if re.search(r'NPPN20|N20|multi', i, re.I) else 1, 0 if re.search(r'9km|4km', i + ti, re.I) else 1)
    for r in ok: BASE[r['Dataset ID']] = r['griddap']
    ok.sort(key=rang)
    print(ERD, 'catalogue chlorophylle :', [r['Dataset ID'] for r in ok[:8]], flush=True)
    return ok


def axes(did):
    raw = json.loads(http(BASE[did].replace('/griddap/', '/info/') + '/index.json'))
    t = raw['table']; dims, var = [], None
    for row in t['rows']:
        if row[0] == 'dimension': dims.append(row[1])
        if row[0] == 'variable' and re.search(r'chl', row[1], re.I) and var is None: var = row[1]
    return dims, var


def serie(did, dims, var, la, lo, debut, fin='last'):
    sel = []
    for d in dims:
        if d == 'time': sel.append(f'[({debut}T00:00:00Z):1:(' + (fin if fin == 'last' else fin + 'T00:00:00Z') + ')]')
        elif d in ('latitude', 'lat'): sel.append(f'[({la})]')
        elif d in ('longitude', 'lon'): sel.append(f'[({lo})]')
        else: sel.append('[0]')
    # requete entierement encodee (certains frontaux renvoient 404 sur les crochets bruts)
    base = BASE[did]
    q = base + '.csv?' + urllib.parse.quote(var + ''.join(sel), safe='')
    raw = http(q, timeout=180).decode('utf-8', 'replace').splitlines()[2:]
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
    pts, err, used = [], [], None
    essai = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    for srv in SERVEURS:
        try:
            cands = catalogue(srv)
        except Exception as e:  # noqa: BLE001
            err.append(f'{srv}: catalogue {str(e)[:120]}'); print(err[-1], flush=True); continue
        for c in cands[:6]:
            did = c['Dataset ID']
            try:
                dims, var = axes(did)
                if not var or 'time' not in dims: continue
                # essai sur la mer de Chiloe, 20 derniers jours : le serveur sert-il vraiment les donnees ?
                serie(did, dims, var, -42.6, -73.25, essai)
                used = (did, c.get('Title', ''), dims, var); break
            except Exception as e:  # noqa: BLE001
                msg = str(e)[:160].replace('\n', ' ')
                print(f'  {did}: {msg}', flush=True)
                if 'No data' in msg or 'nothing' in msg.lower():
                    used = (did, c.get('Title', ''), dims, var); break
        if used: break
    if not used:
        print('chlorophylle : aucun jeu utilisable', err); return
    did, title, dims, var = used
    print('jeu retenu :', did, '|', title, dims, var, BASE.get(did), flush=True)
    # le serveur refuse les longues series (404) : on lit les 60 derniers jours, puis la meme fenetre de 14 jours
    # pour chacune des 6 annees precedentes
    debut = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    for b, bn, pid, lab, la, lo in POINTS:
        try:
            s, pe, cell = {}, '', None
            for a, o in DEC:
                try:
                    s = serie(did, dims, var, round(la + a, 3), round(lo + o, 3), debut)
                except Exception as e:  # noqa: BLE001
                    pe = str(e)[:300]; s = {}
                if len(s) >= 4: cell = (round(la + a, 3), round(lo + o, 3)); break
                time.sleep(.5)
            if not cell: raise RuntimeError(pe or 'pas de donnees recentes (nuages ou maille terrestre)')
            jours = sorted(s); last = jours[-1]; l0 = (dt.date.fromisoformat(last) - dt.timedelta(days=13)).isoformat()
            rec = [s[d] for d in jours if d >= l0]
            hist = []
            for y in range(1, 7):
                a0 = (dt.date.fromisoformat(l0) - dt.timedelta(days=365 * y)).isoformat(); a1 = (dt.date.fromisoformat(last) - dt.timedelta(days=365 * y)).isoformat()
                try:
                    v = list(serie(did, dims, var, cell[0], cell[1], a0, a1).values())
                except Exception:  # noqa: BLE001
                    v = []
                if len(v) >= 2: hist.append(S.median(v))
            now = S.median(rec) if rec else None
            norm = S.median(hist) if len(hist) >= 2 else None
            # fiabilite : lecture recente (< 21 jours), assez de jours clairs, au moins 4 annees de reference, pas d'eau turbide
            age = (dt.date.today() - dt.date.fromisoformat(last)).days
            why = ('no clear-sky image for ' + str(age) + ' days (clouds or polar night)' if age > 21 else
                   'only ' + str(len(hist)) + ' reference years' if len(hist) < 3 or (len(hist) == 3 and not (now and now >= 2 * max(hist))) else
                   'too few clear days' if len(rec) < 4 else
                   'very high value, likely coastal turbidity' if now and now > 20 else '')
            note = 'only 3 reference years, but at least twice the highest of them' if not why and len(hist) == 3 else ''
            pts.append({'reliable': not why, 'why': why, 'caveat': note, 'hist_max': round(max(hist), 2) if hist else None, 'basin': b, 'basin_name': bn, 'id': pid, 'label': lab, 'lat': cell[0], 'lon': cell[1], 'n_recent': len(rec), 'last': last, 'period': f'{l0} to {last}', 'now': round(now, 2) if now else None,
                        'normal': round(norm, 2) if norm else None, 'years': len(hist), 'anom_pct': round(100 * (now / norm - 1)) if now and norm else None,
                        'recent': [[d, round(s[d], 2)] for d in jours[-60:]]})
            print(f'  {pid:14s} {now} mg/m3, normale {norm}, ecart {pts[-1]["anom_pct"]} %', flush=True)
        except Exception as e:  # noqa: BLE001
            err.append(f'{pid}: {str(e)[:300]}')
            o = next((p for p in ancien.get('points', []) if p['id'] == pid), None)
            if o: pts.append(o)
    if not pts:
        print('chlorophylle : rien de lu', err); return
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'), 'dataset': did, 'title': title,
        'source': 'NOAA ERDDAP (' + BASE[did].split('/erddap')[0] + '), VIIRS ocean colour chlorophyll-a (public domain)', 'unit': 'mg/m3',
        'note': 'Chlorophyll measures the amount of algae, not their toxicity. A level far above the same weeks of past years is a sign to watch, not a harmful bloom.', 'errors': err},
        'points': pts}, ensure_ascii=False, separators=(',', ':')))
    print(f'data/chlorophyll.json : {len(pts)} points, {len(err)} erreurs')


if __name__ == '__main__':
    main()
