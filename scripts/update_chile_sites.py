#!/usr/bin/env python3
"""Chili : concessions de salmoniculture (Subpesca, couche publique « Concesiones de Acuicultura ») -> data/chile_sites.json.

Service : https://geoportal.subpesca.cl/server/rest/services/IDE_PUBLICO/SRMPUB_ACUICULTURA/MapServer
Chaque concession : titulaire, especes, region, commune, surface, polygone. On garde les salmonides (saumons, truite),
on ramene chaque polygone a son centre, et on regroupe les titulaires (societes juridiques) par groupe d'entreprises
(cle "holding") pour les relier aux chiffres de Sernapesca. Ce sont des concessions, actives ou non : pas des centres
en production. Un echec ne bloque rien : le fichier precedent est conserve.
"""
import json, re, time, urllib.request, urllib.parse, datetime as dt

BASE = 'https://geoportal.subpesca.cl/server/rest/services/IDE_PUBLICO/SRMPUB_ACUICULTURA/MapServer'
OUT = 'data/chile_sites.json'
UA = {'User-Agent': 'Mozilla/5.0 (saumon dashboard)'}
# titulaire (texte) -> groupe, dans l'ordre : le premier motif qui correspond l'emporte
HOLDINGS = [
    ('Mowi Chile', r'MOWI|MARINE HARVEST'), ('Cermaq Chile', r'CERMAQ'), ('Multiexport', r'MULTI[ -]?X|MULTIEXPORT'),
    ('AquaChile', r'AQUACHILE|MAINSTREAM|AGUAS CLARAS'), ('Blumar', r'BLUMAR'), ('Camanchaca', r'CAMANCHACA'),
    ('Australis', r'AUSTRALIS'), ('Salmones Austral', r'SALMONES AUSTRAL|TRUSAL'), ('Ventisqueros', r'VENTISQUEROS'),
    ('Yadran', r'YADRAN'), ('Cooke Chile', r'COOKE'), ('Invermar', r'INVERMAR'), ('Nova Austral', r'NOVA AUSTRAL'),
    ('Marine Farm', r'MARINE FARM'), ('Salmones Antártica', r'ANTARTICA|ANTÁRTICA'), ('Caleta Bay', r'CALETA BAY'),
    ('Salmones Aysén', r'SALMONES AYSEN|SALMONES AYSÉN'), ('Salmones de Chile', r'SALMONES DE CHILE'),
]
SALMO = re.compile(r'SALM|TRUCHA|ONCORHYNCHUS|SALAR', re.I)

def get(url, params):
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode('utf-8', 'ignore'))

def holding(t):
    for h, rx in HOLDINGS:
        if re.search(rx, t or '', re.I): return h
    return 'Other'

def main():
    status = {}
    try:
        info = get(BASE, {'f': 'json'})
        layers = info.get('layers', [])
        # couche qui porte TITULAR et ESPECIES
        lid = None
        for L in layers:
            meta = get(f"{BASE}/{L['id']}", {'f': 'json'})
            names = {f['name'].upper() for f in meta.get('fields') or []}
            if 'TITULAR' in names and ('ESPECIES' in names or 'T_GRUPOESP' in names): lid, fields = L['id'], names; break
        if lid is None: raise RuntimeError('no layer with TITULAR/ESPECIES: ' + ', '.join(L.get('name', '') for L in layers))
        out_f = [f for f in ['TITULAR', 'ESPECIES', 'T_GRUPOESP', 'REGION', 'COMUNA', 'TOPONIMIO', 'SUPERFICIE', 'N_CODIGOCE', 'T_ESTADOTR', 'ESTADO_UOT'] if f in fields]
        sites, off = [], 0
        while True:
            j = get(f'{BASE}/{lid}/query', {'where': '1=1', 'outFields': ','.join(out_f), 'returnGeometry': 'true', 'outSR': 4326,
                                             'maxAllowableOffset': 0.001, 'resultOffset': off, 'resultRecordCount': 1000, 'f': 'json'})
            feats = j.get('features') or []
            for ft in feats:
                a = {k.upper(): v for k, v in (ft.get('attributes') or {}).items()}
                sp = f"{a.get('ESPECIES') or ''} {a.get('T_GRUPOESP') or ''}"
                if not SALMO.search(sp): continue
                rings = (ft.get('geometry') or {}).get('rings') or []
                pts = [p for r in rings[:1] for p in r]
                if not pts: continue
                lon = sum(p[0] for p in pts) / len(pts); lat = sum(p[1] for p in pts) / len(pts)
                t = (a.get('TITULAR') or '').strip()
                sites.append({'t': t, 'h': holding(t), 'lat': round(lat, 4), 'lon': round(lon, 4), 'r': a.get('REGION'), 'c': a.get('COMUNA'),
                              'n': a.get('TOPONIMIO'), 'sp': (a.get('ESPECIES') or '')[:80], 'ha': a.get('SUPERFICIE'), 'code': a.get('N_CODIGOCE'),
                              'st': a.get('T_ESTADOTR') or a.get('ESTADO_UOT')})
            if not j.get('exceededTransferLimit') and len(feats) < 1000: break
            off += len(feats); time.sleep(0.5)
        status['subpesca'] = f'ok layer {lid}: {len(sites)} salmonid concessions'
        json.dump({'meta': {'generated': dt.date.today().isoformat(), 'source': 'Subpesca, Concesiones de Acuicultura (IDE público)', 'url': BASE, 'status': status,
                            'note': 'concessions (granted or in process), not active farms; position = centre of the polygon; holding = company group matched from the holder name'},
                   'sites': sites}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print('chile sites:', status['subpesca'])
    except Exception as e:
        print(f'chile sites: error {type(e).__name__}: {str(e)[:200]} (previous file kept)')

if __name__ == '__main__':
    main()
