#!/usr/bin/env python3
"""
Met a jour data/data.json (records + cohort) a partir de l'export Excel du
Biomasseregisteret de Fiskeridirektoratet (feuille 'Biomasse-prod-omr').

Usage :
    python3 scripts/update_biomasse.py chemin/vers/le/fichier.xlsx

L'Excel contient l'historique COMPLET a chaque export (pas seulement le
dernier mois) -- le script reconstruit donc entierement 'records' et
'cohort' plutot que d'ajouter incrementalement, pour eviter les doublons
si deux exports se chevauchent.

Formules validees terme a terme contre les 1365 lignes 'records' et 3255
lignes 'cohort' deja presentes dans data.json (correspondance exacte) :

  cohort.stock       = BEHFISK_STK
  cohort.weight_kg    = BIOMASSE_KG / BEHFISK_STK
  cohort.growth_kg    = weight_kg(mois) - weight_kg(mois calendaire precedent,
                        meme PO+cohorte) -- null si le mois precedent manque
  cohort.age_months   = voir plus bas, cas particulier

  records.*_kg/_stk   = somme sur toutes les cohortes du PO/mois
  records.mortality_pct = 100 * somme(DODFISK_STK) / somme(BEHFISK_STK)
  records.growth_kg   = moyenne des growth_kg de cohorte, ponderee par
                        BEHFISK_STK (stock vivant, pas les abattages)
  records.age_months  = moyenne des age_months de cohorte, ponderee par
                        UTTAK_STK (poissons abattus ce mois) -- null si
                        aucun abattage

Cas particulier : age_months de cohorte. Le Biomasseregisteret ne donne que
l'ANNEE de mise a l'eau (UTSETTSAAR), pas la date exacte -- l'age precis
d'une cohorte tout juste relachee (ex. -0,34 mois observe dans l'historique)
ne peut pas etre recalcule depuis ce seul fichier. Strategie retenue :
  - Si la cle (po, cohorte, annee, mois) existe deja dans data.json, on
    reprend son age_months tel quel (jamais recalcule -- c'est ce qui a ete
    verifie a l'identique sur les 3255 lignes historiques).
  - Sinon, on part du dernier age_months connu pour ce (po, cohorte) et on
    ajoute le nombre de mois calendaires ecoules (+1 pour un mois consecutif).
  - Si la cohorte est totalement nouvelle (aucun historique), on part de 0.0
    -- une cohorte qui apparait pour la premiere fois vient d'etre relachee,
    l'erreur residuelle est donc faible et ne se reproduit qu'une fois.
"""
import sys, io, json, os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')


def load_excel(path):
    df = pd.read_excel(path, sheet_name='Biomasse-prod-omr', skiprows=5)
    df.columns = [c.strip() for c in df.columns]
    df = df[(df['ARTSID'] == 'LAKS') &
            (df['PO_KODE'].apply(lambda x: isinstance(x, int)))].copy()
    df = df.sort_values(['PO_KODE', 'UTSETTSÅR', 'ÅR', 'MÅNED_KODE'])
    return df


def build_cohort(df, existing_cohort):
    df = df.copy()
    df['weight_kg'] = df['BIOMASSE_KG'] / df['BEHFISK_STK'].replace(0, pd.NA)
    df['ym'] = df['ÅR'] * 12 + df['MÅNED_KODE']
    df['prev_ym'] = df.groupby(['PO_KODE', 'UTSETTSÅR'])['ym'].shift(1)
    df['prev_w'] = df.groupby(['PO_KODE', 'UTSETTSÅR'])['weight_kg'].shift(1)
    df['gap'] = df['ym'] - df['prev_ym']
    df['growth_kg'] = df['weight_kg'] - df['prev_w']
    df.loc[df['gap'] != 1, 'growth_kg'] = None

    old = {(r['po'], r['cohort'], r['year'], r['month']): r['age_months']
           for r in existing_cohort}
    # dernier age_months connu par (po, cohorte), pour prolonger les nouvelles
    # entrees mois par mois plutot que de tout recalculer a zero.
    last_age = {}
    for r in sorted(existing_cohort, key=lambda r: (r['year'], r['month'])):
        if r.get('age_months') is not None:
            last_age[(r['po'], r['cohort'])] = (r['year'] * 12 + r['month'], r['age_months'])

    out = []
    for _, r in df.iterrows():
        po, coh, y, m = int(r['PO_KODE']), int(r['UTSETTSÅR']), int(r['ÅR']), int(r['MÅNED_KODE'])
        key = (po, coh, y, m)
        stock = float(r['BEHFISK_STK'])
        weight_kg = float(r['weight_kg']) if pd.notna(r['weight_kg']) else None
        growth_kg = float(r['growth_kg']) if pd.notna(r['growth_kg']) else None

        if key in old:
            age = old[key]
        else:
            pk = (po, coh)
            ym = y * 12 + m
            if pk in last_age:
                last_ym, last_val = last_age[pk]
                age = last_val + (ym - last_ym)
            else:
                age = 0.0
            last_age[pk] = (ym, age)

        out.append({'po': po, 'cohort': coh, 'year': y, 'month': m,
                    'age_months': age, 'weight_kg': weight_kg,
                    'growth_kg': growth_kg, 'stock': stock})
    return out


def build_records(df, cohort_rows):
    coh_by_key = {}
    for r in cohort_rows:
        coh_by_key.setdefault((r['year'], r['month'], r['po']), []).append(r)

    out = []
    g = df.groupby(['ÅR', 'MÅNED_KODE', 'PO_KODE'])
    for (y, m, po), sub in g:
        y, m, po = int(y), int(m), int(po)
        behfisk = float(sub['BEHFISK_STK'].sum())
        dodfisk = float(sub['DØDFISK_STK'].sum())
        uttak_stk = float(sub['UTTAK_STK'].sum())

        cohorts = coh_by_key.get((y, m, po), [])
        by_coh = {c['cohort']: c for c in cohorts}

        # age_months : moyenne ponderee par UTTAK_STK (poissons abattus)
        age_num = age_den = 0.0
        for _, row in sub.iterrows():
            c = by_coh.get(int(row['UTSETTSÅR']))
            if c is None or c['age_months'] is None or row['UTTAK_STK'] <= 0:
                continue
            age_num += c['age_months'] * row['UTTAK_STK']
            age_den += row['UTTAK_STK']
        age_months = (age_num / age_den) if age_den > 0 else None

        # growth_kg : moyenne ponderee par BEHFISK_STK (stock vivant)
        gr_num = gr_den = 0.0
        for _, row in sub.iterrows():
            c = by_coh.get(int(row['UTSETTSÅR']))
            if c is None or c['growth_kg'] is None or row['BEHFISK_STK'] <= 0:
                continue
            gr_num += c['growth_kg'] * row['BEHFISK_STK']
            gr_den += row['BEHFISK_STK']
        growth_kg = (gr_num / gr_den) if gr_den > 0 else None

        out.append({
            'year': y, 'month': m, 'po': po,
            'uttak_kg': float(sub['UTTAK_KG'].sum()),
            'uttak_stk': uttak_stk,
            'dodfisk_stk': dodfisk,
            'behfisk_stk': behfisk,
            'biomasse_kg': float(sub['BIOMASSE_KG'].sum()),
            'mortality_pct': (100 * dodfisk / behfisk) if behfisk else None,
            'smolt_stk': float(sub['UTSETT_SMOLT_STK'].sum()),
            'age_months': age_months,
            'growth_kg': growth_kg,
            'feed_kg': float(sub['FORFORBRUK_KG'].sum()),
        })
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage : python3 scripts/update_biomasse.py fichier.xlsx")
    path = sys.argv[1]
    if not os.path.exists(path):
        sys.exit(f"Fichier introuvable : {path}")

    data = json.load(io.open(DATA)) if os.path.exists(DATA) else {}
    existing_cohort = data.get('cohort', [])

    print(f"Lecture de {path} ...")
    df = load_excel(path)
    print(f"  {len(df)} lignes LAKS avec PO valide, "
          f"{df['ÅR'].min()}-{df['ÅR'].max()}")

    cohort_rows = build_cohort(df, existing_cohort)
    records_rows = build_records(df, cohort_rows)

    old_n_c, old_n_r = len(existing_cohort), len(data.get('records', []))
    data['cohort'] = cohort_rows
    data['records'] = records_rows
    data.setdefault('meta', {})
    import datetime as dt
    data['meta']['generated'] = dt.date.today().isoformat()
    data['meta']['records'] = len(records_rows)
    data['meta']['cohort'] = len(cohort_rows)

    io.open(DATA, 'w').write(json.dumps(data, separators=(',', ':')))
    print(f"\nrecords : {old_n_r} -> {len(records_rows)} lignes")
    print(f"cohort  : {old_n_c} -> {len(cohort_rows)} lignes")
    last = sorted(set((r['year'], r['month']) for r in records_rows))[-1]
    print(f"dernier mois present : {last[0]}-{last[1]:02d}")
    print(f"data.json : {os.path.getsize(DATA)/1e6:.1f} Mo")


if __name__ == '__main__':
    main()
