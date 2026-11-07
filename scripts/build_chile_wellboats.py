"""Wellboats et navires de service au Chili (Global Fishing Watch, AIS) : escales 2023 -> aujourd'hui.

Source : API Global Fishing Watch v3, jeu 'public-global-port-visits-events' (escales detectees par GFW a
partir de l'AIS ; les 'anchorages' incluent les usines, les ports et les points d'arret pres des fermes).
On garde les navires classes 'carrier' et 'cargo' par GFW dans la zone salmonicole (41-55.5 S).
Sortie : data/chile_wellboats_raw.json (escales compactes + fiche des navires). Les mois anciens sont
gardes en cache, seuls les 2 derniers mois sont relus.
"""
import os, json, time, datetime as dt, requests

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


if __name__ == '__main__':
    main()
