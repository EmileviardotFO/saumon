#!/usr/bin/env python3
"""
Flux de saumon dans l'Union europeenne, depuis Eurostat Comext (DS-045409,
commerce exterieur mensuel par produit CN8), pour l'onglet "EU flows".

  Amont : importations de chacun des 27 pays de l'UE, par pays d'origine.
  Aval  : exportations des pays de transformation (Danemark, Pologne,
          Pays-Bas) par pays de destination.
  Formes suivies (CN8) : entier frais, entier congele, filets frais, filets
  congeles, autre chair fraiche de salmonides, fume, prepare/conserve.

Requetes SDMX-CSV (format valide par la sonde du 28.10.2026) :
  .../sdmx/2.1/data/DS-045409/M.{declarant}.{partenaire}.{produits}.{flux}.QUANTITY_IN_100KG+VALUE_IN_EUROS
Partenaire vide = tous ; si le serveur le refuse, on repasse avec la liste
explicite des pays.

Sortie : data/eurostat.json (fichier a part, charge par l'onglet seulement) :
  rows = [annee*100+mois, declarant, partenaire, indice produit, flux (1 import, 2 export), tonnes, milliers d'euros]
Les partenaires qui pesent moins de 0,5 % des echanges d'un declarant (sur
toute la periode) sont regroupes sous "ZZ" (autres), pour garder un fichier
leger. Un passage ne retelecharge rien si Eurostat n'a pas publie de mise a
jour depuis le precedent.

    python3 scripts/update_eurostat.py [--force]
"""
import collections
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'eurostat.json')
BASE = 'https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/DS-045409'
UA = 'Mozilla/5.0 (X11; Linux x86_64) saumon-dashboard (github.com/emileviardotfo/saumon)'
START = '2021-01'
PRODUCTS = [('03021400', 'Fresh whole'), ('03031300', 'Frozen whole'), ('03044100', 'Fresh fillets'),
            ('03048100', 'Frozen fillets'), ('03045200', 'Other fresh salmonid meat'),
            ('03054100', 'Smoked'), ('16041100', 'Prepared / preserved')]
EU27 = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'HU', 'IE', 'IT',
        'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK']
HUBS = ['DK', 'PL', 'NL']
MIN_SHARE = 0.005
# pays producteurs jamais regroupes, meme petits (vue "par origine" de l'onglet)
ORIGINS = ['NO', 'FO', 'GB', 'IS', 'CL', 'AU', 'CA', 'US', 'NZ', 'TR', 'CN', 'VN', 'TH', 'UA', 'RU']


def get(url, tries=3):
    for a in range(tries):
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/vnd.sdmx.data+csv'})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (404,):
                return 404, ''
            if e.code < 500 and e.code != 429:
                return e.code, e.read().decode('utf-8', 'replace')[:300]
        except Exception as e:
            print('   ', repr(e)[:120])
        time.sleep(10 * (a + 1))
    return None, ''


def query(reporter, flow, partners=''):
    prods = '+'.join(p for p, _ in PRODUCTS)
    url = f'{BASE}/M.{reporter}.{partners}.{prods}.{flow}.QUANTITY_IN_100KG+VALUE_IN_EUROS?startPeriod={START}&format=SDMX-CSV'
    st, txt = get(url)
    return st, txt


def parse(txt):
    """-> {(ym, partner, prod_idx): [tonnes, keur]}"""
    pidx = {p: i for i, (p, _) in enumerate(PRODUCTS)}
    out = collections.defaultdict(lambda: [0.0, 0.0])
    last_update = None
    for r in csv.DictReader(io.StringIO(txt)):
        part = r.get('partner') or ''
        if len(part) != 2 or part in ('EU', 'EA'):           # agregats exclus
            continue
        try:
            v = float(r.get('OBS_VALUE') or 0)
        except ValueError:
            continue
        y, m = r['TIME_PERIOD'].split('-')
        key = (int(y) * 100 + int(m), part, pidx[r['product']])
        if r['indicators'] == 'QUANTITY_IN_100KG':
            out[key][0] += v / 10.0                         # 100 kg -> tonnes
        else:
            out[key][1] += v / 1000.0                       # euros -> milliers d'euros
        last_update = last_update or r.get('LAST UPDATE')
    return out, last_update


def all_partners():
    # liste explicite des pays (code list CXT_FREE_ISO d'Eurostat), si le joker est refuse
    return ['AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AN', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM', 'CN', 'CO', 'CR', 'CS', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DD', 'DE', 'DJ', 'DK', 'DM', 'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY', 'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IN', 'IO', 'IQ', 'IR', 'IS', 'IT', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN', 'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV', 'LY', 'MA', 'MD', 'ME', 'MG', 'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM', 'PN', 'PS', 'PT', 'PW', 'PY', 'PZ', 'QA', 'QP', 'QQ', 'QR', 'QS', 'QT', 'QU', 'QV', 'QW', 'QX', 'QY', 'QZ', 'RE', 'RO', 'RU', 'RW', 'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SU', 'SV', 'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TP', 'TR', 'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VD', 'VE', 'VG', 'VI', 'VN', 'VU', 'WF', 'WS', 'XA', 'XB', 'XC', 'XI', 'XK', 'XL', 'XM', 'XO', 'XP', 'XR', 'XS', 'XU', 'XZ', 'YD', 'YE', 'YT', 'YU', 'ZA', 'ZM', 'ZW']


def main():
    force = '--force' in sys.argv
    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else None
    # 1. Eurostat a-t-il publie depuis le dernier passage ? (requete minuscule)
    st, txt = get(f'{BASE}/M.PL.NO.03021400.1.QUANTITY_IN_100KG?lastNObservations=1&format=SDMX-CSV')
    probe_update = None
    if st == 200:
        for r in csv.DictReader(io.StringIO(txt)):
            probe_update = r.get('LAST UPDATE'); break
    if old and not force and probe_update and old['meta'].get('source_update') == probe_update:
        print(f'Eurostat inchange depuis le dernier passage ({probe_update}) : rien a faire.')
        return
    print(f'Mise a jour Eurostat : {probe_update}')

    rows, failed = [], []
    jobs = [(r, 1) for r in EU27] + [(h, 2) for h in HUBS]
    for reporter, flow in jobs:
        st, txt = query(reporter, flow)
        if st != 200:
            print(f'  {reporter} flux {flow} : {st}, nouvel essai avec la liste des pays')
            agg = collections.defaultdict(lambda: [0.0, 0.0])
            ok = False
            parts = all_partners()
            for i in range(0, len(parts), 120):
                st2, txt2 = query(reporter, flow, '+'.join(parts[i:i + 120]))
                if st2 == 200:
                    ok = True
                    d, _ = parse(txt2)
                    for k, v in d.items():
                        agg[k][0] += v[0]; agg[k][1] += v[1]
            if not ok:
                failed.append(f'{reporter}-{flow}')
                continue
            data = agg
        else:
            data, _ = parse(txt)
        # partenaires marginaux regroupes en "ZZ"
        tot = sum(v[0] for v in data.values()) or 1.0
        by_part = collections.Counter()
        for (ym, p, i), v in data.items():
            by_part[p] += v[0]
        keep = {p for p, t in by_part.items() if t / tot >= MIN_SHARE or (flow == 1 and p in ORIGINS)}
        merged = collections.defaultdict(lambda: [0.0, 0.0])
        for (ym, p, i), v in data.items():
            k = (ym, p if p in keep else 'ZZ', i)
            merged[k][0] += v[0]; merged[k][1] += v[1]
        n0 = len(rows)
        for (ym, p, i), (t, ke) in sorted(merged.items()):
            if t < 0.05 and ke < 0.5:
                continue
            rows.append([ym, reporter, p, i, flow, round(t, 1), round(ke, 1)])
        print(f'  {reporter} {"imports" if flow == 1 else "exports"} : {len(rows) - n0} lignes, {len(keep)} partenaires gardes, {tot:,.0f} t')
        time.sleep(1)

    if not rows:
        sys.exit('Aucune donnee Eurostat recue.')
    if old and failed:
        # on garde les anciennes lignes des declarants en echec
        bad = {tuple(f.split('-')) for f in failed}
        rows += [r for r in old['rows'] if (r[1], str(r[4])) in bad]
    last = max(r[0] for r in rows)
    out = {
        'meta': {'source': 'Eurostat Comext DS-045409 (EU trade by CN8, monthly)', 'source_update': probe_update,
                 'fetched': dt.date.today().isoformat(), 'start': START, 'last_period': last,
                 'products': [n for _, n in PRODUCTS], 'cn8': [p for p, _ in PRODUCTS],
                 'reporters_up': EU27, 'hubs': HUBS, 'origins': ORIGINS, 'failed': failed,
                 'cols': ['ym', 'reporter', 'partner', 'product', 'flow', 'tonnes', 'k_eur'],
                 'note': 'partner ZZ = partners below 0.5% of the reporter total, grouped'},
        'rows': rows,
    }
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'{len(rows)} lignes, dernier mois {last}, echecs : {failed or "aucun"}')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
