"""Sonde Chili 2 : texte brut de deux resolutions de densidad de cultivo et d'un informe sectorial (pour ecrire le lecteur)."""
import io, re, requests, pdfplumber
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
for u in ['https://www.subpesca.cl/portal/615/articles-129434_documento.pdf', 'https://www.subpesca.cl/portal/615/articles-130677_documento.pdf',
          'https://www.subpesca.cl/portal/615/articles-130678_documento.pdf', 'https://source.subpesca.cl/portal/616/articles-130859_documento.pdf']:
    r = requests.get(u, headers=UA, timeout=60); print('=====', u, r.status_code, len(r.content))
    if not r.ok: continue
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        print('pages', len(pdf.pages))
        for i, p in enumerate(pdf.pages[:14]):
            t = p.extract_text() or ''
            print(f'--- page {i + 1}'); print(t[:3500])
            for tb in p.extract_tables()[:3]:
                print('   TABLE', [r[:9] for r in tb[:6]])
# l'article 130859 sous le portail 615 existe-t-il ?
for u in ['https://www.subpesca.cl/portal/615/w3-article-130859.html', 'https://www.subpesca.cl/portal/616/w3-article-130859.html', 'https://www.subpesca.cl/portal/616/w3-article-130606.html']:
    r = requests.get(u, headers=UA, timeout=30); t = re.search(r'<title>(.*?)</title>', r.text, re.S); print(u, r.status_code, t.group(1)[:120] if t else '')
    print('   pdf links', re.findall(r'href="([^"]+documento[^"]*\.pdf)"', r.text)[:3])
