"""Sonde : jeux de donnees CIMT (commerce par SH, province) sur open.canada.ca + page de l'application."""
import re, requests, json
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
for q in ['cimt', 'Canadian International Merchandise Trade HS', 'merchandise trade province HS exports', 'international merchandise trade database']:
    r = requests.get('https://open.canada.ca/data/api/3/action/package_search', params={'q': q, 'rows': 30}, headers=H, timeout=60).json()['result']['results']
    for p in r:
        t = (p.get('title_translated') or {}).get('en') or p.get('title')
        if re.search(r'(?i)trade|cimt|commerce', t):
            print('PKG', p['id'], p.get('metadata_modified', '')[:10], t[:140]); [print('    ', x.get('format'), x.get('url')) for x in p['resources'][:6]]
r = requests.get('https://www150.statcan.gc.ca/n1/en/catalogue/71-607-X2021004', headers=H, timeout=60)
for m in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
    if re.search(r'(?i)cimt|trade|71-607|commerce', m): print('LINK', m)
