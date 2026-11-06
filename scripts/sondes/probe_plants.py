"""Sonde : plantes de transformation. Chili = liste Sernapesca des plantes autorisees a abattre/transformer des salmonides ;
Norvege = geocodage Kartverket des abattoirs Mattilsynet (FFPP-SA)."""
import io, json, requests, pdfplumber
H = {'User-Agent': 'salmon-dashboard/1.0 (market intelligence; contact via github EmileviardotFO)'}
u = 'https://www.sernapesca.cl/app/uploads/2026/11/listado_de_plantas_autorizadas_salmonidos_v20261102_.pdf'
r = requests.get(u, headers=H, timeout=120); print('sernapesca', r.status_code, len(r.content))
if r.status_code == 200:
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        print('pages', len(pdf.pages))
        for i, p in enumerate(pdf.pages[:3]):
            print('--- page', i); print((p.extract_text() or '')[:2500])
            for tb in (p.extract_tables() or [])[:1]:
                for row in tb[:12]: print('  T', row)
        last = pdf.pages[-1]; print('--- last'); print((last.extract_text() or '')[:1500])
for q in ({'sok': 'Kverva', 'postnummer': '7246'}, {'sok': 'Sandstad', 'postnummer': '7246'}, {'postnummer': '8764', 'treffPerSide': 1}):
    r = requests.get('https://ws.geonorge.no/adresser/v1/sok', params=dict(q, treffPerSide=3), headers=H, timeout=60)
    print('geonorge', q, r.status_code, r.text[:500])
r = requests.get('https://nominatim.openstreetmap.org/search', params={'q': 'Puerto Montt, Chile', 'format': 'json', 'limit': 1}, headers=H, timeout=60)
print('nominatim', r.status_code, r.text[:300])
