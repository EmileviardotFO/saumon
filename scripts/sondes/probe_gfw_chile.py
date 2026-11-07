"""Sonde GFW Chili v4 : tous les navires 'carrier/support' qui font escale dans la zone salmonicole."""
import os, json, requests
from collections import Counter, defaultdict
tok = next(v for k, v in os.environ.items() if k.startswith('S_') and v and 'FISH' in k.upper())
H = {'Authorization': f'Bearer {tok.strip()}'}
B = 'https://gateway.api.globalfishingwatch.org/v3'
PV = 'public-global-port-visits-events:latest'
POLY = {'type': 'Polygon', 'coordinates': [[[-75.8, -55.5], [-69.5, -55.5], [-69.5, -41.0], [-75.8, -41.0], [-75.8, -55.5]]]}

def ev(body, maxn=6000):
    out, off = [], 0
    while off < maxn:
        r = requests.post(B + '/events', headers=H, params={'limit': 500, 'offset': off}, json=body, timeout=180)
        if not r.ok:
            print('ERR', r.status_code, r.text[:400]); break
        j = r.json(); out += j.get('entries', [])
        if j.get('nextOffset') in (None, 0) or not j.get('entries'): break
        off = j['nextOffset']
    return out

for vt in (['CARRIER'], ['SUPPORT'], ['CARGO'], ['OTHER']):
    body = {'datasets': [PV], 'startDate': '2026-09-01', 'endDate': '2026-10-31', 'geometry': POLY, 'vesselTypes': vt}
    es = ev(body)
    print('\nTYPE', vt, 'events', len(es))
    if es: print('  cles event', list(es[0])[:20], 'vessel', list(es[0].get('vessel', {}))[:20])
    c = Counter(); info = {}; ports = defaultdict(Counter)
    for e in es:
        v = e.get('vessel') or {}
        k = v.get('id'); c[k] += 1; info[k] = (v.get('name'), v.get('flag'), v.get('ssvid'), v.get('type'))
        pv = (e.get('port_visit') or {}).get('intermediateAnchorage') or (e.get('port_visit') or {}).get('startAnchorage') or {}
        ports[k][pv.get('name')] += 1
    for k, n in c.most_common(80):
        print('  %-24s %-4s %-10s %-9s %4d  %s' % (*[str(x)[:24] for x in info[k]], n, ', '.join(f'{p}:{m}' for p, m in ports[k].most_common(4))))
# profondeur d'historique sur un navire
vid = '5eb825d9c-cb47-3b48-02a0-fc40858d8bc2'
for y in range(2017, 2027):
    r = requests.get(B + '/events', headers=H, params={'datasets[0]': PV, 'vessels[0]': vid, 'start-date': f'{y}-01-01', 'end-date': f'{y}-12-31', 'limit': 1, 'offset': 0}, timeout=120)
    print('HIST PATAGON 7', y, r.status_code, r.json().get('total') if r.ok else r.text[:100])
