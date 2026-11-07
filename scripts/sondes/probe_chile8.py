import requests, re, io
import pdfplumber
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
B = 'https://regiones.ine.cl'
def links(u):
    r = requests.get(u, headers=H, timeout=90); print('==', u, r.status_code)
    return sorted(set(re.findall(r'href="([^"]+)"', r.text)))
def show(u, n=3500):
    u = u if u.startswith('http') else B + u
    b = requests.get(u, headers=H, timeout=120).content
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        t = '\n'.join((p.extract_text() or '') for p in pdf.pages)
    print('#### PDF', u, len(b), 'pages', len(pdf.pages)); print('\n'.join(l for l in t.splitlines() if re.search(r'(?i)salm|trucha|coho|atl|total|mes|var', l))[:n])
ll = links(B + '/los-lagos/estadisticas-regionales/economia/agricultura-agroindustria-y-pesca/industria-pesquera-acuicola')
pl = [l for l in ll if '.pdf' in l.lower() or '.xls' in l.lower()]; print('\n'.join(pl[:60]))
if pl: show([l for l in pl if '.pdf' in l.lower()][0])
xl = [l for l in pl if '.xls' in l.lower()]
if xl: print('XLS', xl[:10])
ma = [l for l in links(B + '/magallanes/estadisticas-regionales/economia/agricultura-agroindustria-y-pesca/pesca') if '.pdf' in l]
print('\n'.join(ma)); show(ma[0])
for u in [B + '/aysen/estadisticas-regionales/economia/agricultura-agroindustria-y-pesca/pesca', B + '/aysen/estadisticas-por-tema/agricultura-y-medio-ambiente/pesca']:
    try: print('\n'.join(l for l in links(u) if re.search(r'(?i)\.pdf|bolet', l)))
    except Exception as e: print('ERR', e)
show('https://regiones.ine.cl/documentos/default-source/region-xi/estadisticas/pesca/boletines/2025/bolet%C3%ADn-de-pesca---cuarto-trimestre-2025.pdf')
