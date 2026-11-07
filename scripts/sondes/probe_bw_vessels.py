"""Sonde : API fiskehelse BarentsWatch (client existant) - bronnbater, positions, visites par lokalitet."""
import os, json, gzip, base64, requests, re
H = {'User-Agent': 'salmon-dashboard/1.0'}
tok = requests.post('https://id.barentswatch.no/connect/token', data={'client_id': os.environ['BW_CLIENT_ID'], 'client_secret': os.environ['BW_CLIENT_SECRET'], 'scope': 'api', 'grant_type': 'client_credentials'}, timeout=60).json()['access_token']
T = {'Authorization': 'Bearer ' + tok, **H}
B = 'https://www.barentswatch.no/bwapi'
spec = requests.get(B + '/openapi/fishhealth/openapi.json', headers=T, timeout=60).json()
for p in spec['paths']:
    if re.search(r'(?i)vessel', p):
        for meth, op in spec['paths'][p].items(): print('PATH', meth.upper(), p, '|', (op.get('summary') or op.get('description') or '')[:200], '| params', [x.get('name') for x in op.get('parameters', [])])
V = requests.get(B + '/v1/geodata/fishhealth/vessels', headers=T, timeout=120).json()
W = [v for v in V if v.get('isWellboat')]; SB = [v for v in V if v.get('isSlaughterBoat')]
print('vessels', len(V), 'wellboats', len(W), 'slaughter boats', len(SB))
print('==WB=='); print(base64.b64encode(gzip.compress(json.dumps({'all_n': len(V), 'wb': W, 'sb': SB}).encode())).decode()); print('==/WB==')
r = requests.get(B + '/v1/geodata/fishhealth/vesselslatestpositions', headers=T, timeout=120); print('latest', r.status_code, r.text[:600])
lp = r.json() if r.ok else []
print('latest n', len(lp))
# visites a une lokalitet : prendre une lokalitet connue (12043 ?) et la semaine 44
for loc in [10865, 13563, 31237, 12904]:
    r = requests.get(f'{B}/v1/geodata/fishhealth/locality/{loc}/vessel/2026/44', headers=T, timeout=60); print('visits', loc, r.status_code, r.text[:800])
    r = requests.get(f'{B}/v1/geodata/fishhealth/locality/{loc}/vessel/2026', headers=T, timeout=60); print('visits year', loc, r.status_code, len(r.text), r.text[:500])
if W:
    mm = W[0]['mmsi']; r = requests.get(f'{B}/v1/geodata/fishhealth/vesseltrack/{mm}/2026/44', headers=T, timeout=60); print('track', mm, r.status_code, len(r.text), r.text[:500])
