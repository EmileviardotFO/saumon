"""Sonde : AIS BarentsWatch (scope ais) + liste Mattilsynet des bronnbater."""
import os, re, json, gzip, base64, requests, time
H = {'User-Agent': 'salmon-dashboard/1.0'}
def dump(tag, obj):
    b = base64.b64encode(gzip.compress(json.dumps(obj, ensure_ascii=False).encode())).decode()
    print(f'=={tag}=='); print(b); print(f'==/{tag}==')
tok = requests.post('https://id.barentswatch.no/connect/token', data={'client_id': os.environ['BW_CLIENT_ID'], 'client_secret': os.environ['BW_CLIENT_SECRET'], 'scope': 'ais', 'grant_type': 'client_credentials'}, timeout=60)
print('token', tok.status_code, tok.text[:200] if tok.status_code != 200 else 'ok')
T = {'Authorization': 'Bearer ' + tok.json().get('access_token', '')} if tok.ok else {}
out = {}
for u in ['https://live.ais.barentswatch.no/swagger/v1/swagger.json', 'https://historic.ais.barentswatch.no/swagger/v1/swagger.json',
          'https://live.ais.barentswatch.no/index.html', 'https://historic.ais.barentswatch.no/index.html', 'https://historic.ais.barentswatch.no/swagger/index.html', 'https://live.ais.barentswatch.no/swagger/index.html']:
    try:
        r = requests.get(u, headers=H, timeout=60); print(u, r.status_code, len(r.text)); out[u] = r.text[:300000]
    except Exception as e: print(u, e)
dump('SWAGGER', out)
# live : derniers messages combines (tous les navires) -> on garde un echantillon et les types
try:
    r = requests.get('https://live.ais.barentswatch.no/v1/latest/combined', headers={**H, **T}, timeout=180)
    print('latest/combined', r.status_code, len(r.content)); j = r.json() if r.ok else []
    print('n', len(j)); print(j[:2])
    W = [x for x in j if re.search(r'(?i)\b(ro |ronja|gaso|gåsø|seihav|novatrans|steigen|bjørg|bjorg|aqua|br[øo]nn|well|frøy|froy|viking|sølvtrans|solvtrans|vestfjord|tanja|helen|harvest|smolt|kvitbj|fjord)', x.get('name') or '')]
    dump('LIVE_SAMPLE', {'n': len(j), 'keys': list(j[0].keys()) if j else [], 'types': {str(k): sum(1 for x in j if x.get('shipType') == k) for k in set(x.get('shipType') for x in j)}, 'cand': W[:800]})
except Exception as e: print('live err', e)
# historique : 24 h d'un navire connu (Ronja Storm 257...) via nom
try:
    r = requests.get('https://historic.ais.barentswatch.no/v1/historic/trackslast24hours/257111020', headers={**H, **T}, timeout=120); print('hist24', r.status_code, r.text[:400])
except Exception as e: print('hist err', e)
# Mattilsynet : liste des transportenheter
for u in ['https://www.mattilsynet.no/godkjente-produkter-og-virksomheter/transportenheter-godkjent-for-transport-av-levende-akvakulturdyr',
          'https://mattilsynet.no/godkjente-produkter-og-virksomheter/transportenheter-godkjent-for-transport-av-levende-akvakulturdyr']:
    try:
        r = requests.get(u, headers=H, timeout=60); print(u, r.status_code, len(r.text))
        links = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx|xls|csv|pdf)[^"]*)"', r.text)))
        print(links[:20]); dump('MT_PAGE', {'html': r.text[:400000], 'links': links})
        for l in links[:3]:
            l = requests.compat.urljoin(u, l); rr = requests.get(l, headers=H, timeout=60); print(l, rr.status_code, len(rr.content))
            dump('MT_FILE', {'url': l, 'b64': base64.b64encode(rr.content).decode()})
        break
    except Exception as e: print(u, e)
