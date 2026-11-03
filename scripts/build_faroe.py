#!/usr/bin/env python3
"""
Construit data/faroe.json pour l'onglet Faroe Islands du tableau de bord.

Sources :
  - Bakkafrost, page « Data » : nombre de poissons par ferme aux Feroe, fin de chaque mois depuis juin 2026
    (la page ne montre que les derniers mois : chaque passage ARCHIVE les colonnes dans
    farming/donnees_fo/bakkafrost_fermes.csv), plus les indicateurs annuels (mortalite, poux, jachere, aliment).
  - Landsverk : registre officiel des zones d'elevage en mer (titulaire, fjord, numero de zone).
    Positions = centre approximatif du fjord ou de la baie (les plans officiels sont des PDF dessines).
  - Mises a jour trimestrielles de Bakkafrost et Mowi (recolte par mois, smolts) : farming/donnees_fo/recolte.csv,
    complete a chaque trimestre.

    python3 scripts/build_faroe.py
"""
import csv
import datetime as dt
import io
import json
import os
import re
import urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'farming', 'donnees_fo')
OUT = os.path.join(ROOT, 'data', 'faroe.json')
BAKKA_URL = 'https://www.bakkafrost.com/en/about-us/sustainability/data/'
LANDSVERK_URL = 'https://www.landsverk.fo/fo-fo/borgari/kervi%C3%B0/aling'

# Registre Landsverk (releve du 03/11/2026) : titulaire, fjord, zones. Luna P/f = Hiddenfjord.
REGISTRE = [
    ('Bakkafrost', 'C-07 Funningsfjørður', ['A-02', 'A-43', 'A-71']), ('Bakkafrost', 'C-11 Lambavík', ['A-04']),
    ('Bakkafrost', 'C-14 Kollafjørður / Tangafjørður', ['A-05']), ('Bakkafrost', 'C-16 Nólsoyarfjørður', ['A-06']),
    ('Hiddenfjord', 'C-18 Vestmannasund', ['A-08']), ('Bakkafrost', 'C-01 Hvannasund S', ['A-11', 'A-21']),
    ('Bakkafrost', 'C-05 Haraldsund S', ['A-12']), ('Bakkafrost', 'C-04 Borðoyarvík', ['A-13']),
    ('Hiddenfjord', 'C-20 Sørvágsfjørður', ['A-14']), ('Bakkafrost', 'C-21 Trongisvágsfjørður', ['A-15']),
    ('Bakkafrost', 'C-22 Hovsfjørður', ['A-17']), ('Bakkafrost', 'C-23 Vágsfjørður / Lopransfjørður', ['A-19', 'A-92']),
    ('Bakkafrost', 'C-21 Hvalbiarfjørður', ['A-23']), ('Bakkafrost', 'C-10 Gøtuvík', ['A-25', 'A-47']),
    ('Hiddenfjord', 'C-19 Miðvágur / Sandavágur / Hestsfjørður', ['A-27']), ('Mowi Faroes', 'C-12 Sundini Norður', ['A-32', 'A-87']),
    ('Mowi Faroes', 'C-08 Oyndarfjørður', ['A-52']), ('Bakkafrost', 'C-09 Fuglafjørður', ['A-57']),
    ('Bakkafrost', 'C-03 Árnafjørður', ['A-63']), ('Bakkafrost', 'C-06 Haraldsund N', ['A-72']),
    ('Bakkafrost', 'C-02 Hvannasund N', ['A-73']), ('Bakkafrost', 'C-13 Sundini S', ['A-80']),
    ('Bakkafrost', 'C-14 Kollafjørður / Tangafjørður', ['A-81']), ('Hiddenfjord', 'C-20 Sørvágsfjørður', ['A-83']),
    ('Bakkafrost', 'C-14 Undir Neslandinum', ['A-85']), ('Hiddenfjord', 'C-18 Vestmannasund', ['A-88']),
    ('Hiddenfjord', 'C-19 Miðvágur / Sandavágur / Hestsfjørður', ['A-89']), ('Mowi Faroes', 'C-17 Sandsvág-Skúvoyarfjørður', ['A-90']),
]
# centre approximatif du fjord ou de la baie (precision de l'ordre de 2-3 km)
POS = {'A-02': (62.268, -6.952), 'A-43': (62.258, -6.948), 'A-71': (62.263, -6.950), 'A-04': (62.138, -6.700),
       'A-05': (62.095, -6.900), 'A-06': (61.995, -6.760), 'A-08': (62.150, -7.130), 'A-11': (62.284, -6.515),
       'A-21': (62.276, -6.515), 'A-12': (62.262, -6.590), 'A-13': (62.225, -6.570), 'A-14': (62.070, -7.330),
       'A-15': (61.560, -6.780), 'A-17': (61.508, -6.745), 'A-19': (61.473, -6.780), 'A-92': (61.443, -6.770),
       'A-23': (61.598, -6.915), 'A-25': (62.180, -6.725), 'A-47': (62.190, -6.722), 'A-27': (62.040, -7.140),
       'A-32': (62.230, -6.985), 'A-87': (62.245, -7.000), 'A-52': (62.270, -6.860), 'A-57': (62.240, -6.800),
       'A-63': (62.255, -6.535), 'A-72': (62.285, -6.595), 'A-73': (62.315, -6.515), 'A-80': (62.150, -6.905),
       'A-81': (62.115, -6.880), 'A-83': (62.078, -7.300), 'A-85': (62.080, -6.735), 'A-88': (62.165, -7.160),
       'A-89': (62.030, -7.100), 'A-90': (61.790, -6.830)}
ALIAS = {'A-18': 'A-17'}    # Bakkafrost ecrit « A18 - Hov », le registre « A-17 Hovsfjørður »

# Releve de la page Bakkafrost du 03/11/2026 : amorce de l'archive (blanc = ferme vide)
AMORCE = {'2026-06-30': {'A04 - Lambavík': 1117403, 'A06 - Argir': 1117334, 'A11 - Hvannasund S': 1353975, 'A13 - Borðoyavík': 1033114,
                         'A15 - Tvøroyri': 1011751, 'A18 - Hov': 1025614, 'A19 - Vágur': 1002543, 'A21 - Hvannasund S': 1329852,
                         'A23 - Hvalba': 1114004, 'A25 - Gøtuvík': 1030534, 'A47 - Gøtuvík': 993031, 'A57 - Fuglafjørður': 2231361,
                         'A63 - Árnafjørður': 1106106, 'A71 - Funningsfjørður': 2427264, 'A73 - Hvannasund N': 1211319, 'A85 - Nes': 208507},
          '2026-07-31': {'A06 - Argir': 1110028, 'A11 - Hvannasund S': 1348200, 'A13 - Borðoyavík': 555728, 'A15 - Tvøroyri': 1006591,
                         'A18 - Hov': 1018983, 'A19 - Vágur': 997195, 'A21 - Hvannasund S': 1325908, 'A23 - Hvalba': 1111951,
                         'A25 - Gøtuvík': 1027999, 'A47 - Gøtuvík': 990268, 'A57 - Fuglafjørður': 2494242, 'A63 - Árnafjørður': 1094730,
                         'A71 - Funningsfjørður': 2420315, 'A72 - Haraldsund': 874610, 'A73 - Hvannasund N': 1208389, 'A85 - Nes': 134561},
          '2026-08-31': {'A06 - Argir': 1101560, 'A11 - Hvannasund S': 1344947, 'A12 - Kunoyarnes': 996022, 'A15 - Tvøroyri': 1000615,
                         'A18 - Hov': 1014413, 'A19 - Vágur': 695964, 'A21 - Hvannasund S': 1323918, 'A23 - Hvalba': 1110064,
                         'A25 - Gøtuvík': 1016044, 'A47 - Gøtuvík': 978572, 'A57 - Fuglafjørður': 2485990, 'A63 - Árnafjørður': 669150,
                         'A71 - Funningsfjørður': 2415919, 'A72 - Haraldsund': 1552778, 'A73 - Hvannasund N': 1205823, 'A80 - Selatrað': 461702},
          '2026-09-30': {'A04 - Lambavík': 229813, 'A06 - Argir': 769580, 'A11 - Hvannasund S': 1330821, 'A12 - Kunoyarnes': 1788193,
                         'A15 - Tvøroyri': 997074, 'A18 - Hov': 1010322, 'A19 - Vágur': 129967, 'A21 - Hvannasund S': 1315951,
                         'A23 - Hvalba': 1107988, 'A25 - Gøtuvík': 1002075, 'A47 - Gøtuvík': 960085, 'A57 - Fuglafjørður': 2478613,
                         'A71 - Funningsfjørður': 2408655, 'A72 - Haraldsund': 1548128, 'A73 - Hvannasund N': 1202423, 'A80 - Selatrað': 615243}}
# Recolte et smolts publies dans les mises a jour trimestrielles (milliers de tonnes HOG / GWT, poids moyen kg, millions de smolts)
RECOLTE = [  # entreprise, periode, tonnes, poids moyen, source
    ('Bakkafrost', '2026-Q1', 25200, None, 'Bakkafrost Q2 2026 trading update (YTD 51.9 kt minus Q2 26.7 kt)'),
    ('Bakkafrost', '2026-04', 7700, 5.9, 'Bakkafrost Q2 2026 trading update'), ('Bakkafrost', '2026-05', 8700, 5.7, 'Bakkafrost Q2 2026 trading update'),
    ('Bakkafrost', '2026-06', 10300, 5.2, 'Bakkafrost Q2 2026 trading update'), ('Bakkafrost', '2026-07', 8300, 5.0, 'Bakkafrost Q3 2026 trading update'),
    ('Bakkafrost', '2026-08', 7100, 5.0, 'Bakkafrost Q3 2026 trading update'), ('Bakkafrost', '2026-09', 7700, 4.9, 'Bakkafrost Q3 2026 trading update'),
    ('Mowi Faroes', '2025-Q3', 2500, None, 'Mowi Q3 2025 trading update (gutted weight)'),
    ('Mowi Faroes', '2026-Q2', 2500, None, 'Mowi Q2 2026 trading update (gutted weight)'),
]
SMOLTS = [('Bakkafrost', '2026-Q1', 3.9), ('Bakkafrost', '2026-Q2', 5.6), ('Bakkafrost', '2026-Q3', 4.5)]
# Indicateurs annuels Bakkafrost Feroe (page Data, releve du 03/11/2026)
ANNUEL = {'mortality_pct': {2016: 6.33, 2017: 8.96, 2018: 11.56, 2019: 4.57, 2020: 10.29, 2021: 8.24, 2022: 4.91, 2023: 7.3, 2024: 6.6, 2025: 4.29},
          'lice_af': {2016: 0.8, 2017: 0.7, 2018: 0.47, 2019: 0.43, 2020: 0.45, 2021: 0.43, 2022: 0.28, 2023: 0.28, 2024: 0.22, 2025: 0.27},
          'fallow_weeks': {2016: 10.8, 2017: 15.5, 2018: 15.6, 2019: 17.3, 2020: 20.6, 2021: 12.8, 2022: 18.5, 2023: 20.08, 2024: 16, 2025: 13.46},
          'feed_factor': {2016: 1.13, 2017: 1.18, 2018: 1.17, 2019: 1.12, 2020: 1.08, 2021: 1.06, 2022: 1.06, 2023: 1.096, 2024: 1.11, 2025: 1.106}}


# ----------------------------------------------------------------------------- poids moyen theorique
# Croissance « TGC » (coefficient de croissance thermique) : W^(1/3) augmente de TGC/1000 x temperature chaque jour (W en g).
# Temperatures : moyennes mensuelles approximatives de la mer cotiere feroienne (environ 7 degres en hiver, 11 en aout).
TEMP = {1: 7.3, 2: 6.9, 3: 6.8, 4: 7.0, 5: 7.7, 6: 8.9, 7: 10.2, 8: 10.9, 9: 10.5, 10: 9.6, 11: 8.6, 12: 7.9}
TGC = 2.5                 # valeur moyenne pour du saumon atlantique en mer (2,0 a 3,0 selon la taille et les sources)
SMOLT_KG = 0.5            # Bakkafrost met en mer des smolts d'environ 500 g
VIF_HOG = 0.88            # poids vide tete (HOG) / poids vif


def croissance(w_kg, d0, d1):
    """Poids vif (kg) au jour d1 d'un poisson de w_kg au jour d0 ; a rebours si d1 < d0."""
    c = (w_kg * 1000) ** (1 / 3)
    pas = 1 if d1 >= d0 else -1
    d = d0
    while d != d1:
        jour = d if pas > 0 else d - dt.timedelta(days=1)
        c += pas * TGC / 1000 * TEMP[jour.month]
        d += dt.timedelta(days=pas)
    return max(c, 1) ** 3 / 1000


def mi_mois(date_fin):
    return date_fin.replace(day=15)


def poids_ferme(dates, fish, poids_recolte):
    """Poids vif estime a chaque fin de mois. Trois cas, par cycle (un cycle s'arrete quand la ferme est vide) :
       - cycle commence dans l'archive (0 -> poissons) : smolts de 500 g mis en mer au milieu du mois ;
       - cycle avec recolte dans l'archive : au milieu du premier mois de recolte, poids = poids moyen de recolte
         publie par Bakkafrost pour ce mois (converti en vif), puis croissance avant et apres ;
       - sinon age inconnu : fourchette entre smolts mis en mer a la mi-mars 2026 et a la mi-septembre 2025.
       Les ajouts de poissons en cours de cycle sont des smolts de 500 g melanges au stock existant."""
    D = [dt.date.fromisoformat(d) for d in dates]
    n = len(D)
    w, lo, hi, meth = [None] * n, [None] * n, [None] * n, [''] * n
    i = 0
    while i < n:
        if not fish[i]: i += 1; continue
        j = i
        while j + 1 < n and fish[j + 1]: j += 1                      # cycle = mois i..j avec des poissons
        debut_vu = i > 0                                             # la ferme etait vide le mois d'avant
        rec = next((k for k in range(i + 1, min(j + 2, n)) if (k > j or fish[k] < fish[k - 1] * 0.92)
                    and poids_recolte.get(dates[k][:7])), None)
        def suivre(w0, d0, k0, k1, cible):
            """remplit cible[k] pour k0..k1 depuis un poids w0 au jour d0, en melangeant les ajouts de smolts"""
            ww, dd = w0, d0
            for k in range(k0, k1 + 1):
                if k > k0 and fish[k - 1] and fish[k] > fish[k - 1] * 1.08 and dd <= mi_mois(D[k]):
                    ww = croissance(ww, dd, mi_mois(D[k])); dd = mi_mois(D[k])
                    ww = (fish[k - 1] * ww + (fish[k] - fish[k - 1]) * SMOLT_KG) / fish[k]
                cible[k] = round(croissance(ww, dd, D[k]), 2) if D[k] >= dd else round(croissance(ww, dd, D[k]), 2)
                ww, dd = cible[k], D[k]
        if debut_vu:
            suivre(SMOLT_KG, mi_mois(D[i]), i, j, w); meth[i:j + 1] = ['from stocking'] * (j - i + 1)
        elif rec is not None:
            # chaque mois de recolte : au milieu du mois, poids = poids moyen de recolte publie (converti en vif) ;
            # avant la premiere recolte, croissance a rebours ; entre deux recoltes, croissance normale
            ancres = {k: poids_recolte[dates[k][:7]] / VIF_HOG for k in range(i, j + 1)
                      if k > i and fish[k] < fish[k - 1] * 0.92 and poids_recolte.get(dates[k][:7])}
            if rec > j: ancres[rec] = poids_recolte[dates[rec][:7]] / VIF_HOG     # ferme videe le mois suivant
            k0 = min(ancres)
            for k in range(i, min(k0, j + 1)):
                w[k] = round(croissance(ancres[k0], mi_mois(D[k0]), D[k]), 2)
            for k in range(k0, j + 1):
                if k in ancres: w[k] = round(croissance(ancres[k], mi_mois(D[k]), D[k]), 2)
                else: w[k] = round(croissance(w[k - 1], D[k - 1], D[k]), 2)
            meth[i:j + 1] = ['harvest-anchored'] * (j - i + 1)
        elif any(fish[k] > fish[k - 1] * 1.08 for k in range(i + 1, j + 1)):
            # age inconnu mais ajout de smolts dans l'archive : un complement suit de peu la mise en mer principale,
            # on retient une mise en mer principale un mois plus tot
            k = next(k for k in range(i + 1, j + 1) if fish[k] > fish[k - 1] * 1.08)
            d0 = mi_mois(D[k - 1])
            suivre(SMOLT_KG, d0 if d0 <= D[i] else D[i], i, j, w)
            meth[i:j + 1] = ['from stocking (inferred from a top-up)'] * (j - i + 1)
        else:
            # age inconnu : au plus tot, smolts de la mi-mars 2026 ; au plus tard, smolts de la mi-septembre 2025,
            # plafonnes au poids de recolte du mois (des poissons plus gros seraient deja en recolte)
            suivre(SMOLT_KG, dt.date(2026, 3, 15), i, j, lo)
            suivre(SMOLT_KG, dt.date(2025, 9, 15), i, j, hi)
            for k in range(i, j + 1):
                cap = poids_recolte.get(dates[k][:7])
                if cap and hi[k] and hi[k] > cap / VIF_HOG: hi[k] = round(cap / VIF_HOG, 2)
            meth[i:j + 1] = ['unknown age'] * (j - i + 1)
        i = j + 1
    return w, lo, hi, meth


class Tables(HTMLParser):
    """Tableaux HTML, chacun precede du dernier titre (h1-h4) rencontre."""
    def __init__(self):
        super().__init__(); self.out, self.titre, self.t, self.row, self.cell, self.h = [], '', None, None, None, None
    def handle_starttag(self, tag, a):
        if tag in ('h1', 'h2', 'h3', 'h4'): self.h = ''
        elif tag == 'table': self.t = {'titre': self.titre, 'rows': []}
        elif tag == 'tr' and self.t is not None: self.row = []
        elif tag in ('td', 'th') and self.row is not None: self.cell = ''
    def handle_endtag(self, tag):
        if tag in ('h1', 'h2', 'h3', 'h4') and self.h is not None: self.titre = (self.titre + ' | ' + self.h.strip())[-200:]; self.h = None
        elif tag in ('td', 'th') and self.cell is not None: self.row.append(re.sub(r'\s+', ' ', self.cell).strip()); self.cell = None
        elif tag == 'tr' and self.row is not None: self.t['rows'].append(self.row); self.row = None
        elif tag == 'table' and self.t is not None: self.out.append(self.t); self.t = None
    def handle_data(self, d):
        if self.cell is not None: self.cell += d
        if self.h is not None: self.h += d


def lire_bakkafrost(html):
    """-> ({date: {ferme: poissons}}, indicateurs annuels lus)"""
    p = Tables(); p.feed(html)
    fermes, annuel = {}, {}
    for t in p.out:
        rows = t['rows']
        if not rows: continue
        tete = rows[0]
        dates = [re.match(r'(\d{2})/(\d{2})/(\d{4})', c.replace('*', '').strip()) for c in tete[1:]]
        if 'FAROE' in t['titre'].upper() and 'BIOMASS' in t['titre'].upper() and any(dates):
            for r in rows[1:]:
                if not r or r[0].lower().startswith('total') or not re.match(r'A\d', r[0]): continue
                for m, v in zip(dates, r[1:]):
                    if not m: continue
                    d = f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
                    n = re.sub(r'[^\d]', '', v)
                    fermes.setdefault(d, {})[r[0].strip()] = int(n) if n else 0
    return fermes, annuel


def archive(lu):
    """Fusionne les releves dans farming/donnees_fo/bakkafrost_fermes.csv (date, ferme, poissons)."""
    os.makedirs(SRC, exist_ok=True)
    p = os.path.join(SRC, 'bakkafrost_fermes.csv')
    data = {}
    if os.path.exists(p):
        with io.open(p, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh): data.setdefault(r['date'], {})[r['ferme']] = int(r['poissons'])
    for d, f in lu.items(): data[d] = f                           # la page fait foi pour les mois qu'elle montre
    with io.open(p, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh); w.writerow(['date', 'ferme', 'poissons'])
        for d in sorted(data):
            for f, n in sorted(data[d].items()): w.writerow([d, f, n])
    return data


def main():
    lu, note = {}, ''
    if os.environ.get('FO_HORS_LIGNE') != '1':
        try:
            html = urllib.request.urlopen(urllib.request.Request(BAKKA_URL, headers={'User-Agent': 'suivi-salmonicole/1.0'}), timeout=60).read().decode('utf-8', 'replace')
            lu, _ = lire_bakkafrost(html)
            if not lu: note = 'tableau des fermes introuvable sur la page Bakkafrost (mise en page changée ?)'
        except Exception as e:  # noqa: BLE001
            note = f'page Bakkafrost inaccessible : {e}'
    base = AMORCE.copy(); base.update(lu)
    data = archive(base)
    dates = sorted(data)
    noms = sorted({f for d in data.values() for f in d})
    # fermes Bakkafrost -> zones du registre
    reg = {z: (op, fj) for op, fj, zs in REGISTRE for z in zs}
    POIDS_RECOLTE = {p: wt for c, p, t, wt, src in RECOLTE if c == 'Bakkafrost' and wt and re.match(r'\d{4}-\d{2}$', p)}
    sites = []
    for f in noms:
        m = re.match(r'A(\d+)\s*-\s*(.+)', f)
        code = ALIAS.get(f'A-{int(m.group(1)):02d}', f'A-{int(m.group(1)):02d}') if m else None
        op, fj = reg.get(code, ('Bakkafrost', ''))
        lat, lon = POS.get(code, (None, None))
        fish = [data[d].get(f, 0) for d in dates]
        w, lo, hi, meth = poids_ferme(dates, fish, POIDS_RECOLTE)
        sites.append({'id': f, 'code': code, 'name': m.group(2).strip() if m else f, 'fjord': fj, 'op': 'Bakkafrost',
                      'lat': lat, 'lon': lon, 'fish': fish, 'w': w, 'wlo': lo, 'whi': hi, 'wm': meth})
    L = len(dates) - 1
    an = dates[L][:4]
    inconnus = [x for x in sites if x['wm'][L] == 'unknown age' and x['fish'][L]]
    n_inc = sum(x['fish'][L] for x in inconnus)
    # smolts du 1er semestre de l'annee deja places dans des fermes d'age connu (complement deduit) : retires du compte
    deja = sum(x['fish'][L] for x in sites if x['wm'][L].startswith('from stocking (inferred') and x['fish'][L])
    s1 = sum(m for c, p, m in SMOLTS if c == 'Bakkafrost' and p in (f'{an}-Q1', f'{an}-Q2')) * 1e6
    jeunes = max(0.0, min(n_inc, s1 * 0.97 - deja))           # ~3 % de pertes depuis la mise en mer
    vieux = n_inc - jeunes
    dfin = dt.date.fromisoformat(dates[L])
    w_jeunes = (croissance(SMOLT_KG, dt.date(int(an), 2, 15), dfin) * 3.9 + croissance(SMOLT_KG, dt.date(int(an), 5, 15), dfin) * 5.6) / 9.5
    cap = POIDS_RECOLTE.get(dates[L][:7])
    w_vieux = min(croissance(SMOLT_KG, dt.date(int(an) - 1, 9, 15), dfin), cap / VIF_HOG if cap else 99)
    connus = sum(x['fish'][L] * x['w'][L] for x in sites if x['w'][L] and x['fish'][L])
    cohorte = {'date': dates[L], 'unknown_fish': n_inc, 'young_fish': round(jeunes), 'old_fish': round(vieux),
               'w_young': round(w_jeunes, 2), 'w_old': round(w_vieux, 2), 'h1_releases': s1,
               'biomass_known_t': round(connus / 1000), 'biomass_unknown_t': round((jeunes * w_jeunes + vieux * w_vieux) / 1000)}
    autres = [{'code': z, 'fjord': fj, 'op': op, 'lat': POS.get(z, (None, None))[0], 'lon': POS.get(z, (None, None))[1]}
              for op, fj, zs in REGISTRE for z in zs if op != 'Bakkafrost' or not any(s['code'] == z for s in sites)]
    out = {'meta': {'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'dates': dates, 'note': note,
                    'sources': {'farms': BAKKA_URL, 'register': LANDSVERK_URL}},
           'sites': sites, 'register_other': autres,
           'harvest': [{'co': c, 'p': p, 't': t, 'w': w, 'src': s} for c, p, t, w, s in RECOLTE],
           'smolts': [{'co': c, 'p': p, 'm': m} for c, p, m in SMOLTS],
           'annual': {k: {str(a): v for a, v in d.items()} for k, d in ANNUEL.items()},
           'cohort': cohorte,
           'model': {'tgc': TGC, 'smolt_kg': SMOLT_KG, 'live_per_hog': VIF_HOG, 'temp': TEMP,
                     'unknown_range': ['smolts put to sea mid-March 2026', 'smolts put to sea mid-September 2025, capped at the month\'s harvest weight']}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'data/faroe.json : {len(sites)} fermes Bakkafrost, {len(dates)} fins de mois ({dates[0]} -> {dates[-1]}), '
          f'{len(autres)} autres zones du registre' + (f' — ATTENTION : {note}' if note else ''))
    if note: raise SystemExit(1)


if __name__ == '__main__':
    main()
