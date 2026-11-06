"""Sonde Canada 3 : imports US par port (porths) et SST (Open-Meteo marine, ERDDAP)."""
import json, os, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard probe)'}
U = 'https://api.census.gov/data/timeseries/intltrade/imports/porths'
v = requests.get(U + '/variables.json', headers=H, timeout=60).json()['variables']
print(sorted(v.keys()))
for q in ({'get': 'PORT,PORT_NAME,CTY_CODE,CTY_NAME,GEN_VAL_MO,CNT_WGT_MO', 'I_COMMODITY': '030214', 'COMM_LVL': 'HS6', 'time': '2025-09'},
          {'get': 'PORT,PORT_NAME,CTY_CODE,GEN_VAL_MO', 'I_COMMODITY': '030214', 'time': '2025-09'},
          {'get': 'PORT,PORT_NAME,GEN_VAL_MO', 'I_COMMODITY': '030214', 'CTY_CODE': '1220', 'time': '2025-09'},
          {'get': 'PORT,PORT_NAME,CTY_CODE,GEN_VAL_MO', 'I_COMMODITY': '030214', 'time': 'from 2025-01 to 2025-03'}):
    q = dict(q, key=os.environ.get('CENSUS_API_KEY', ''))
    r = requests.get(U, params=q, headers=H, timeout=90)
    print('\n==', q, r.status_code, r.text[:200] if 'html' in r.text[:20].lower() else '')
    if r.text.startswith('['):
        t = json.loads(r.text); print(t[0], len(t))
        ca = [x for x in t[1:] if '1220' in x]
        ca.sort(key=lambda x: -float(x[t[0].index('GEN_VAL_MO')] or 0))
        for x in ca[:25]: print('  ', x)
        break

# HS10 par pays (endpoint qui marche deja) : quantite totale Canada
r = requests.get('https://api.census.gov/data/timeseries/intltrade/imports/hs',
                 params={'get': 'CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1', 'time': 'from 2025-07 to 2025-09',
                         'COMM_LVL': 'HS10', 'I_COMMODITY': '0302140000', 'CTY_CODE': '1220', 'key': os.environ.get('CENSUS_API_KEY', '')}, headers=H, timeout=90)
print('\n== hs10 Canada', r.status_code, r.text[:800])


# serie mensuelle par port 2024-2026 pour HS 030214, Canada
q = {'get': 'PORT,PORT_NAME,CTY_CODE,GEN_VAL_MO', 'I_COMMODITY': '030214', 'time': 'from 2024-01 to 2026-12', 'key': os.environ.get('CENSUS_API_KEY', '')}
r = requests.get(U, params=q, headers=H, timeout=120); print('\n== series', r.status_code, r.text[:200])
if r.text.startswith('['):
    t = json.loads(r.text); h = t[0]; print(h, len(t))
    from collections import defaultdict
    tot = defaultdict(float); pn = {}
    for x in t[1:]:
        d = dict(zip(h, x))
        if d['CTY_CODE'] != '1220': continue
        tot[(d['time'], d['PORT'])] += float(d['GEN_VAL_MO'] or 0); pn[d['PORT']] = d['PORT_NAME']
    ports = defaultdict(float)
    for (tm, p), v in tot.items(): ports[p] += v
    for p, v in sorted(ports.items(), key=lambda x: -x[1])[:30]: print('  ', p, pn[p], round(v / 1e6, 1), 'M USD')
