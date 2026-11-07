"""Sonde GFW Chili : quels jeux de donnees (VMS Chili, aquaculture) et quels wellboats y trouve-t-on ?"""
import os, json, requests
tok = next(v for k, v in os.environ.items() if k.startswith('S_') and v and 'FISH' in k.upper())
H = {'Authorization': f'Bearer {tok.strip()}'}
B = 'https://gateway.api.globalfishingwatch.org/v3'

def g(path, **p):
    r = requests.get(B + path, headers=H, params=p, timeout=90)
    print('GET', path, {k: v for k, v in p.items() if 'date' not in k}, '->', r.status_code)
    if not r.ok: print('  ', r.text[:400])
    return r

# 1. jeux de donnees disponibles (on garde ceux qui parlent du Chili / aquaculture / VMS)
ds = []
for off in range(0, 600, 100):
    r = g('/datasets', limit=100, offset=off)
    if not r.ok: break
    j = r.json(); items = j.get('entries', j if isinstance(j, list) else [])
    if not items: break
    ds += items
print('datasets total', len(ds))
for d in ds:
    s = json.dumps(d).lower()
    if any(w in s for w in ('chile', 'aquacult', 'vms', 'carrier', 'support')):
        print('  DS', d.get('id'), '|', (d.get('name') or '')[:70], '|', d.get('type'))

# 2. recherche de wellboats connus et de mots-cles dans les identites chiliennes
chile_ids = [d['id'] for d in ds if 'chile' in d.get('id', '') and 'identity' in d.get('id', '')]
print('identites chiliennes', chile_ids)
for q in ('WELLBOAT', 'PATAGON', 'ORCA', 'RONJA', 'SITECNA', 'TRANSMARKO', 'AQUA', 'SALMON', 'LIVE FISH'):
    for dsid in ['public-global-vessel-identity:latest'] + [c if ':' in c else c + ':latest' for c in chile_ids[:2]]:
        r = g('/vessels/search', query=q, **{'datasets[0]': dsid}, limit=15)
        if not r.ok: continue
        for e in r.json().get('entries', []):
            si = (e.get('selfReportedInfo') or [{}])[0]
            if si.get('flag') not in ('CHL', None): continue
            cs = [x.get('shiptypes') for x in (e.get('combinedSourcesInfo') or [])][:1]
            print('   ', q, '|', si.get('shipname'), si.get('flag'), si.get('ssvid'), si.get('id'), si.get('transmissionDateFrom'), si.get('transmissionDateTo'), cs, si.get('sourceCode'))

# 3. requete avancee : navires chiliens hors peche dans l'identite chilienne
for dsid in [c if ':' in c else c + ':latest' for c in chile_ids]:
    r = g('/vessels/search', where="flag='CHL'", **{'datasets[0]': dsid}, limit=50)
    if r.ok:
        es = r.json().get('entries', [])
        print(' ', dsid, len(es), 'total', r.json().get('total'))
        for e in es[:30]:
            si = (e.get('selfReportedInfo') or [{}])[0]
            print('    ', si.get('shipname'), si.get('ssvid'), si.get('id'), si.get('transmissionDateTo'), json.dumps(e.get('registryInfo') or [])[:120])
