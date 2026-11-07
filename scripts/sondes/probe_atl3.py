"""Sonde Canada Atlantique (3) : annees DFO 2016-2021, sante animale et statistiques de Terre-Neuve, rapports NB."""
import re, gzip, base64, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
B = 'https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/288b6dc4-16dc-43cc-80a4-2a45b1f93383/attachments/'
def dump(tag, b):
    print(f'=={tag}=='); print(base64.b64encode(gzip.compress(b)).decode()); print(f'==/{tag}==')
def get(tag, url):
    try:
        r = requests.get(url, headers=H, timeout=180); print(tag, r.status_code, len(r.content), r.headers.get('content-type'), url[:160])
        if r.ok and len(r.content) < 20_000_000: dump(tag, r.content)
        return r
    except Exception as e: print(tag, 'ERR', e, url)
for y in range(2016, 2022): get(f'DFO{y}', f'{B}marine-finfish-data-{y}.csv')
for t, u in [('NL_AAH', 'https://www.gov.nl.ca/fisheries/aquatic-animal-health/'), ('NL_PROD', 'https://www.gov.nl.ca/fisheries/fishaq/stats/production/'),
             ('NL_COC24', 'https://www.gov.nl.ca/fisheries/files/Annual-Code-of-Containment-Compliance-Report-2024.pdf'),
             ('NL_LIC', 'https://www.gov.nl.ca/fisheries/licenses-permits-and-fees/licensing/'),
             ('NB_AR', 'https://www2.gnb.ca/content/dam/GNB3/org/aaf-aap/doc/ar-2024-2025.pdf'),
             ('NB_LICESTD', 'https://dnr-mrn.gnb.ca/AquacultureRegistryDocs/OtherDocuments/Sea%20Lice%20Monitoring%20and%20Reporting%20Standard%202024_EN%20-%20FINAL.pdf')]:
    r = get(t, u)
    if r is not None and r.ok and 'html' in (r.headers.get('content-type') or ''):
        for l in sorted(set(re.findall(r'href="([^"#]+\.(?:pdf|xlsx?|csv))"', r.text)))[:40]:
            l = requests.compat.urljoin(r.url, l)
            if re.search(r'(?i)lice|health|isa|mortal|bma|bay|production|stat|aqua|fish|sites?|licen', l): get(t + '_' + re.sub(r'\W', '_', l.split('/')[-1])[:50], l)
