"""Exploration : donnees ouvertes Aduanas (DUS), Sernapesca (caligus, CAD, SRS), INE regional (bulletins pesca)."""
import requests, re, json, sys
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
def get(u, **k):
    try:
        r = requests.get(u, headers=H, timeout=90, **k); return r
    except Exception as e: print('ERR', u, e); return None
print('===== CKAN datos.gob.cl : Aduanas')
for q in ['exportaciones aduanas 2026', 'registro de exportacion 2026', 'exportaciones 2025 aduana', 'DUS exportacion']:
    r = get('https://datos.gob.cl/api/3/action/package_search', params={'q': q, 'rows': 15})
    if r is not None and r.ok:
        for p in r.json()['result']['results']:
            print(q, '|', p['name'], '|', p['title'], '|', p.get('metadata_modified'), '|', len(p.get('resources', [])))
r = get('https://datos.gob.cl/api/3/action/organization_show', params={'id': 'servicio_nacional_de_aduanas', 'include_datasets': 'true'})
if r is not None and r.ok:
    for p in r.json()['result'].get('packages', [])[:80]: print('ORG', p['name'], '|', p['title'], '|', p.get('metadata_modified'))
print('===== Sernapesca')
for u in ['https://www.sernapesca.cl/?s=caligus', 'https://www.sernapesca.cl/?s=alta+diseminacion', 'https://www.sernapesca.cl/?s=SRS', 'https://www.sernapesca.cl/informes/', 'https://www.sernapesca.cl/manejo-sanitario/acuicultura/programas-sanitarios/', 'https://www.sernapesca.cl/?s=informe+sanitario']:
    r = get(u)
    if r is None: continue
    print('==', u, r.status_code, len(r.text))
    for l in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
        if re.search(r'(?i)caligus|calig|diseminaci|srs|sanitari|\.pdf|\.xlsx|informe', l): print('  ', l)
print('===== INE regional pesca')
for u in ['https://regiones.ine.gob.cl/los-lagos/estadisticas-regionales/economia/pesca', 'https://regiones.ine.gob.cl/aysen/estadisticas-regionales/economia/pesca',
          'https://regiones.ine.gob.cl/magallanes/estadisticas-regionales/economia/pesca', 'https://www.ine.gob.cl/estadisticas/economia/agricultura-agroindustria-y-pesca/pesca',
          'https://regiones.ine.gob.cl/los-lagos/inicio']:
    r = get(u)
    if r is None: continue
    print('==', u, r.status_code, len(r.text))
    for l in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
        if re.search(r'(?i)pesca|bolet|industria|\.pdf|\.xlsx', l): print('  ', l)
