"""Sonde : texte integral des rapports sanitaires officiels (pour l'onglet Disease overview).
Chaque rapport est imprime entre ==DOC nom== et ==/DOC==, page par page."""
import io, re, sys, requests, pdfplumber
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
DOCS = {
    'is_mast_2025': 'https://www.mast.is/static/files/Fiskeldi/arsskyrslur/arsskyrsla-dyralaekna-fiskeldis-2025.pdf',
    'cl_sernapesca_2025': 'https://www.sernapesca.cl/app/uploads/2026/03/Informe-Situacion-Sanitaria-Salmonicultura-Ano-2025.pdf',
    'no_fhr_2025': 'https://www.vetinst.no/rapporter-og-publikasjoner/rapporter/2026/fish-health-report-2025/_/attachment/inline/4e7d310d-0620-439c-a2cf-caac02253620:b124880858959e1f6b61fbe45e1137e7e31fc0f9/Fish%20Health%20Report%202025.pdf',
}
want = sys.argv[1:] or list(DOCS)
for name in want:
    url = DOCS[name]
    try:
        r = requests.get(url, headers=H, timeout=180); r.raise_for_status()
        pdf = pdfplumber.open(io.BytesIO(r.content))
        print(f'==DOC {name}== pages={len(pdf.pages)}')
        for i, p in enumerate(pdf.pages):
            t = (p.extract_text() or '').strip()
            print(f'--- page {i + 1}'); print(t)
        print('==/DOC==')
    except Exception as e:  # noqa: BLE001
        print(name, 'ERREUR', e)
