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

def get(url, params, tries=3):
    last = None
    for i in range(tries):
        try:
            # POST : avec des centaines d'identifiants, l'adresse GET depasse ~2 000 caracteres et Subpesca repond 404 (vu le 2 nov. 2026)
            req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers=dict(UA, **{'Content-Type': 'application/x-www-form-urlencoded'}))
            with urllib.request.urlopen(req, timeout=120) as r: j = json.loads(r.read().decode('utf-8', 'ignore'))
            if isinstance(j, dict) and j.get('error'): raise RuntimeError(f"ArcGIS error {j['error'].get('code')}: {j['error'].get('message')}")
            return j
        except Exception as e:
            last = e; time.sleep(5 * (i + 1))
    raise last

def holding(t):
    for h, rx in HOLDINGS:
        if re.search(rx, t or '', re.I): return h
    return 'Other'

# Subpesca prefixe les noms de champs par la table d'origine (REP_SUBPESCA2.ADM_UOT.PULLINQUE4_T_ACUICULTURA.TITULAR,
# novembre 2026) et certains noms ont change : on compare sur le dernier segment, avec ces equivalences.
ALIASES = {'T_GRUPOESP': ['T_GRUPOESP', 'T_GRUPOESPECIE'], 'SUPERFICIE': ['SUPERFICIE', 'SUPERFICIEPOLIGONO'],
           'N_CODIGOCE': ['N_CODIGOCE', 'N_CODIGOCENTRO'], 'T_ESTADOTR': ['T_ESTADOTR', 'T_ESTADOTRAMITE'],
           'ESTADO_UOT': ['ESTADO_UOT', 'C_ESTADOUOT']}
WANTED = ['TITULAR', 'ESPECIES', 'T_GRUPOESP', 'REGION', 'COMUNA', 'TOPONIMIO', 'SUPERFICIE', 'N_CODIGOCE', 'T_ESTADOTR', 'ESTADO_UOT']

def short(name): return (name or '').split('.')[-1].upper()

def field_map(names):
    """noms courts attendus -> nom complet du service"""
    by_short = {short(n): n for n in names}
    out = {}
    for w in WANTED:
        for a in ALIASES.get(w, [w]):
            if a in by_short: out[w] = by_short[a]; break
    return out

def site_of(ft):
    raw = {short(k): v for k, v in (ft.get('attributes') or {}).items()}
    a = {w: next((raw[x] for x in ALIASES.get(w, [w]) if x in raw), None) for w in WANTED}
    sp = f"{a.get('ESPECIES') or ''} {a.get('T_GRUPOESP') or ''}"
    if not SALMO.search(sp): return None
    rings = (ft.get('geometry') or {}).get('rings') or []
    pts = [p for r in rings[:1] for p in r]
    if not pts: return None
    lon = sum(p[0] for p in pts) / len(pts); lat = sum(p[1] for p in pts) / len(pts)
    t = (a.get('TITULAR') or '').strip()
    st = lambda v: v.strip() if isinstance(v, str) else v
    return {'t': t, 'h': holding(t), 'lat': round(lat, 4), 'lon': round(lon, 4), 'r': st(a.get('REGION')), 'c': st(a.get('COMUNA')),
            'n': st(a.get('TOPONIMIO')), 'sp': (a.get('ESPECIES') or '')[:80], 'ha': a.get('SUPERFICIE'), 'code': a.get('N_CODIGOCE'),
            'st': a.get('T_ESTADOTR') or a.get('ESTADO_UOT')}

def download(status):
    info = get(BASE, {'f': 'json'})
    layers = info.get('layers', [])
    status['layers'] = ', '.join(f"{L['id']}:{L.get('name', '')}" for L in layers)[:300]
    lid, fm, maxrec = None, {}, 1000
    # couche des concessions (pas des demandes) qui porte TITULAR et ESPECIES ; les couches "Solicitudes" passent en dernier
    for L in sorted(layers, key=lambda L: 'solicitud' in (L.get('name') or '').lower()):
        meta = get(f"{BASE}/{L['id']}", {'f': 'json'})
        m = field_map([f['name'] for f in meta.get('fields') or []])
        if 'TITULAR' in m and ('ESPECIES' in m or 'T_GRUPOESP' in m):
            lid, fm, maxrec = L['id'], m, min(int(meta.get('maxRecordCount') or 1000), 1000); break
    if lid is None: raise RuntimeError('no layer with TITULAR/ESPECIES among: ' + status['layers'])
    status['layer'] = f"{lid}: {next((L.get('name') for L in layers if L['id'] == lid), '')}"
    out_f = ','.join(fm.values())
    q = f'{BASE}/{lid}/query'
    geo = {'outFields': out_f, 'returnGeometry': 'true', 'outSR': 4326, 'maxAllowableOffset': 0.001, 'f': 'json'}
    # filtre cote serveur (salmonides) ; si le serveur le refuse, tout est demande et filtre ici
    where = (f"UPPER({fm['ESPECIES']}) LIKE '%SALM%' OR UPPER({fm['ESPECIES']}) LIKE '%TRUCHA%'" +
             (f" OR UPPER({fm['T_GRUPOESP']}) LIKE '%SALM%'" if 'T_GRUPOESP' in fm else '')) if 'ESPECIES' in fm else '1=1'
    try: ids = get(q, {'where': where, 'returnIdsOnly': 'true', 'f': 'json'}).get('objectIds') or []
    except Exception: where = '1=1'; ids = get(q, {'where': where, 'returnIdsOnly': 'true', 'f': 'json'}).get('objectIds') or []
    if not ids: raise RuntimeError(f'layer {lid}: no object ids for where={where}')
    ids = sorted(ids); sites = []
    # par lots d'identifiants : marche meme si le serveur ne gere pas la pagination (resultOffset)
    for i in range(0, len(ids), min(maxrec, 500)):
        j = get(q, dict(geo, objectIds=','.join(map(str, ids[i:i + 500]))))
        for ft in j.get('features') or []:
            x = site_of(ft)
            if x: sites.append(x)
        time.sleep(0.5)
    status['subpesca'] = f'ok layer {lid}: {len(ids)} objects queried, {len(sites)} salmonid concessions'
    return sites

def main():
    status = {}; today = dt.date.today().isoformat()
    try: old = json.load(open(OUT, encoding='utf-8'))
    except Exception: old = None
    meta = {'source': 'Subpesca, Concesiones de Acuicultura (IDE público)', 'url': BASE,
            'note': 'concessions (granted or in process), not active farms; position = centre of the polygon; holding = company group matched from the holder name'}
    try:
        sites = download(status)
        if not sites: raise RuntimeError('no salmonid concession returned')
        json.dump({'meta': dict(meta, generated=today, status=status), 'sites': sites}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print('chile sites:', status['subpesca'])
    except Exception as e:
        err = f'{type(e).__name__}: {str(e)[:240]}'
        print(f'chile sites: error {err}'); print('  ', status)
        # on garde les concessions deja telechargees ; sinon un fichier vide qui affiche l'erreur sur la page
        if old and old.get('sites'):
            old.setdefault('meta', {})['last_error'] = {'date': today, 'error': err}
            json.dump(old, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        else:
            json.dump({'meta': dict(meta, generated=None, last_error={'date': today, 'error': err}, status=status), 'sites': []},
                      open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        raise SystemExit(1)   # l'etape apparait en echec dans Actions (sans bloquer le reste : continue-on-error)

if __name__ == '__main__':
    main()
