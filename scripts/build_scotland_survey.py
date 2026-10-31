#!/usr/bin/env python3
"""Ecosse : enquete annuelle officielle (Scottish Fish Farm Production Survey, tableaux complementaires).

Le tableur "...supplementary-tables.xlsx" (publie chaque septembre par le Marine Directorate) est depose a la main
dans xlsx/scotland/. Ce script en tire les series longues et les ajoute a data/scotland_survey.json, sans toucher
aux champs saisis a la main depuis le rapport (cle "meta", "smolts_to_sea"...).
  - production annuelle depuis 1979 et estimation de l'annee suivante (tableaux 24 et 35) ;
  - production par zone de production, par stade (annee 0, grilse, pre-salmon, 2 ans) et poids moyens (tableau 35) ;
  - survie de chaque classe d'age de smolts (tableau 28) ;
  - smolts mis en mer, produits, et estimation faite l'annee precedente (tableau 19).
"""
import glob, json, os
import openpyxl

SRC = sorted(glob.glob('xlsx/scotland/*supplementary*.xlsx'), key=os.path.getmtime)
OUT = 'data/scotland_survey.json'

def num(v):
    if v in (None, '', 'Not applicable'): return None
    try: return float(str(v).replace(',', ''))
    except ValueError: return None

def rows(wb, name):
    r = list(wb[name].iter_rows(values_only=True))
    h = next(i for i, x in enumerate(r) if x and x[0] in ('Year', 'Region', 'Year of smolt input', 'Year class'))
    return r[h + 1:]

def main():
    if not SRC: print('scotland survey: no supplementary tables in xlsx/scotland/, nothing to do'); return
    wb = openpyxl.load_workbook(SRC[-1], read_only=True, data_only=True)
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    # production annuelle
    prod = {str(int(r[0])): int(r[1]) for r in rows(wb, 'Table_24') if isinstance(r[0], (int, float)) and num(r[1])}
    # par zone : production, stades, poids
    area = {}
    for r in rows(wb, 'Table_35'):
        if not r or not r[0] or not isinstance(r[1], (int, float)): continue
        a, y = r[0], str(int(r[1])); d = area.setdefault(a, {})
        d[y] = {'t': num(r[4]), 'y0': num(r[6]), 'gr': num(r[8]), 'gr_w': num(r[9]), 'ps': num(r[10]), 'ps_w': num(r[11]), 'y2': num(r[12]), 'y2_w': num(r[13]),
                'staff': (num(r[2]) or 0) + (num(r[3]) or 0) if num(r[2]) is not None else None}
    # survie des classes d'age
    surv = {}
    for r in rows(wb, 'Table_28'):
        if not isinstance(r[0], (int, float)): continue
        g = lambda i: num(r[i]) if len(r) > i else None
        surv[str(int(r[0]))] = {'smolts': g(1), 'y0_pct': g(5), 'y1_pct': g(9), 'y1_w': g(8), 'y2_pct': g(13), 'y2_w': g(12)}
    # smolts : mis en mer, produits, estimation de l'annee suivante
    sm = {}
    for r in rows(wb, 'Table_19'):
        if not isinstance(r[0], (int, float)): continue
        sm[str(int(r[0]))] = {'to_sea': num(r[1]), 'produced': num(r[2]), 'est_next': num(r[3])}
    out['history'] = {'source_file': os.path.basename(SRC[-1]), 'production': prod, 'by_area': area, 'year_class': surv, 'smolts': sm}
    est = {y: v['t'] for y, v in area.get('All Scotland', {}).items() if v['t'] and y not in prod}
    if est: out['production_estimate'] = {y: int(v) for y, v in est.items()}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'scotland survey: {SRC[-1]} -> {OUT}, production {min(prod)}-{max(prod)}, areas {sorted(area)}, estimate {est}')

if __name__ == '__main__':
    main()
