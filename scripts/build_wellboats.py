#!/usr/bin/env python3
"""
data/wellboats.json : passages des bateaux de transport de poisson vivant (wellboats) et des bateaux d'abattage
sur les fermes norvegiennes, semaine par semaine, et alertes quand l'activite sort de l'ordinaire.

Source : API fiskehelse de BarentsWatch (meme client que les poux, scope "api") :
  /v1/geodata/fishhealth/vessels                        navires suivis, avec les drapeaux isWellboat / isSlaughterBoat
  /v1/geodata/fishhealth/locality/{no}/vessel/{annee}   passages de navires a chaque lokalitet, semaine par semaine
  /v1/geodata/fishhealth/vesselslatestpositions         derniere position de chaque navire suivi
BarentsWatch detecte un passage quand un navire reste dans l'emprise de la ferme (AIS de Kystverket).

Les fermes viennent du registre deja lu (data.json -> bw_register : zone de production et titulaire par lokalitet).
L'annee precedente est gardee dans data/wellboats_hist.json (relue une fois par mois), l'annee en cours chaque jour.

    BW_CLIENT_ID=... BW_CLIENT_SECRET=... python3 scripts/build_wellboats.py [--annee-precedente]
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import statistics
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'wellboats.json')
HIST = os.path.join(ROOT, 'data', 'wellboats_hist.json')
API = 'https://www.barentswatch.no/bwapi'
H = {'User-Agent': 'salmon-dashboard/1.0 (github.com/EmileviardotFO/saumon)'}


def token():
    r = requests.post('https://id.barentswatch.no/connect/token', data={'client_id': os.environ['BW_CLIENT_ID'], 'client_secret': os.environ['BW_CLIENT_SECRET'],
                                                                         'scope': 'api', 'grant_type': 'client_credentials'}, timeout=60)
    r.raise_for_status()
    return r.json()['access_token']


def get(path, T, tries=4):
    for i in range(tries):
        try:
            r = requests.get(API + path, headers={**H, 'Authorization': 'Bearer ' + T}, timeout=90)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 * (i + 1)); continue
            if r.status_code == 204:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    return None


def year_visits(locs, year, T, kinds):
    """passages des wellboats et bateaux d'abattage, pour toutes les fermes, sur une annee"""
    out = []

    def one(no):
        js = get(f'/v1/geodata/fishhealth/locality/{no}/vessel/{year}', T) or []
        res = []
        for w in js:
            for v in w.get('vesselVisits') or []:
                k = kinds.get(v.get('mmsi'))
                if not k and not (v.get('isWellboat') or v.get('isSlaughterBoat')):
                    continue
                k = k or ('S' if v.get('isSlaughterBoat') else 'W')
                a, b = v.get('startTime'), v.get('stopTime')
                try:
                    hrs = (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600
                except Exception:
                    hrs = None
                res.append([int(no), int(w['year']), int(w['week']), int(v['mmsi']), k, a[:16] if a else None, round(hrs, 1) if hrs is not None else None])
        return res
    with cf.ThreadPoolExecutor(8) as ex:
        for r in ex.map(one, locs):
            out += r
    return out


def main():
    T = token()
    V = get('/v1/geodata/fishhealth/vessels', T) or []
    kinds = {v['mmsi']: ('S' if v.get('isSlaughterBoat') else 'W') for v in V if v.get('isWellboat') or v.get('isSlaughterBoat')}
    names = {v['mmsi']: v.get('vesselName') for v in V if v['mmsi'] in kinds}
    reg = (json.load(open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8')).get('bw_register') or {})
    site_po, site_org, site_name, site_cap = reg.get('site_po', {}), reg.get('site_org', {}), reg.get('site_name', {}), reg.get('site_cap', {})
    locs = sorted(site_po, key=int)
    print(f'{len(kinds)} wellboats / bateaux d\'abattage ; {len(locs)} fermes de saumon')
    now = dt.date.today(); Y = now.isocalendar()[0]
    hist = json.load(open(HIST, encoding='utf-8')) if os.path.exists(HIST) else {}
    if '--annee-precedente' in sys.argv or str(Y - 1) not in hist.get('years', {}):
        t0 = time.time(); prev = year_visits(locs, Y - 1, T, kinds)
        hist.setdefault('years', {})[str(Y - 1)] = prev; hist['built'] = now.isoformat()
        json.dump(hist, open(HIST, 'w', encoding='utf-8'), separators=(',', ':'))
        print(f'  {Y - 1} : {len(prev)} passages en {time.time() - t0:.0f} s')
    t0 = time.time(); cur = year_visits(locs, Y, T, kinds)
    print(f'  {Y} : {len(cur)} passages en {time.time() - t0:.0f} s')
    rows = hist['years'].get(str(Y - 1), []) + cur
    # ---- agregats hebdomadaires : Norvege, zone, titulaire
    def wk(y, w): return y * 100 + w
    last_wk = max((wk(r[1], r[2]) for r in cur), default=None)
    # la semaine en cours est incomplete : on s'arrete a la derniere semaine pleine
    iso = now.isocalendar(); cur_wk = wk(iso[0], iso[1])
    full_last = max((k for k in {wk(r[1], r[2]) for r in rows} if k < cur_wk), default=last_wk)
    agg = {}
    for no, y, w, mm, k, start, hrs in rows:
        po = site_po.get(str(no)); org = site_org.get(str(no), '?')
        for key in ('NO', f'PO{po}', f'ORG:{org}'):
            a = agg.setdefault(key, {}).setdefault(wk(y, w), [0, 0, 0.0, set()])
            if k == 'W':
                a[0] += 1; a[2] += hrs or 0; a[3].add(mm)
            else:
                a[1] += 1
    series = {key: {str(w): [v[0], v[1], round(v[2]), len(v[3])] for w, v in sorted(d.items())} for key, d in agg.items()}
    # ---- alertes : semaine pleine la plus recente contre les 8 precedentes et la meme semaine un an plus tot
    def back(k, n):
        d = dt.date.fromisocalendar(k // 100, k % 100, 1) - dt.timedelta(weeks=n); c = d.isocalendar(); return wk(c[0], c[1])
    alerts = []
    for key, d in agg.items():
        x = d.get(full_last, [0, 0, 0, set()])[0]
        prev = [d.get(back(full_last, i), [0])[0] for i in range(1, 9)]
        ly = d.get(back(full_last, 52), [0])[0]
        m = statistics.mean(prev); sd = statistics.pstdev(prev) or 1
        if x >= 5 and x >= 1.5 * max(m, 1) and (x - m) / sd >= 2:
            alerts.append({'key': key, 'week': full_last, 'visits': x, 'avg8': round(m, 1), 'ly': ly, 'z': round((x - m) / sd, 1), 'kind': 'high'})
        elif key.startswith('PO') and m >= 8 and x <= 0.4 * m:
            alerts.append({'key': key, 'week': full_last, 'visits': x, 'avg8': round(m, 1), 'ly': ly, 'z': round((x - m) / sd, 1), 'kind': 'low'})
    # ---- fermes tres frequentees ces 14 derniers jours
    since = (now - dt.timedelta(days=14)).isoformat()
    by_site = {}
    for no, y, w, mm, k, start, hrs in cur:
        if not start or start[:10] < since:
            continue
        s = by_site.setdefault(no, {'W': 0, 'S': 0, 'h': 0.0, 'boats': set(), 'last': ''})
        s[k] += 1; s['h'] += hrs or 0; s['boats'].add(names.get(mm) or str(mm)); s['last'] = max(s['last'], start)
    hot = sorted([{'no': no, 'name': site_name.get(str(no)), 'po': site_po.get(str(no)), 'org': site_org.get(str(no)), 'cap': site_cap.get(str(no)),
                   'wb': s['W'], 'sb': s['S'], 'hours': round(s['h']), 'boats': sorted(s['boats'])[:6], 'last': s['last']}
                  for no, s in by_site.items()], key=lambda x: (-(x['wb'] + 2 * x['sb']), -x['hours']))[:80]
    # ---- positions actuelles des wellboats
    pos = []
    for p in get('/v1/geodata/fishhealth/vesselslatestpositions', T) or []:
        if p.get('mmsi') in kinds and p.get('geometry'):
            lo, la = p['geometry']['coordinates'][:2]
            pos.append({'mmsi': p['mmsi'], 'name': p.get('name') or names.get(p['mmsi']), 'k': kinds[p['mmsi']], 'lat': round(la, 4), 'lon': round(lo, 4),
                        'sog': p.get('sog'), 'ts': (p.get('timestamp') or '')[:16], 'dest': p.get('destination')})
    out = {'meta': {'built': dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), 'year': Y, 'last_full_week': full_last, 'current_week': cur_wk,
                    'boats': len(kinds), 'sites': len(locs), 'source': 'BarentsWatch fish health API: vessel visits at fish farms (AIS, Norwegian Coastal Administration)'},
           'series': series, 'alerts': sorted(alerts, key=lambda a: -a['z']), 'hot': hot, 'positions': pos,
           'boats': {str(mm): [names.get(mm), k] for mm, k in kinds.items()}}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'ecrit {OUT} ({os.path.getsize(OUT) // 1024} ko) : {len(alerts)} alertes, {len(hot)} fermes actives sur 14 jours, {len(pos)} positions')


if __name__ == '__main__':
    main()
