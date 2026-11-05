"""Sonde 2 : en-tetes du Pink Sheet, et tableau MAST (Power BI public) en essayant les grappes Power BI d'Europe du Nord."""
import base64
import json
import re
import traceback

import requests

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

try:
    import pandas as pd
    page = requests.get('https://www.worldbank.org/en/research/commodity-markets', headers=UA, timeout=60).text
    url = sorted(set(re.findall(r'https?://[^"\']+CMO-Historical-Data-Monthly\.xlsx', page)))[0]
    open('/tmp/pink.xlsx', 'wb').write(requests.get(url, headers=UA, timeout=120).content)
    df = pd.read_excel('/tmp/pink.xlsx', sheet_name='Monthly Prices', header=None)
    print('PINK colonnes :', [f'{i}:{a} {b}' for i, (a, b) in enumerate(zip(df.iloc[4], df.iloc[5]))])
except Exception:
    print(traceback.format_exc()[-800:])

meta = json.load(open('data/iceland.json', encoding='utf-8'))['meta']
embeds = [u.strip() for u in str(meta.get('dashboard_embed', '')).split(',') if 'powerbi' in u]
regions = ['north-europe', 'west-europe']
letters = ['', '-a', '-b', '-c', '-d', '-e', '-f', '-g', '-h', '-i', '-j', '-k', '-l', '-m', '-n', '-o', '-p']
hosts = []
for rg in regions:
    for L in letters:
        hosts.append(f'https://wabi-{rg}{L}-primary-api.analysis.windows.net' if L else f'https://wabi-{rg}-api.analysis.windows.net')
for e in embeds:
    r = re.search(r'r=([^&]+)', e).group(1)
    cfg = json.loads(base64.b64decode(r + '=' * (-len(r) % 4)))
    k, t = cfg['k'], cfg['t']
    print('=== rapport', k, 'tenant', t, 'c', cfg.get('c'))
    try:
        rr = requests.get(f'https://api.powerbi.com/public/routing/cluster/{t}', headers=dict(UA, **{'X-PowerBI-ResourceKey': k}), timeout=30)
        print('routing', rr.status_code, rr.text[:200])
    except Exception as ex:
        print('routing erreur', ex)
    h = dict(UA, **{'X-PowerBI-ResourceKey': k, 'Accept': 'application/json'})
    found = None
    for host in hosts:
        try:
            x = requests.get(f'{host}/public/reports/{k}/modelsAndExploration?preferReadOnlySession=true', headers=h, timeout=20)
        except Exception:
            continue
        if x.ok:
            found = (host, x.json()); print('OK', host); break
    if not found:
        print('aucune grappe ne repond'); continue
    host, mx = found
    model = mx['models'][0]
    print('modele', model.get('id'), model.get('dbName'))
    for s in mx['exploration']['sections']:
        print('-- page', s.get('displayName'))
        for vc in s.get('visualContainers', []):
            try:
                c = json.loads(vc.get('config', '{}')); sv = c.get('singleVisual', {})
                pq = sv.get('prototypeQuery')
                sel = [x.get('Name') for x in (pq or {}).get('Select', [])]
                print('   ', sv.get('visualType'), '|', sel[:12])
            except Exception:
                pass
    # schema du modele
    try:
        sch = requests.post(f'{host}/public/reports/conceptualschema', headers=dict(h, **{'Content-Type': 'application/json'}),
                            json={'modelIds': [model['id']], 'userPreferredLocale': 'en-US'}, timeout=30)
        print('schema', sch.status_code)
        if sch.ok:
            for ent in sch.json()['schemas'][0]['schema']['Entities']:
                print('   TABLE', ent['Name'], [p['Name'] for p in ent.get('Properties', [])][:40])
    except Exception:
        print(traceback.format_exc()[-500:])
print('fin')
