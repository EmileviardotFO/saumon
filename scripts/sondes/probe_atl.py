"""Sonde Canada Atlantique : inventaire des sources publiques (open.canada.ca, provinces, CFIA, StatCan)."""
import json, re, gzip, base64, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
def dump(tag, obj):
    print(f'=={tag}=='); print(base64.b64encode(gzip.compress(json.dumps(obj, ensure_ascii=False).encode())).decode()); print(f'==/{tag}==')
out = {'ckan': {}, 'pages': {}}
Q = ['aquaculture New Brunswick', 'aquaculture Nova Scotia', 'aquaculture Newfoundland', 'marine aquaculture leases', 'Aquaculture Activities Regulations',
     'drug pesticide aquaculture', 'fish health events aquaculture', 'infectious salmon anaemia', 'sea lice Atlantic', 'aquaculture production', 'aquaculture escapes',
     'bay management area', 'finfish aquaculture sites', 'salmon aquaculture', 'aquaculture site New Brunswick salmon', 'Newfoundland aquaculture licences']
for q in Q:
    try:
        r = requests.get('https://open.canada.ca/data/api/3/action/package_search', params={'q': q, 'rows': 40}, headers=H, timeout=60)
        for p in r.json()['result']['results']:
            out['ckan'][p['id']] = {'t': p.get('title_translated', {}).get('en') or p.get('title'), 'org': (p.get('organization') or {}).get('title'),
                                    'mod': p.get('metadata_modified', '')[:10], 'res': [[x.get('name') if isinstance(x.get('name'), str) else (x.get('name_translated') or {}).get('en'), x.get('format'), x.get('url')] for x in p.get('resources', [])][:25]}
        print(q, r.status_code, len(out['ckan']))
    except Exception as e: print(q, 'ERR', e)
P = ['https://novascotia.ca/fish/aquaculture/public-information/', 'https://novascotia.ca/fish/aquaculture/site-mapping-tool',
     'https://novascotia.ca/fish/aquaculture/fish-health/', 'https://novascotia.ca/fish/aquaculture/aquaculture-management-areas/',
     'https://www.gov.nl.ca/ffa/aquaculture/', 'https://www.gov.nl.ca/fisheries/aquaculture/', 'https://www.gov.nl.ca/ffa/public-education/aquaculture/',
     'https://www2.gnb.ca/content/gnb/en/departments/10/open_data/aquaculture.html', 'https://www2.gnb.ca/content/gnb/en/departments/10/aquaculture.html',
     'https://www2.gnb.ca/content/gnb/en/departments/10/aquaculture/content/masmp.html',
     'https://inspection.canada.ca/en/animal-health/aquatic-animals/diseases/reportable-diseases/isa/locations',
     'https://inspection.canada.ca/animal-health/aquatic-animals/diseases/reportable-diseases/infectious-salmon-anaemia/locations-infected/eng/1339174937153/1339175227861',
     'https://www.dfo-mpo.gc.ca/aquaculture/management-gestion/apr-rpa-reporting-eng.htm', 'https://www.dfo-mpo.gc.ca/aquaculture/sci-res/rd2024-25-eng.html',
     'https://www.gov.nl.ca/fisheries/files/Active-Aquaculture-Licences-Aug-18-2026.pdf', 'https://www.gov.nl.ca/ffa/files/Aquaculture-Sites-September-7-2022.pdf',
     'https://atlanticfishfarmers.com/', 'https://mowi.com/cae/', 'https://www.cookeseafood.com/', 'https://www.cermaq.com/canada']
for u in P:
    try:
        r = requests.get(u, headers=H, timeout=60, allow_redirects=True)
        links = sorted(set(re.findall(r'href="([^"#]+)"', r.text))) if 'html' in r.headers.get('content-type', '') else []
        links = [requests.compat.urljoin(r.url, l) for l in links if re.search(r'(?i)\.(pdf|xlsx?|csv|zip|json|kmz|kml|shp|geojson)$|aquacult|lice|health|licen|site|bma|isa|data|report|stat', l)]
        out['pages'][u] = {'status': r.status_code, 'final': r.url, 'type': r.headers.get('content-type'), 'len': len(r.content),
                           'title': (re.search(r'<title>(.*?)</title>', r.text, re.S) or [None, ''])[1].strip()[:150] if 'html' in r.headers.get('content-type', '') else '',
                           'links': links[:250], 'pdf_b64': base64.b64encode(r.content).decode() if u.endswith('.pdf') and r.ok else None}
        print(u, r.status_code, len(r.content), len(links))
    except Exception as e: print(u, 'ERR', e)
# Statistique Canada : production aquacole par province (32-10-0107)
try:
    r = requests.get('https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/32100107/en', headers=H, timeout=60); print('statcan', r.status_code, r.text[:200]); out['statcan'] = r.text[:500]
except Exception as e: print('statcan ERR', e)
dump('ATL', out)
