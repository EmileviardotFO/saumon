"""Sonde Canada : inventaire des sources publiques (DFO open data BC, StatCan, US Census).
Imprime les colonnes, la couverture et quelques lignes de chaque source."""
import io, json, zipfile, requests, pandas as pd

H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard probe)'}
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40)

def get(url, **kw):
    r = requests.get(url, headers=H, timeout=90, **kw)
    print('  ->', r.status_code, len(r.content), 'bytes', r.headers.get('content-type'))
    return r

def show_csv(name, url):
    print('\n=====', name, '\n', url)
    try:
        r = get(url)
        if r.status_code != 200: print(r.text[:300]); return None
        for enc in ('utf-8-sig', 'latin-1'):
            try: df = pd.read_csv(io.BytesIO(r.content), encoding=enc, low_memory=False); break
            except Exception as e: err = e
        print('rows', len(df)); print('cols', list(df.columns))
        print(df.head(4).to_string()); print(df.tail(3).to_string())
        for c in df.columns:
            lc = c.lower()
            if any(k in lc for k in ('date', 'year', 'month', 'annee', 'mois')):
                try: print('  range', c, df[c].min(), '->', df[c].max())
                except Exception: pass
        return df
    except Exception as e:
        print('ERR', e)

def ckan(pid):
    """Liste les ressources d'un jeu open.canada.ca."""
    for base in ('https://open.canada.ca/data/api/action/package_show?id=',):
        try:
            r = requests.get(base + pid, headers=H, timeout=60)
            res = r.json()['result']
            print('\n#####', res['title']['en'] if isinstance(res.get('title'), dict) else res.get('title'),
                  '| modified', res.get('metadata_modified'))
            return [(x.get('name'), x.get('url'), x.get('format')) for x in res['resources']]
        except Exception as e:
            print('ckan ERR', pid, e)
    return []

SETS = {
    'sea_lice': '3cafbe89-c98b-4b44-88f1-594e8d28838d',
    'mortality_category': '0a8c5505-ecb3-4d8b-8120-462bd7def6bb',
    'fish_health_events': 'deefd1d7-7184-44c7-83aa-ec0db91aad27',
    'mortality_events': '7fbb2662-391a-4df7-99b4-3343fa68fc93',
    'transfer_licences': '700fe290-7653-49e1-b961-741dc1ead924',
    'licence_holders': '522d1b67-30d8-4a34-9b62-5da99b1035e6',
    'escapes': '691dd994-4911-433d-b3b6-00349ba9f24e',
    'aar_drugs': '288b6dc4-16dc-43cc-80a4-2a45b1f93383',
}
for k, pid in SETS.items():
    for name, url, fmt in ckan(pid):
        print('   res:', fmt, name, url)
        if (fmt or '').upper() == 'CSV' and 'eng' in (url or '').lower():
            show_csv(k + ' / ' + str(name), url)

# Recherche d'autres jeux aquaculture (production, inventaire, Atlantique)
for q in ('aquaculture salmon inventory', 'marine finfish aquaculture', 'aquaculture production statistics',
          'salmon aquaculture New Brunswick', 'aquaculture Newfoundland salmon'):
    try:
        r = requests.get('https://open.canada.ca/data/api/action/package_search', params={'q': q, 'rows': 25},
                         headers=H, timeout=60).json()
        print('\n>>> search', q, r['result']['count'])
        for p in r['result']['results']:
            t = p['title']['en'] if isinstance(p['title'], dict) else p['title']
            print('  ', p['id'], '|', t, '|', p.get('metadata_modified', '')[:10])
    except Exception as e:
        print('search ERR', q, e)

# StatCan : production aquacole annuelle par province (32-10-0107)
print('\n===== StatCan 32-10-0107')
try:
    r = get('https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/32100107/en')
    u = r.json()['object']; z = zipfile.ZipFile(io.BytesIO(get(u).content))
    f = [n for n in z.namelist() if not n.endswith('MetaData.csv')][0]
    df = pd.read_csv(z.open(f), low_memory=False)
    print(list(df.columns)); print(df.head(3).to_string())
    m = df[df.apply(lambda r: 'almon' in ' '.join(map(str, r.values)), axis=1)]
    print(m.tail(40).to_string())
except Exception as e:
    print('ERR', e)

# US Census : imports US de saumon d'Atlantique frais depuis le Canada, par district d'entree
print('\n===== US Census imports from Canada HS 030214')
for t in ('2025-09', '2026-08'):
    try:
        r = get('https://api.census.gov/data/timeseries/intltrade/imports/hs',
                params={'get': 'DIST_NAME,CON_VAL_MO,CON_QY1_MO,UNIT_QY1', 'I_COMMODITY': '030214',
                        'CTY_CODE': '1220', 'DISTRICT': '*', 'time': t})
        print(r.text[:2500])
    except Exception as e:
        print('ERR', e)

# StatCan CIMT (commerce par province, HS6)
print('\n===== CIMT')
for u in ('https://www150.statcan.gc.ca/t1/cimt/rest/getReport/(%22N%22,%22E%22,%22030214%22,%22999%22,%22202601%22,%22202608%22)',
          'https://www150.statcan.gc.ca/t1/cimt/rest/getCodeSet'):
    try:
        r = get(u); print(r.text[:1500])
    except Exception as e:
        print('ERR', e)
