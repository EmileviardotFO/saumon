"""Sonde : sources possibles pour l'onglet Feed et pour l'Islande (tableau MAST).

Ecrit dans sonde_out/ ce qui a pu etre lu. Ne modifie rien dans data/.
"""
import base64
import json
import os
import re
import traceback

import requests

OUT = 'sonde_out'
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (salmon dashboard; github.com/EmileviardotFO/saumon)'}


def save(name, obj):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        if isinstance(obj, (dict, list)):
            json.dump(obj, f, ensure_ascii=False, indent=1)
        else:
            f.write(obj)


def essai(nom, fn):
    print(f'=== {nom}')
    try:
        fn()
    except Exception:
        print(traceback.format_exc()[-1500:])


# ---------- 1. Banque mondiale, "Pink Sheet" mensuel (farine de poisson, soja, ble, mais, huiles...) ----------
def pink():
    page = requests.get('https://www.worldbank.org/en/research/commodity-markets', headers=UA, timeout=60).text
    urls = sorted(set(re.findall(r'https?://[^"\']+CMO-Historical-Data-Monthly\.xlsx', page)))
    print('liens trouves :', urls)
    url = urls[0] if urls else 'https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx'
    r = requests.get(url, headers=UA, timeout=120)
    print('xlsx', r.status_code, len(r.content))
    open(os.path.join(OUT, 'pink.xlsx'), 'wb').write(r.content)
    import pandas as pd
    x = pd.ExcelFile(os.path.join(OUT, 'pink.xlsx'))
    print('feuilles :', x.sheet_names)
    for sh in x.sheet_names:
        df = x.parse(sh, header=None, nrows=8)
        print('---', sh); print(df.iloc[:, :12].to_string()[:2500])
    df = x.parse('Monthly Prices', header=None)
    print('derniere ligne :', df.iloc[-1, :6].tolist())


# ---------- 2. FMI, prix des matieres premieres (PCPS) ----------
def imf():
    for code in ['PFISH', 'PSMEA', 'PSOYB', 'PSOIL', 'PWHEAMT', 'PMAIZMT', 'PROIL', 'PPOIL']:
        u = f'https://www.imf.org/external/datamapper/api/v1/{code}'
        r = requests.get(u, headers=UA, timeout=60)
        print(code, r.status_code, r.text[:300].replace('\n', ' '))


# ---------- 3. Islande : tableau de bord MAST (Power BI public) ----------
def mast():
    meta = json.load(open('data/iceland.json', encoding='utf-8'))['meta']
    embeds = [u.strip() for u in str(meta.get('dashboard_embed', '')).split(',') if 'powerbi' in u]
    print(len(embeds), 'rapports Power BI')
    res = []
    for e in embeds:
        r = re.search(r'r=([^&]+)', e).group(1)
        cfg = json.loads(base64.b64decode(r + '=' * (-len(r) % 4)))
        k, t = cfg['k'], cfg['t']
        cl = requests.get(f'https://api.powerbi.com/public/routing/cluster/{t}', headers=UA, timeout=60).json()
        base = cl['FixedClusterUri'].rstrip('/').replace('-redirect', '').replace('global-', '')
        api = base.replace('https://', 'https://').rstrip('/')
        if '.analysis.windows.net' not in api:
            api = api
        h = dict(UA, **{'X-PowerBI-ResourceKey': k, 'Accept': 'application/json'})
        api_host = re.sub(r'https://([^.]+)\.', lambda m: f'https://{m.group(1)}-api.', api, count=1) if '-api.' not in api else api
        mx = None
        for host in (api_host, api):
            try:
                rr = requests.get(f'{host}/public/reports/{k}/modelsAndExploration?preferReadOnlySession=true', headers=h, timeout=60)
                print(host, rr.status_code, len(rr.content))
                if rr.ok:
                    mx = rr.json(); api_ok = host; break
            except Exception as ex:
                print(host, 'erreur', ex)
        if not mx:
            continue
        save(f'mast_{k[:8]}_exploration.json', mx)
        sections = mx.get('exploration', {}).get('sections', [])
        vis = []
        for s in sections:
            for vc in s.get('visualContainers', []):
                try:
                    c = json.loads(vc.get('config', '{}'))
                    sv = c.get('singleVisual', {})
                    vis.append({'section': s.get('displayName'), 'type': sv.get('visualType'),
                                'title': json.dumps(sv.get('vcObjects', {}).get('title', ''))[:200],
                                'query': bool(sv.get('prototypeQuery'))})
                except Exception:
                    pass
        print('pages :', [s.get('displayName') for s in sections])
        print('visuels :', len(vis))
        res.append({'key': k, 'api': api_ok, 'model': [m.get('id') for m in mx.get('models', [])], 'visuals': vis})
    save('mast_resume.json', res)


essai('Pink Sheet', pink)
essai('FMI', imf)
essai('MAST Power BI', mast)
print('fin')
