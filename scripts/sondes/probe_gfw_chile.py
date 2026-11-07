"""Sonde GFW Chili v3 : identites (recherche avancee), puis evenements de quelques wellboats."""
import os, json, requests
tok = next(v for k, v in os.environ.items() if k.startswith('S_') and v and 'FISH' in k.upper())
H = {'Authorization': f'Bearer {tok.strip()}'}
B = 'https://gateway.api.globalfishingwatch.org/v3'
ID = 'public-global-vessel-identity:latest'

def g(path, p):
    r = requests.get(B + path, headers=H, params=p, timeout=120)
    if not r.ok: print('  ERR', path, r.status_code, r.text[:250])
    return r

def show(e, tag=''):
    si = (e.get('selfReportedInfo') or [{}])
    s0 = si[0] if si else {}
    reg = (e.get('registryInfo') or [{}])
    r0 = reg[0] if reg else {}
    cs = (e.get('combinedSourcesInfo') or [{}])[0]
    st = [x['name'] for x in cs.get('shiptypes', [])]
    print(f"  {tag}|{s0.get('shipname') or r0.get('shipname')}|{s0.get('flag') or r0.get('flag')}|mmsi {s0.get('ssvid')}|imo {r0.get('imo')}|{st}|{s0.get('transmissionDateFrom','')[:10]}->{s0.get('transmissionDateTo','')[:10]}|pos {s0.get('positionsCount')}|id {s0.get('id')}|reg {r0.get('shiptypes') if r0 else ''} {r0.get('tonnageGt') if r0 else ''} {r0.get('lengthM') if r0 else ''}")
    return s0.get('id')

ids = {}
for w in ["flag = 'CHL' AND shiptypes = 'CARRIER'", "flag = 'CHL' AND shiptypes = 'SUPPORT'", "flag = 'CHL' AND shiptypes = 'OTHER'",
          "flag = 'CHL' AND shiptypes = 'FISH_TENDER'"]:
    r = g('/vessels/search', {'where': w, 'datasets[0]': ID, 'limit': 50, 'includes[0]': 'MATCH_CRITERIA'})
    if r.ok:
        j = r.json(); print('WHERE', w, 'total', j.get('total'), 'n', len(j.get('entries', [])), 'next', j.get('since'))
        for e in j.get('entries', [])[:50]: show(e, 'W')
for q in ['PATAGON', 'PATAGON XI', 'PATAGON VII', 'ORCA YKA', 'ORCA CHONO', 'ORCA', 'GRIP PATAGONIA', 'RONJA', 'SOLVTRANS', 'AQUASHIP',
          'DON', 'MARFOOD', 'SITECNA', 'TRANSMARKO', 'AUSTRAL', 'CAMANCHACA', 'BOLD', 'NORDIC', 'AYSEN', 'CHILOE', 'SAN CRISTOBAL', 'AQUAREOS']:
    r = g('/vessels/search', {'query': q, 'datasets[0]': ID, 'limit': 20})
    if r.ok:
        es = r.json().get('entries', [])
        print('Q', q, len(es))
        for e in es:
            s0 = (e.get('selfReportedInfo') or [{}])[0]
            if s0.get('flag') == 'CHL' or 'PATAGON' in q or 'ORCA' in q:
                i = show(e, q)
                if i and s0.get('flag') == 'CHL': ids[s0.get('shipname')] = i
print('IDS', json.dumps(ids)[:3000])
# evenements pour les 6 premiers
EV = ['public-global-port-visits-events:latest', 'public-global-loitering-events:latest', 'public-global-encounters-events:latest', 'public-global-fishing-events:latest']
for name, vid in list(ids.items())[:8]:
    for ds in EV:
        r = g('/events', {'datasets[0]': ds, 'vessels[0]': vid, 'start-date': '2026-08-01', 'end-date': '2026-11-06', 'limit': 50, 'offset': 0})
        if r.ok:
            es = r.json().get('entries', [])
            print('EV', name, ds.split('-')[2], len(es), r.json().get('total'))
            for e in es[:6]:
                pos = e.get('position') or {}
                pv = (e.get('port_visit') or {}).get('startAnchorage') or {}
                print('     ', e.get('start', '')[:16], e.get('end', '')[:16], round(pos.get('lat', 0), 3), round(pos.get('lon', 0), 3), pv.get('name'), e.get('loitering', {}).get('totalTimeHours'))
