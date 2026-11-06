"""Sonde Canada 3 : imports US par port (porths) et SST (Open-Meteo marine, ERDDAP)."""
import json, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard probe)'}
U = 'https://api.census.gov/data/timeseries/intltrade/imports/porths'
v = requests.get(U + '/variables.json', headers=H, timeout=60).json()['variables']
print(sorted(v.keys()))
for q in ({'get': 'PORT,PORT_NAME,CTY_CODE,CTY_NAME,GEN_VAL_MO,CNT_WGT_MO', 'I_COMMODITY': '030214', 'COMM_LVL': 'HS6', 'time': '2025-09'},
          {'get': 'PORT,PORT_NAME,CTY_CODE,GEN_VAL_MO', 'I_COMMODITY': '030214', 'time': '2025-09'},
          {'get': 'PORT,PORT_NAME,GEN_VAL_MO', 'I_COMMODITY': '030214', 'CTY_CODE': '1220', 'time': '2025-09'},
          {'get': 'PORT,PORT_NAME,CTY_CODE,GEN_VAL_MO', 'I_COMMODITY': '030214', 'time': 'from 2025-01 to 2025-03'}):
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
                         'COMM_LVL': 'HS10', 'I_COMMODITY': '0302140000', 'CTY_CODE': '1220'}, headers=H, timeout=90)
print('\n== hs10 Canada', r.status_code, r.text[:800])

# SST : Open-Meteo marine (historique)
for n, (la, lo) in {'Broughton': (50.7, -126.5), 'Clayoquot': (49.2, -126.0), 'Fundy': (44.95, -66.9),
                    'Fortune Bay NL': (47.5, -55.6), 'Nova Scotia S': (44.0, -64.6)}.items():
    r = requests.get('https://marine-api.open-meteo.com/v1/marine', params={'latitude': la, 'longitude': lo, 'daily': 'sea_surface_temperature_mean',
                     'hourly': 'sea_surface_temperature', 'start_date': '2022-01-01', 'end_date': '2026-10-31', 'timezone': 'UTC'}, headers=H, timeout=90)
    print('\n== open-meteo', n, r.status_code, r.text[:300])
    try:
        j = r.json(); hh = j.get('hourly', {}); ts = hh.get('time', []); ss = hh.get('sea_surface_temperature', [])
        print('  hourly n', len(ts), 'non-null', sum(1 for s in ss if s is not None), ts[:1], ts[-1:])
        from collections import defaultdict
        m = defaultdict(list)
        for t, s in zip(ts, ss):
            if s is not None: m[t[:7]].append(s)
        print('  monthly', {k: round(sum(x) / len(x), 2) for k, x in list(m.items())[::6]})
        print('  lat/lon used', j.get('latitude'), j.get('longitude'))
    except Exception as e: print('ERR', e)

# ERDDAP : recherche des jeux OISST
for srv in ('https://coastwatch.pfeg.noaa.gov/erddap', 'https://www.ncei.noaa.gov/erddap'):
    try:
        r = requests.get(srv + '/search/index.json', params={'searchFor': 'OISST v2.1 daily', 'page': 1, 'itemsPerPage': 10}, headers=H, timeout=60)
        j = r.json(); cols = j['table']['columnNames']; i = cols.index('Dataset ID'); it = cols.index('Title')
        for row in j['table']['rows']: print('  ', srv, row[i], '|', row[it][:90])
    except Exception as e: print('ERR erddap', srv, e)
