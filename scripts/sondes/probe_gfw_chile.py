"""Sonde GFW Chili v2 : presence AIS par zone (navires de service), jeux VMS Chili."""
import os, json, requests
tok = next(v for k, v in os.environ.items() if k.startswith('S_') and v and 'FISH' in k.upper())
H = {'Authorization': f'Bearer {tok.strip()}'}
B = 'https://gateway.api.globalfishingwatch.org/v3'

r = requests.get(B + '/datasets', headers=H, params={'limit': 100, 'offset': 0}, timeout=90)
j = r.json(); print('datasets keys', list(j)[:10] if isinstance(j, dict) else type(j), str(j)[:600])

# zone salmonicole : Los Lagos + Aysen (+ Magallanes a part)
ZONES = {
    'LosLagos_Aysen': [[-75.6, -47.5], [-72.0, -47.5], [-72.0, -41.3], [-75.6, -41.3], [-75.6, -47.5]],
    'Magallanes': [[-75.5, -54.5], [-70.0, -54.5], [-70.0, -50.5], [-75.5, -50.5], [-75.5, -54.5]],
}
def report(ds, poly, dr, extra=None):
    body = {'geojson': {'type': 'Polygon', 'coordinates': [poly]}}
    p = {'spatial-resolution': 'LOW', 'temporal-resolution': 'ENTIRE', 'group-by': 'VESSEL_ID',
         'datasets[0]': ds, 'date-range': dr, 'format': 'JSON'}
    if extra: p.update(extra)
    r = requests.post(B + '/4wings/report', headers=H, params=p, json=body, timeout=300)
    print('REPORT', ds, dr, '->', r.status_code, '' if r.ok else r.text[:300])
    return r.json() if r.ok else None

for ds in ('public-global-presence:latest', 'public-global-fishing-effort:latest',
           'public-chile-presence:latest', 'public-chile-fishing-effort:latest',
           'public-chile-non-fishing-presence:latest', 'public-chile-vms-presence:latest'):
    j = report(ds, ZONES['LosLagos_Aysen'], '2026-09-01,2026-09-30')
    if not j: continue
    rows = []
    for ent in j.get('entries', []):
        for k, v in ent.items():
            rows += v
    print('  lignes', len(rows), 'cles', list(rows[0])[:20] if rows else None)
    agg = {}
    for x in rows:
        key = x.get('vesselId') or x.get('mmsi')
        a = agg.setdefault(key, dict(x, hours=0)); a['hours'] += x.get('hours') or 0
    from collections import Counter
    print('  navires', len(agg), 'types', Counter(a.get('vesselType') for a in agg.values()).most_common(12))
    print('  pavillons', Counter(a.get('flag') for a in agg.values()).most_common(6))
    for a in sorted(agg.values(), key=lambda a: -a['hours'])[:60]:
        if a.get('vesselType') in ('fishing',): continue
        print('    %-28s %-5s %-10s %-14s %6.0f h  %s' % ((a.get('shipName') or '')[:28], a.get('flag'), a.get('mmsi'), a.get('vesselType'), a['hours'], a.get('callsign')))
