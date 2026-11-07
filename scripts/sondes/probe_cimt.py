"""Sonde : application CIMT de Statistique Canada (commerce international par SH et province) - points d'acces."""
import re, requests, json
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)', 'Accept': 'application/json, text/html'}
for u in ['https://www150.statcan.gc.ca/n1/en/catalogue/71-607-X2021004', 'https://www150.statcan.gc.ca/t1/cimt/en', 'https://www150.statcan.gc.ca/t1/cimt/index.jsp',
          'https://www150.statcan.gc.ca/t1/cimt/rest/getReport/(%22-1%22,%22-1%22,1,2,1,0,1,%220302140000%22,%221%22,%22NA%22,%2224%22,%2210%22,%22202601%22,%22202608%22,%22202601%22,%22202608%22,%22-1%22)/json',
          'https://www150.statcan.gc.ca/t1/cimt/rest/getSearchHS/0302/en', 'https://www150.statcan.gc.ca/n1/pub/71-607-x/71-607-x2021004-eng.htm']:
    try:
        r = requests.get(u, headers=H, timeout=60, allow_redirects=True)
        print('##', u, r.status_code, r.url, r.headers.get('content-type'), len(r.text))
        print(r.text[:1500].replace('\n', ' '))
        for m in sorted(set(re.findall(r'["\'](/t1/cimt[^"\']+|https?://[^"\']*cimt[^"\']*|[^"\']*rest/[^"\']+)["\']', r.text)))[:60]: print('  LINK', m)
        for s in re.findall(r'src="([^"]+\.js[^"]*)"', r.text)[:15]:
            js = requests.get(requests.compat.urljoin(r.url, s), headers=H, timeout=60).text
            for m in sorted(set(re.findall(r'["\'`]([^"\'`]*rest/[^"\'`]{3,120})["\'`]', js)))[:60]: print('  JS', s[-40:], m)
    except Exception as e: print(u, 'ERR', e)
