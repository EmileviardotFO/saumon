"""Sonde : la cle Global Fishing Watch est-elle bien connectee ? N'affiche jamais sa valeur."""
import json, os, requests

sec = {k[2:]: v for k, v in os.environ.items() if k.startswith('S_') and v}
print('Secrets GFW trouves (noms seulement) :', sorted(sec))
cand = [k for k in sec if any(w in k.upper() for w in ('GFW', 'FISHING', 'GLOBAL'))]
print('Candidats GFW :', cand)
if not cand:
    raise SystemExit('AUCUN secret GFW trouve')
B = 'https://gateway.api.globalfishingwatch.org/v3'
for k in cand:
    tok = (sec[k] or '').strip()
    print(f'\n== {k} : longueur {len(tok)}, commence par JWT ? {tok.startswith("eyJ")}')
    h = {'Authorization': f'Bearer {tok}'}
    for q in ('Ronja', 'Patagonia'):
        r = requests.get(f'{B}/vessels/search', headers=h, timeout=60,
                         params={'query': q, 'datasets[0]': 'public-global-vessel-identity:latest', 'limit': 8})
        print(' recherche', q, '-> HTTP', r.status_code)
        if not r.ok:
            print('  ', r.text[:300]); continue
        for e in r.json().get('entries', [])[:8]:
            si = (e.get('selfReportedInfo') or [{}])[0]
            print('   ', si.get('shipname'), si.get('flag'), si.get('ssvid'), [x.get('shiptypes') for x in (e.get('combinedSourcesInfo') or [])][:1])
    # acces aux evenements (visites de port) : necessaire pour suivre les wellboats
    r = requests.get(f'{B}/datasets', headers=h, timeout=60)
    print(' datasets -> HTTP', r.status_code, r.text[:200] if not r.ok else '')
