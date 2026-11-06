"""Sonde Chili 3 : texte et tableaux de resolutions non lues, et rapports sectoriels manquants."""
import io, re, requests, pdfplumber, sys
sys.path.insert(0, 'scripts')
import build_chile_subpesca as B
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
for aid in [122256, 120926, 124291, 127266]:
    r = requests.get(f'https://www.subpesca.cl/portal/615/articles-{aid}_documento.pdf', headers=UA, timeout=90); print('=====', aid, r.status_code, len(r.content))
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        print('pages', len(pdf.pages))
        for i, p in enumerate(pdf.pages[:8]):
            t = p.extract_text() or ''
            print(f'--- page {i + 1}'); print(t[:2200])
            for tb in p.extract_tables()[:3]:
                print('   TABLE', len(tb), [x[:8] for x in tb[:4]])
for aid in [128332, 129116, 129266, 129400, 129771, 127900, 131200]:
    for host in ('https://source.subpesca.cl/portal', 'https://www.subpesca.cl/portal'):
        r = requests.get(f'{host}/616/articles-{aid}_documento.pdf', headers=UA, timeout=90)
        print('REPORT', aid, host, r.status_code, len(r.content), r.headers.get('content-type'))
        if r.status_code == 200 and r.content[:4] == b'%PDF':
            texts, _ = B.pdf_text(r.content)
            print('   p1:', (texts[0] or '')[:300].replace('\n', ' | '))
            print('   parsed:', B.parse_report(aid, texts))
            m = re.search(r'.{0,80}acumulad.{0,120}', '\n'.join(texts)); print('   ctx:', m.group(0) if m else None)
            break
