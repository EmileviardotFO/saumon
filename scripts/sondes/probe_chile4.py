"""Sonde Chili 4 : pages des informes techniques qui donnent l'intention de siembra (nombre de poissons) ; texte des rapports sectoriels 2026."""
import io, re, requests, pdfplumber
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
for aid in [122256, 127266, 120926]:
    r = requests.get(f'https://www.subpesca.cl/portal/615/articles-{aid}_documento.pdf', headers=UA, timeout=90); print('=====', aid)
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ''
            if re.search(r'(?i)intenci[oó]n de siembra|ejemplares|n[°º] de peces|PROPUESTA', t) and i >= 4:
                print(f'--- page {i + 1}'); print(t[:1800])
                for tb in p.extract_tables()[:4]:
                    print('   TABLE', len(tb), [x[:9] for x in tb[:8]])
for aid in [129116]:
    r = requests.get(f'https://source.subpesca.cl/portal/616/articles-{aid}_documento.pdf', headers=UA, timeout=90)
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ''
            if re.search(r'(?i)cosecha', t):
                print(f'--- REPORT page {i + 1}'); print(t[:3000])
