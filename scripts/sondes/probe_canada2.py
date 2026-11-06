"""Sonde Canada 2 : jeux DFO complementaires, imports US par port (Est / Ouest), SST NOAA."""
import io, requests, pandas as pd
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard probe)'}
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 50)
P = 'https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/'

def csv(url, n=4):
    print('\n=====', url)
    try:
        r = requests.get(url, headers=H, timeout=120); print(' ->', r.status_code, len(r.content))
        if r.status_code != 200: print(r.text[:300]); return None
        try: df = pd.read_csv(io.BytesIO(r.content), encoding='utf-8-sig', low_memory=False)
        except Exception: df = pd.read_csv(io.BytesIO(r.content), encoding='latin-1', low_memory=False)
        print('rows', len(df)); print('cols', list(df.columns)); print(df.head(n).to_string()[:3000]); return df
    except Exception as e: print('ERR', e)

# 1. rapports publics nationaux (toutes provinces) : colonnes et provinces
df = csv(P + '288b6dc4-16dc-43cc-80a4-2a45b1f93383/attachments/Marine%20Finfish%20Data%202024.csv', 6)
if df is not None:
    for c in df.columns:
        if df[c].dtype == object and df[c].nunique() < 40: print('  ', c, df[c].value_counts().head(15).to_dict())

# 2. carcasses / statut de production : valeurs de la colonne statut, derniers mois
df = csv(P + '0a8c5505-ecb3-4d8b-8120-462bd7def6bb/attachments/carc-cat-fac-inst-2013-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv')
if df is not None:
    c = 'Production Information & Report Status'; print(df[c].value_counts().to_dict())
    print(df.groupby('Year')[c].value_counts().unstack().fillna(0).tail(6).to_string())
    print(df[['Year', 'Month']].drop_duplicates().tail(8).to_string()); print(df['Species'].value_counts().to_dict())

# 3. autres jeux : ressources via CKAN
for pid in ('27dfcbf6-d320-4afc-9d0c-3d5df107dbe6', 'fdba4d10-51aa-40df-884e-09e1c29049d8', 'e591a756-6b99-4986-b8ce-f341bd47228f',
            '4dc95665-3d44-428c-bb26-12f981c57060'):
    try:
        res = requests.get('https://open.canada.ca/data/api/action/package_show?id=' + pid, headers=H, timeout=60).json()['result']
        print('\n#####', res['title'])
        for x in res['resources']:
            print('   res:', x.get('format'), x.get('name'), x.get('url'))
            if (x.get('format') or '').upper() == 'CSV' and ('eng' in x['url'].lower() or 'english' in str(x.get('name')).lower()) and 'def' not in x['url'].lower() and 'term' not in x['url'].lower():
                csv(x['url'])
    except Exception as e: print('ERR', pid, e)

# 4. US Census : imports par port (porths), HS 030214 et 030441 depuis le Canada
for t in ('2025-09',):
    for ep, fields in (('porths', 'PORT,PORT_NAME,CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,CNT_WGT_MO,VES_WGT_MO,AIR_WGT_MO'),
                       ('porths', 'PORT,PORT_NAME,CTY_CODE,I_COMMODITY,GEN_VAL_MO')):
        for hs in ('030214', '030441'):
            u = f'https://api.census.gov/data/timeseries/intltrade/imports/{ep}'
            try:
                r = requests.get(u, params={'get': fields, 'CTY_CODE': '1220', 'I_COMMODITY': hs, 'time': t, 'COMM_LVL': 'HS6'}, headers=H, timeout=90)
                print('\n== census', ep, hs, fields[:40], r.status_code); print(r.text[:2500])
                if r.status_code == 200: break
            except Exception as e: print('ERR', e)
# variables disponibles
try:
    r = requests.get('https://api.census.gov/data/timeseries/intltrade/imports/porths/variables.json', headers=H, timeout=60)
    print(list(r.json()['variables'].keys()))
except Exception as e: print('ERR vars', e)

# 5. SST NOAA OISST (ERDDAP), quelques points
PTS = {'Broughton': (50.75, -126.5), 'Clayoquot': (49.2, -126.0), 'Fundy': (44.95, -66.9), 'Fortune Bay NL': (47.4, -55.5), 'Nova Scotia S': (43.9, -64.8)}
for n, (la, lo) in PTS.items():
    for ds in ('ncdcOisst21Agg_LonPM180',):
        u = (f'https://coastwatch.pfeg.noaa.gov/erddap/griddap/{ds}.csv?sst[(2026-09-01):30:(2026-10-31)][(0.0)][({la}):1:({la + 0.5})][({lo}):1:({lo + 0.5})]')
        try:
            r = requests.get(u, headers=H, timeout=90); print('\n== SST', n, r.status_code); print(r.text[:700])
        except Exception as e: print('ERR', e)
