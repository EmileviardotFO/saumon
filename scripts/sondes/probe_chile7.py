import requests, re, io
import pdfplumber
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
def get(u):
    try: return requests.get(u, headers=H, timeout=120)
    except Exception as e: print('ERR', u, e)
r = get('https://www.sernapesca.cl/informacion-utilidad/listados-y-registros/')
print('== listados', r.status_code if r else None)
links = sorted(set(re.findall(r'href="([^"]+)"', r.text))) if r else []
for l in links:
    if re.search(r'(?i)disemin|calig|cad|srs|piscir|ventana|\.pdf|\.xls', l): print('  ', l)
cad = [l for l in links if re.search(r'(?i)diseminac', l)]
if cad:
    b = get(cad[-1]).content
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        print('CAD pages', len(pdf.pages)); t = '\n'.join((p.extract_text() or '') for p in pdf.pages); print(t[:2500])
for reg in ['los-lagos', 'aysen', 'magallanes']:
    u = f'https://regiones.ine.cl/{reg}/estadisticas-regionales/economia/agricultura-agroindustria-y-pesca/pesca'
    r = get(u); print('== INE', reg, r.status_code if r else None, len(r.text) if r else 0)
    if not r: continue
    for l in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
        if re.search(r'(?i)\.pdf|\.xlsx?|bolet|pesca', l): print('  ', l)
