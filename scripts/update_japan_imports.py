#!/usr/bin/env python3
"""
Importations japonaises de saumon et de truite, par forme et par pays d'origine, chaque mois,
d'apres les declarations du Japon a l'ONU (UN Comtrade, API publique sans cle) : poids net
(poids de produit, comme les douanes japonaises) et valeur CAF en dollars.

    python3 scripts/update_japan_imports.py            # met a jour data/japan_imports.json
    python3 scripts/update_japan_imports.py --depuis 2019

Le Japon declare avec deux a trois mois de retard. Chaque passage ne retelecharge que l'annee en
cours et la precedente (revisions) ; les annees plus anciennes restent en cache dans le JSON.
Une cle Comtrade gratuite (secret COMTRADE_KEY) leve les limites de l'API publique : facultative.
"""
import argparse
import datetime as dt
import io
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'japan_imports.json')
PUBLIC = 'https://comtradeapi.un.org/public/v1/preview/C/M/HS'
KEYED = 'https://comtradeapi.un.org/data/v1/get/C/M/HS'
JAPON = 392

# code SH6 -> (espece, forme)
CODES = {
    '030214': ('Atlantic salmon', 'fresh whole'), '030211': ('Trout', 'fresh whole'),
    '030213': ('Pacific salmon', 'fresh whole'),
    '030311': ('Sockeye', 'frozen whole'), '030312': ('Pacific salmon (coho, chum...)', 'frozen whole'),
    '030313': ('Atlantic salmon', 'frozen whole'), '030314': ('Trout', 'frozen whole'),
    '030441': ('Salmon (Atlantic + Pacific)', 'fresh fillet'), '030442': ('Trout', 'fresh fillet'),
    '030481': ('Salmon (Atlantic + Pacific)', 'frozen fillet'), '030482': ('Trout', 'frozen fillet'),
    '030541': ('Salmon', 'smoked'),
    '030452': ('Salmonids', 'fresh trimmings & pieces'), '030399': ('All fish', 'frozen heads, tails, fins & offal'),
}
# codes pays M49 -> ISO2 (les principaux ; les autres gardent leur code)
PAYS = {152: 'CL', 578: 'NO', 643: 'RU', 842: 'US', 234: 'FO', 36: 'AU', 124: 'CA', 352: 'IS', 826: 'GB',
        792: 'TR', 208: 'DK', 156: 'CN', 704: 'VN', 764: 'TH', 360: 'ID', 554: 'NZ', 251: 'FR', 276: 'DE',
        528: 'NL', 616: 'PL', 410: 'KR', 490: 'TW', 0: 'WORLD'}


def appel(codes, periodes):
    cle = os.environ.get('COMTRADE_KEY')
    params = {'reporterCode': JAPON, 'flowCode': 'M', 'period': ','.join(periodes), 'cmdCode': ','.join(codes),
              'includeDesc': 'true'}
    url = (KEYED if cle else PUBLIC) + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'suivi-salmonicole/1.0', **({'Ocp-Apim-Subscription-Key': cle} if cle else {})})
    for essai in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=90).read().decode('utf-8')).get('data') or []
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and essai < 3: time.sleep(30 * (essai + 1)); continue
            raise
    return []


def lignes(data):
    """-> [[ym, hs6, origine, kg, usd]] ; ignore le total monde et les doublons de mode de transport."""
    out = {}
    for r in data:
        p = int(r.get('partnerCode') or 0)
        if p == 0: continue
        if (r.get('motCode') not in (None, 0)) or (r.get('customsCode') not in (None, 'C00')) or (r.get('partner2Code') not in (None, 0)):
            continue                                               # garder seulement les totaux toutes modalites
        kg = r.get('netWgt') or r.get('qty') or 0
        usd = r.get('cifvalue') or r.get('primaryValue') or 0
        cle = (int(r['period']), str(r['cmdCode']), PAYS.get(p, str(p)))
        x = out.setdefault(cle, [0.0, 0.0]); x[0] += float(kg or 0); x[1] += float(usd or 0)
    return [[k[0], k[1], k[2], round(v[0]), round(v[1])] for k, v in sorted(out.items())]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--depuis', type=int, default=2019); a = ap.parse_args()
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'rows': []}
    an = dt.date.today().year
    a_tirer = [y for y in range(a.depuis, an + 1) if y >= an - 1 or not any(r[0] // 100 == y for r in ancien['rows'])]
    garde = [r for r in ancien['rows'] if r[0] // 100 not in a_tirer]
    neuves, echecs = [], []
    for y in a_tirer:
        # l'API publique (preview) n'accepte qu'un mois par appel : tous les codes d'un mois en une fois
        # (comme update_national_trade.py, qui fonctionne) ; environ 250 lignes par mois, sous la limite de 500
        for m in range(1, 13):
            if dt.date(y, m, 1) > dt.date.today(): break
            per = f'{y}{m:02d}'
            try:
                rows = appel(list(CODES), [per])
                neuves += lignes(rows)
                if len(rows) >= 500: echecs.append(f'{per} : 500 lignes, limite de la preview atteinte')
            except Exception as e:  # noqa: BLE001
                echecs.append(f'{per} : {e}')
            time.sleep(1.2)
    rows = sorted(garde + neuves)
    if not rows: raise SystemExit('aucune donnee recue de Comtrade : ' + '; '.join(echecs[:3]))
    meta = {'fetched': dt.date.today().isoformat(), 'source': 'UN Comtrade, imports reported by Japan (HS6, monthly)',
            'url': PUBLIC, 'cols': ['ym', 'hs6', 'origin', 'kg', 'usd_cif'], 'codes': {k: list(v) for k, v in CODES.items()},
            'first': rows[0][0], 'last': max(r[0] for r in rows), 'failed': echecs[:20]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': meta, 'rows': rows}, ensure_ascii=False, separators=(',', ':')))
    print(f"data/japan_imports.json : {len(rows)} lignes, {meta['first']} -> {meta['last']}" + (f", {len(echecs)} appels en echec" if echecs else ''))
    if echecs: print('  appels en echec :', '; '.join(echecs[:8]))
    if echecs and not neuves: raise SystemExit(1)


if __name__ == '__main__':
    main()
