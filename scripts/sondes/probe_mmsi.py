"""Sonde : MMSI des bronnbater. 1) API BarentsWatch (scope api) : points d'acces navires / bronnbater ;
2) ecoute aisstream 45 min sur la Norvege pour relever indicatif -> MMSI des navires."""
import os, re, json, time, asyncio, requests, gzip, base64
H = {'User-Agent': 'salmon-dashboard/1.0'}
tok = requests.post('https://id.barentswatch.no/connect/token', data={'client_id': os.environ['BW_CLIENT_ID'], 'client_secret': os.environ['BW_CLIENT_SECRET'], 'scope': 'api', 'grant_type': 'client_credentials'}, timeout=60).json().get('access_token')
T = {'Authorization': 'Bearer ' + (tok or ''), **H}
for u in ['https://www.barentswatch.no/bwapi/openapi/v1/openapi.json', 'https://www.barentswatch.no/bwapi/swagger/v1/swagger.json', 'https://www.barentswatch.no/bwapi/openapi/fishhealth/openapi.json']:
    try:
        r = requests.get(u, headers=T, timeout=60); print(u, r.status_code, len(r.text))
        if r.ok:
            paths = list((r.json().get('paths') or {}).keys()); print(len(paths)); print([p for p in paths if re.search(r'(?i)vessel|well|boat|ship|fartoy|bronn|mmsi', p)])
    except Exception as e: print(u, e)
for u in ['https://www.barentswatch.no/bwapi/v1/geodata/fishhealth/vessels', 'https://www.barentswatch.no/bwapi/v1/geodata/fishhealth/wellboats',
          'https://www.barentswatch.no/bwapi/v1/geodata/fishhealth/vessel', 'https://www.barentswatch.no/bwapi/v2/geodata/fishhealth/vessels']:
    try: r = requests.get(u, headers=T, timeout=60); print(u, r.status_code, r.text[:400])
    except Exception as e: print(u, e)
KEY = os.environ.get('AISSTREAM_KEY')
WB = json.load(open('data/wellboats_no.json'))['vessels']
async def run(sec):
    import websockets
    st = {}
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            async with websockets.connect('wss://stream.aisstream.io/v0/stream', max_size=2**24, ping_interval=20) as ws:
                await ws.send(json.dumps({'APIKey': KEY, 'BoundingBoxes': [[[57.8, 4.0], [71.5, 31.5]]], 'FilterMessageTypes': ['ShipStaticData']}))
                while time.time() - t0 < sec:
                    try: m = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                    except asyncio.TimeoutError: continue
                    s = m.get('Message', {}).get('ShipStaticData')
                    if s: st[str(m['MetaData']['MMSI'])] = [s.get('Name', '').strip(), (s.get('CallSign') or '').strip().upper().replace(' ', ''), s.get('Type'), (s.get('Destination') or '').strip()]
        except Exception as e: print('reco', e); await asyncio.sleep(5)
    return st
st = asyncio.run(run(2700))
print('navires', len(st))
hit = {mm: v for mm, v in st.items() if v[1] in WB}
print('liste Mattilsynet trouvee', len(hit), '/', len(WB))
print('==ST=='); print(base64.b64encode(gzip.compress(json.dumps(st).encode())).decode()); print('==/ST==')
