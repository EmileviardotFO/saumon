import requests, io, pdfplumber
H = {'User-Agent': 'Mozilla/5.0'}
for u in ['https://regiones.ine.cl/documentos/default-source/region-xii/estadisticas/pesca/boletines/2026/pes_ago_2026_(3-0).pdf',
          'https://regiones.ine.cl/documentos/default-source/region-xi/estadisticas/pesca/boletines/2026/bolet%C3%ADn-de-pesca---segundo-trimestre-2026.pdf']:
    b = requests.get(u, headers=H, timeout=120).content
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ''
            if 'ultivo' in t or 'osecha' in t:
                print('#### page', i + 1, u[-40:]); print(t[:3000])
