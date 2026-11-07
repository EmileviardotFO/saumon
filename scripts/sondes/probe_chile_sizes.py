"""Sonde : calibres dans les descriptions des exportations chiliennes de poisson entier (DUS 2026-09),
et couverture AIS (aisstream) des zones salmonicoles chiliennes pendant 3 minutes."""
import collections, os, re, subprocess, sys, json, time, asyncio
sys.path.insert(0, 'scripts')
subprocess.run('sudo apt-get install -y -qq p7zip-full p7zip-rar >/dev/null 2>&1', shell=True)
import build_chile_customs as B
res = B.resources(); ym = max(res); print('mois', ym)
rows = B.read_month(res[ym]['url'])
c = collections.Counter(); kgs = collections.Counter()
for x in rows:
    hs = x[B.C_HS].strip()
    if hs[:4] not in ('0302', '0303'): continue
    ref, _, desc = x[B.C_NOM].partition('~')
    sp = B.species(desc, hs); key = f'{sp}|{hs[:4]}|{desc.strip()[:90]}'
    c[key] += 1; kgs[key] += B.num(x[B.C_QTY])
for k, v in kgs.most_common(150): print(f'{v/1000:9.1f} t  {c[k]:4d}  {k}')
# autres colonnes possibles : imprime une ligne complete
print('LIGNE', [(i, v) for i, v in enumerate(rows[0]) if v.strip()])

KEY = os.environ.get('AISSTREAM_KEY') or os.environ.get('AISTREAM_KEY')
async def ais(sec=180):
    import websockets
    box = [[-47.0, -75.5], [-41.0, -72.0]]
    seen = {}; n = 0; static = {}
    async with websockets.connect('wss://stream.aisstream.io/v0/stream', max_size=2**24) as ws:
        await ws.send(json.dumps({'APIKey': KEY, 'BoundingBoxes': [box]}))
        t0 = time.time()
        while time.time() - t0 < sec:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError: print('rien depuis 30 s'); continue
            md = m.get('MetaData', {}); n += 1; seen[md.get('MMSI')] = (md.get('ShipName', '').strip(), round(md.get('latitude', 0), 2), round(md.get('longitude', 0), 2))
            if m.get('MessageType') == 'ShipStaticData':
                s = m['Message']['ShipStaticData']; static[md.get('MMSI')] = [s.get('Name', '').strip(), s.get('Type')]
    print('AIS Chiloe-Aysen :', n, 'messages,', len(seen), 'navires en', sec, 's')
    for k, v in list(seen.items())[:80]: print(' ', k, v, static.get(k))
if KEY:
    try: asyncio.run(ais())
    except Exception as e: print('AIS erreur', e)
