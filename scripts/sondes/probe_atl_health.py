"""Sonde : avis publics de mortalite anormale a Terre-Neuve (NAIA) — ou sont-ils listes, et sous quelle forme."""
import io, re, json, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}


def get(u, **kw):
    r = requests.get(u, headers=H, timeout=60, **kw); print(u, r.status_code, len(r.content), r.headers.get('content-type')); return r


r = get('https://naia.ca/publications/')
for h, l in re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
    l = re.sub(r'<[^>]+>|\s+', ' ', l).strip()
    if re.search(r'(?i)\.pdf|mortal|notice|report|public', h + ' ' + l): print('   ', h, '|', l[:120])
for q in ('mortality', 'abnormal', 'notice'):
    for kind in ('media', 'posts', 'pages'):
        try:
            r = get(f'https://naia.ca/wp-json/wp/v2/{kind}', params={'search': q, 'per_page': 100})
            if r.ok and 'json' in (r.headers.get('content-type') or ''):
                for x in r.json()[:60]:
                    print('   ', kind, x.get('date'), (x.get('title') or {}).get('rendered', '')[:100], x.get('source_url') or x.get('link'))
        except Exception as e:  # noqa: BLE001
            print('ERREUR', e)
# anciens liens Concrete5 : quels numeros repondent encore ?
import pdfplumber
ok = []
for n in range(640, 760):
    try:
        r = requests.get(f'https://naia.ca/index.php/download_file/view/{n}/200', headers=H, timeout=30)
        if r.ok and r.content[:4] == b'%PDF':
            t = (pdfplumber.open(io.BytesIO(r.content)).pages[0].extract_text() or '')[:300].replace('\n', ' ')
            ok.append(n); print('PDF', n, '|', t)
    except Exception as e:  # noqa: BLE001
        pass
print('PDF trouves', len(ok), ok[:5], ok[-5:])
