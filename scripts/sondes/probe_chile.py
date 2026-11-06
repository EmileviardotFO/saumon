"""Sonde Chili : (1) Subpesca, titres des pages d'articles autour des resolutions de densidad de cultivo (pour trouver comment
les lister) ; (2) pages d'index possibles ; (3) Sernapesca, page des informes sanitarios."""
import re, time, requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
s = requests.Session(); s.headers.update(UA)
def get(u, t=30):
    try:
        r = s.get(u, timeout=t); return r.status_code, r.text
    except Exception as e:
        return None, str(e)
for u in ['https://www.subpesca.cl/portal/615/w3-article-129434.html', 'https://www.subpesca.cl/portal/615/w3-channel.html', 'https://www.subpesca.cl/portal/615/w3-propertyname-647.html',
          'https://www.subpesca.cl/portal/sitemap.xml', 'https://www.subpesca.cl/portal/615/w3-propertyvalue-51209.html']:
    c, t = get(u); title = re.search(r'<title>(.*?)</title>', t or '', re.S)
    print('==', u, c, (title.group(1).strip() if title else '')[:150])
    if c == 200:
        links = sorted(set(re.findall(r'href="([^"]*w3-(?:propertyvalue|propertyname|channel|article)[^"]*)"', t)))
        print('   liens', len(links), links[:80])
        for m in re.finditer(r'(?i)(densidad[^<]{0,120})', t): print('   >', m.group(1)[:140])
t0 = time.time(); n = 0
for i in range(130600, 130700):
    c, t = get(f'https://www.subpesca.cl/portal/615/w3-article-{i}.html', 20); n += 1
    if c == 200:
        ti = re.search(r'<title>(.*?)</title>', t, re.S); h = re.search(r'<h1[^>]*>(.*?)</h1>', t, re.S)
        print(i, c, (ti.group(1).strip() if ti else '')[:110], '|', re.sub('<[^>]+>', '', h.group(1)).strip()[:110] if h else '')
    else:
        print(i, c)
print('temps par page', round((time.time() - t0) / n, 2))
for u in ['https://www.sernapesca.cl/informes/informes-sanitarios/', 'https://www.sernapesca.cl/informacion-utilidad/informes-sanitarios-acuicultura/', 'https://www.sernapesca.cl/?s=informe+sanitario']:
    c, t = get(u); print('==', u, c)
    if c == 200: print('   ', sorted(set(re.findall(r'https://www\.sernapesca\.cl/app/uploads/[^"\']+\.(?:pdf|xlsx?)', t)))[:40])
print('fin')
