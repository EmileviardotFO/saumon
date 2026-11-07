#!/usr/bin/env python3
"""Importations suisses de saumon, par numero de tarif (TN8) et pays, chaque mois, depuis 2018.

Source : Office federal de la douane et de la securite des frontieres (OFDF / BAZG), donnees ouvertes
« Marchandises : commerce exterieur par numero de tarif / pays » (les memes chiffres que SwissImpex),
https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_IMP_en/TN8_IMP_en.zip (un CSV de ~8,6 Go, lu en flux).
Pays = pays d'origine (regle suisse). Sortie : data/swiss_imports.json
"""
import io, os, json, zipfile, datetime as dt, tempfile, requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'swiss_imports.json')
URL = 'https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_IMP_en/TN8_IMP_en.zip'
TN6 = {'0302.13': 'Pacific salmon, fresh', '0302.14': 'Atlantic salmon, fresh whole', '0303.11': 'Sockeye, frozen', '0303.12': 'Other Pacific salmon, frozen',
       '0303.13': 'Atlantic salmon, frozen whole', '0304.41': 'Salmon fillets, fresh', '0304.52': 'Salmonid pieces, fresh', '0304.81': 'Salmon fillets, frozen',
       '0305.41': 'Salmon, smoked', '1604.11': 'Salmon, prepared or preserved'}
KEYS = tuple(f';{k};' for k in TN6)
FROM = 2018


def main():
    tmp = tempfile.NamedTemporaryFile(suffix='.zip', delete=False).name
    with requests.get(URL, stream=True, timeout=600, headers={'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}) as r:
        r.raise_for_status()
        with open(tmp, 'wb') as f:
            for ch in r.iter_content(1 << 20): f.write(ch)
    z = zipfile.ZipFile(tmp); name = z.namelist()[0]
    rows, codes, upd, prov = {}, {}, '', set()
    with z.open(name) as f:
        txt = io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace')
        H = next(txt).rstrip('\n').split(';'); ix = {h: i for i, h in enumerate(H)}
        for line in txt:
            if not any(k in line for k in KEYS):
                continue
            c = line.rstrip('\n').split(';')
            if c[ix['Traffic_direction']] != 'I' or c[ix['Tariffnumber6']] not in TN6 or int(c[ix['year']]) < FROM:
                continue
            ym = int(c[ix['year']]) * 100 + int(c[ix['month']]); tn8 = c[ix['Tariffnumber8']]; iso = c[ix['Country_isoAlpha2']] or c[ix['Country_txt']]
            codes[tn8] = c[ix['Tariffnumber8_txt']]
            fl = lambda k: float(c[ix[k]] or 0)
            k = (ym, tn8, iso); x = rows.setdefault(k, [0.0, 0.0, 0.0]); x[0] += fl('Quantity_kg'); x[1] += fl('Value_CHF'); x[2] += fl('Value_EUR')
            upd = max(upd, c[ix['Update']][:10]);
            if c[ix['status']] != 'def': prov.add(ym)
    os.unlink(tmp)
    out = {'meta': {'source': 'Federal Office for Customs and Border Security (FOCBS/BAZG), open data: foreign trade by tariff number and country (same figures as Swiss-Impex)',
                    'url': 'https://opendata.swiss/en/dataset/waren-aussenhandel-nach-tarifnummer-land', 'fetched': dt.date.today().isoformat(), 'updated': upd,
                    'country': 'country of origin', 'cols': ['ym', 'tn8', 'iso2', 'kg', 'chf', 'eur'], 'tn6': TN6, 'tn8': codes,
                    'last': max(k[0] for k in rows), 'provisional': sorted(prov)},
           'rows': [[k[0], k[1], k[2], round(v[0]), round(v[1]), round(v[2])] for k, v in sorted(rows.items())]}
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('lignes', len(out['rows']), 'dernier mois', out['meta']['last'], 'provisoires', out['meta']['provisional'][-6:])


if __name__ == '__main__':
    main()
