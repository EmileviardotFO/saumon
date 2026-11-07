"""Sonde Canada Atlantique (2) : telechargement des sources reperees, renvoyees en base64 dans le journal."""
import json, re, gzip, base64, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
def dump(tag, b):
    print(f'=={tag}=='); print(base64.b64encode(gzip.compress(b)).decode()); print(f'==/{tag}==')
def get(tag, url, **kw):
    try:
        r = requests.get(url, headers=H, timeout=180, **kw); print(tag, r.status_code, len(r.content), r.headers.get('content-type'), url[:150])
        if r.ok and len(r.content) < 25_000_000: dump(tag, r.content)
        return r
    except Exception as e: print(tag, 'ERR', e, url)
# DFO : declaration publique nationale (Reglement sur les activites d'aquaculture)
r = requests.get('https://open.canada.ca/data/api/3/action/package_show', params={'id': '288b6dc4-16dc-43cc-80a4-2a45b1f93383'}, headers=H, timeout=60).json()['result']
res = [(x.get('name') if isinstance(x.get('name'), str) else (x.get('name_translated') or {}).get('en'), x.get('format'), x.get('url'), x.get('language')) for x in r['resources']]
for x in res: print('RES', x)
for n, f, u, lang in res:
    if f == 'CSV' and re.search(r'Marine%20Finfish|Marine Finfish', u): get('DFO_' + re.sub(r'\W', '_', n or u[-30:]), u)
    if f in ('PDF', 'TXT') and re.search(r'(?i)dictionary|dictionnaire|guide|readme|data', n or ''): get('DFODOC_' + re.sub(r'\W', '_', n or '')[:40], u)
# Nouvelle-Ecosse
get('NS_LEASES', 'https://data.novascotia.ca/api/views/h57h-p9mm/rows.csv?accessType=DOWNLOAD')
get('NS_LEASES_GEO', 'https://data.novascotia.ca/api/geospatial/h57h-p9mm?method=export&format=GeoJSON')
get('NS_LAND', 'https://data.novascotia.ca/api/views/yqwg-f62a/rows.csv?accessType=DOWNLOAD')
get('NS_PROD', 'https://data.novascotia.ca/api/views/v2ex-ev63/rows.csv?accessType=DOWNLOAD')
get('NS_BREACH1', 'https://novascotia.ca/fish/aquaculture/public-information/2024.07.23_Update_to_Public_Notice-_Breach_of_Containment.pdf')
get('NS_BREACH2', 'https://novascotia.ca/fish/aquaculture/public-information/public-notice-breach-of-containment_2025-08-11.pdf')
get('NS_FH', 'https://novascotia.ca/fish/aquaculture/fish-health/')
# Nouveau-Brunswick : catalogue Socrata + registre
try:
    c = requests.get('https://api.us.socrata.com/api/catalog/v1', params={'domains': 'gnb.socrata.com', 'q': 'aquaculture', 'limit': 100}, headers=H, timeout=60).json()
    for x in c.get('results', []):
        rs = x['resource']; print('GNB', rs['id'], rs['name'], rs.get('updatedAt', '')[:10])
        if re.search(r'(?i)fin ?fish|salmon|saumon|poisson', rs['name'] + ' ' + (rs.get('description') or '')):
            get('NB_' + rs['id'], f"https://gnb.socrata.com/api/views/{rs['id']}/rows.csv?accessType=DOWNLOAD")
except Exception as e: print('GNB ERR', e)
for t, u in [('NB_REG', 'https://dnr-mrn.gnb.ca/AquacultureRegistry/'), ('NB_SALMON', 'https://www2.gnb.ca/content/gnb/en/departments/10/aquaculture/content/overview/salmon.html'),
             ('NB_PUBS', 'https://www2.gnb.ca/content/gnb/en/departments/10/aquaculture/content/publications.html'),
             ('NB_STRAT', 'https://www2.gnb.ca/content/dam/gnb/Departments/10/pdf/Aquaculture/nb-finfish-aquaculture-growth-strategy 2022-2030.pdf'),
             ('NL_PUBREP', 'https://www.gov.nl.ca/fisheries/files/aquaculture-public-reporting-pdf-public-reporting.pdf'),
             ('NL_STATS', 'https://www.gov.nl.ca/fisheries/fishaq/stats'), ('NL_PUBS', 'https://www.gov.nl.ca/fisheries/publications/aquaculture-2/'),
             ('NL_BRANCH', 'https://www.gov.nl.ca/fisheries/aquaculture-branch/'),
             ('CFIA_ISA', 'https://inspection.canada.ca/en/animal-health/aquatic-animals/diseases/reportable-diseases/isa/locations-infected'),
             ('STATCAN_PROD', 'https://www150.statcan.gc.ca/n1/tbl/csv/32100107-eng.zip'), ('STATCAN_EXP', 'https://www150.statcan.gc.ca/n1/tbl/csv/32100005-eng.zip')]:
    get(t, u)
