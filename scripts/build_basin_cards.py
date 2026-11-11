#!/usr/bin/env python3
"""
data/basin_cards.json : le bloc « en un coup d'oeil » commun a tous les bassins d'elevage (Norvege, Chili, Ecosse,
Feroe, Islande, Canada, Tasmanie) : les MEMES huit indicateurs, dans le MEME ordre, chacun avec sa valeur, sa periode,
une comparaison a un an, sa source, le fichier lu et sa fraicheur.

  1 harvest_year    recolte de la derniere annee complete
  2 harvest_recent  signal de volume infra-annuel le plus frais (recolte, sinon exportations), cumul depuis janvier
  3 stock           poissons ou biomasse en mer a la derniere date
  4 mortality       derniere mesure de mortalite
  5 lice            dernier niveau de poux
  6 weight          poids moyen de recolte
  7 sites           fermes actives / sites avec poissons
  8 outlook         prevision du tableau de bord (data/own_supply.json)

Regles :
  - aucun chiffre en dur : toutes les valeurs sont lues dans data/*.json a l'execution (jamais le reseau) ;
  - chaque carte est calculee dans un try/except : un chemin casse donne status "missing" avec l'erreur, jamais un plantage ;
  - comparaisons a perimetre egal (meme mois, memes semaines, meme trimestre un an plus tot), sinon cmp = null ;
  - quand un bassin ne publie pas l'indicateur, la carte est "missing" et why_missing le dit en clair ;
  - les definitions different d'un bassin a l'autre : le champ "measure" dit exactement ce qui est mesure.

Champs hors cahier des charges : "note" (complement lu dans les donnees, par ex. le dernier mois seul) et "age_days".
Pour la carte outlook, "asof" est la date de construction de la prevision (la periode decrite est dans le futur).

    python3 scripts/build_basin_cards.py        -> data/basin_cards.json
"""
import calendar
import collections
import datetime as dt
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'basin_cards.json')
TODAY = dt.date.today()
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# id, libelle, sens favorable (offre / sante)
INDICATORS = [('harvest_year', 'Harvest, latest full year', 'up'),
              ('harvest_recent', 'Harvest so far this year', 'up'),
              ('stock', 'Fish in the sea', 'up'),
              ('mortality', 'Mortality', 'down'),
              ('lice', 'Sea lice', 'down'),
              ('weight', 'Average harvest weight', 'up'),
              ('sites', 'Farms with fish', 'up'),
              ('outlook', 'Outlook', 'up')]
LABEL = {i: l for i, l, _ in INDICATORS}
GOOD = {i: g for i, _, g in INDICATORS}
BASINS = [('NO', 'Norway'), ('CL', 'Chile'), ('GB', 'Scotland'), ('FO', 'Faroe Islands'), ('IS', 'Iceland'), ('CA', 'Canada'), ('AU', 'Tasmania (Australia)')]


# ---------------------------------------------------------------- outils
_cache = {}


def load(name):
    """Lit data/<name> une seule fois."""
    if name not in _cache:
        with open(os.path.join(DATA, name), encoding='utf-8') as f:
            _cache[name] = json.load(f)
    return _cache[name]


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def pct(a, b):
    """Variation en % de a par rapport a b, ou None."""
    a, b = num(a), num(b)
    return round(100 * (a / b - 1), 1) if a is not None and b else None


def pts(a, b):
    """Ecart en points entre deux pourcentages, ou None."""
    a, b = num(a), num(b)
    return round(a - b, 2) if a is not None and b is not None else None


def month_end(k):
    """Dernier jour du mois k = AAAAMM (entier)."""
    y, m = divmod(int(k), 100)
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def mlab(k):
    y, m = divmod(int(k), 100)
    return f'{MON[m - 1]} {y}'


def ym(s):
    """'2026-09' ou '202609' ou 202609 -> 202609."""
    return int(str(s).replace('-', '')[:6])


def week_end(y, w):
    return dt.date.fromisocalendar(int(y), int(w), 7)


def quarter_end(y, q):
    return month_end(int(y) * 100 + 3 * int(q))


def fmt(v, d=0):
    return f'{v:,.{d}f}'


def sg(v, d=1):
    return f'{v:+.{d}f}'.replace('-', '−')


def card(cid, value, unit, period, asof, measure, source, file, freq, cmp=None, cmp_kind='pct', cmp_label=None, note=None):
    if num(value) is None:
        raise ValueError('no value found')
    return {'id': cid, 'label': LABEL[cid], 'value': value, 'unit': unit, 'period': period, 'asof': asof.isoformat(),
            'age_days': (TODAY - asof).days, 'cmp': cmp, 'cmp_kind': cmp_kind, 'cmp_label': cmp_label if cmp is not None else None,
            'good': GOOD[cid], 'measure': measure, 'source': source, 'file': file, 'freq': freq, 'status': 'ok', 'why_missing': None, 'note': note}


def missing(cid, why, source=None, file=None):
    return {'id': cid, 'label': LABEL[cid], 'value': None, 'unit': None, 'period': None, 'asof': None, 'age_days': None, 'cmp': None,
            'cmp_kind': None, 'cmp_label': None, 'good': GOOD[cid], 'measure': None, 'source': source, 'file': file, 'freq': None,
            'status': 'missing', 'why_missing': why, 'note': None}


def safe(cid, fn):
    """Une carte ne fait jamais planter le script : toute erreur devient une carte "missing"."""
    try:
        c = fn()
        if not isinstance(c, dict) or c.get('id') != cid:
            raise ValueError('builder returned no card')
        return c
    except Exception as e:  # noqa: BLE001
        return missing(cid, f'could not be computed from the repo data ({type(e).__name__}: {e})'[:300])


def outlook(code, year_done=False):
    """Carte outlook : notre propre estimation (data/own_supply.json). Les cles s'appellent e<annee> (annee en cours,
    reel a date + reste projete) et c<annee+1> (projection). year_done : l'annee e<annee> est deja terminee (exercice
    australien) -> la carte montre la projection de l'annee suivante."""
    o = load('own_supply.json')
    b = (o.get('basins') or {})[code]
    y = max(int(m.group(1)) for k in b for m in [re.match(r'^e(\d{4})$', k)] if m)
    built = dt.date.fromisoformat(str((o.get('meta') or {}).get('built'))[:10])
    rng = ''
    if num(b.get('lo')) is not None and num(b.get('hi')) is not None:
        rng = f' (range {sg(b["lo"])} to {sg(b["hi"])} %)'
    method = (b.get('method') or '').strip()
    if year_done:
        v, ch, per, lab = b.get(f'c{y + 1}'), b.get(f'chg{y + 1}'), f'{y + 1} projection', f'vs {y}'
        note = f'Range of the projection: {sg(b["lo"])} to {sg(b["hi"])} %.' if rng else None
    else:
        v, ch, per, lab = b.get(f'e{y}'), b.get(f'chg{y}'), f'{y} estimate', f'vs {y - 1}'
        note = f'{y + 1} projection: {sg(b[f"chg{y + 1}"])} % on {y}{rng}.' if num(b.get(f'chg{y + 1}')) is not None else None
    if num(v) is None:
        raise ValueError('no estimate in own_supply.json')
    return card('outlook', round(v * 1000), 'tonnes (gutted weight or whole-fish equivalent)', per, built,
                'Dashboard\'s own estimate from primary data, not an official forecast. ' + method[:400], 'Dashboard estimate; ' + (b.get('source') or ''),
                f'data/own_supply.json → basins.{code}', 'monthly', cmp=num(ch), cmp_label=lab, note=note)


# ---------------------------------------------------------------- Norvege
def norway():
    def recs():
        """Registre de biomasse : sommes nationales (toutes zones) par (annee, mois)."""
        agg = collections.defaultdict(lambda: collections.defaultdict(float))
        for r in load('data.json').get('records') or []:
            k = r['year'] * 100 + r['month']
            for f in ('uttak_kg', 'uttak_stk', 'dodfisk_stk', 'behfisk_stk', 'biomasse_kg'):
                agg[k][f] += r.get(f) or 0
        return agg
    SRC = 'Fiskeridirektoratet biomass register'

    def harvest_year():
        A = recs(); years = sorted({k // 100 for k in A})
        full = [y for y in years if all(y * 100 + m in A for m in range(1, 13))]
        y = full[-1]; tot = lambda yy: sum(A[yy * 100 + m]['uttak_kg'] for m in range(1, 13)) / 1000
        prev = tot(y - 1) if y - 1 in full else None
        return card('harvest_year', round(tot(y)), 'tonnes live weight', str(y), dt.date(y, 12, 31),
                    'Salmon and trout taken out of the sea for slaughter, all production zones, live (round) weight; gutted weight is about 0.888 of it.',
                    SRC, 'data/data.json → records[].uttak_kg', 'annual', cmp=pct(tot(y), prev), cmp_label=f'vs {y - 1}')

    def harvest_recent():
        A = recs(); k = max(A); y, m = divmod(k, 100)
        ytd = sum(A[y * 100 + i]['uttak_kg'] for i in range(1, m + 1)) / 1000
        have = all((y - 1) * 100 + i in A for i in range(1, m + 1))
        ly = sum(A[(y - 1) * 100 + i]['uttak_kg'] for i in range(1, m + 1)) / 1000 if have else None
        a, b = A[k]['uttak_kg'] / 1000, (A[k - 100]['uttak_kg'] / 1000 if k - 100 in A else None)
        note = f'{mlab(k)} alone: {fmt(a)} t' + (f' ({sg(pct(a, b))} % vs {mlab(k - 100)}).' if pct(a, b) is not None else '.')
        return card('harvest_recent', round(ytd), 'tonnes live weight', f'Jan–{MON[m - 1]} {y}', month_end(k),
                    'Fish taken out of the sea for slaughter since January, all production zones, live weight.',
                    SRC, 'data/data.json → records[].uttak_kg', 'monthly', cmp=pct(ytd, ly), cmp_label=f'vs Jan–{MON[m - 1]} {y - 1}', note=note)

    def stock():
        A = recs(); k = max(A); v = A[k]['biomasse_kg'] / 1000; b = A[k - 100]['biomasse_kg'] / 1000 if k - 100 in A else None
        n, nl = A[k]['behfisk_stk'] / 1e6, (A[k - 100]['behfisk_stk'] / 1e6 if k - 100 in A else None)
        note = f'{fmt(n, 1)} million fish' + (f' ({sg(pct(n, nl))} % vs {mlab(k - 100)}).' if pct(n, nl) is not None else '.')
        return card('stock', round(v), 'tonnes live weight', f'end of {mlab(k)}', month_end(k),
                    'Biomass standing in the sea at the end of the month, all production zones, live weight.',
                    SRC, 'data/data.json → records[].biomasse_kg', 'monthly', cmp=pct(v, b), cmp_label=f'vs {mlab(k - 100)}', note=note)

    def mortality():
        A = recs(); k = max(A)
        r = lambda kk: 100 * A[kk]['dodfisk_stk'] / A[kk]['behfisk_stk'] if kk in A and A[kk]['behfisk_stk'] else None
        return card('mortality', round(r(k), 2), '% of fish in the month', mlab(k), month_end(k),
                    'Fish reported dead in the month as a share of the fish standing in the sea (count), all production zones.',
                    SRC, 'data/data.json → records[].dodfisk_stk / behfisk_stk', 'monthly', cmp=pts(r(k), r(k - 100)), cmp_kind='pts', cmp_label=f'vs {mlab(k - 100)}')

    def bw_week():
        """BarentsWatch : derniere semaine COMPLETE. La semaine la plus recente est souvent incomplete (declarations en
        retard) : on recule d'une semaine si elle compte moins de 95 % des sites de la precedente."""
        rows = (load('data.json').get('bw_weekly') or {}).get('rows') or []
        W = collections.defaultdict(list)
        for r in rows:
            W[(r['y'], r['w'])].append(r)
        ks = sorted(W); k = ks[-1]
        tot = lambda kk: sum(r.get('na') or 0 for r in W[kk])
        if len(ks) > 1 and tot(k) < 0.95 * tot(ks[-2]):
            k = ks[-2]
        return W, k

    def lice():
        W, k = bw_week()
        def mean(kk):
            X = [(r['lice'], r['nl']) for r in W.get(kk, []) if num(r.get('lice')) is not None and r.get('nl')]
            return sum(a * b for a, b in X) / sum(b for a, b in X) if X else None
        v = mean(k); ly = mean((k[0] - 1, k[1]))
        return card('lice', round(v, 3), 'adult female lice per fish', f'week {k[1]}, {k[0]}', week_end(*k),
                    'Average adult female lice per fish across the sea sites that reported a count (every site weighs the same), production zones 1–13; latest complete week.',
                    'BarentsWatch Fish Health', 'data/data.json → bw_weekly.rows[].lice, nl', 'weekly', cmp=pct(v, ly), cmp_label=f'vs week {k[1]}, {k[0] - 1}')

    def weight():
        A = recs(); k = max(A)
        w = lambda kk: A[kk]['uttak_kg'] / A[kk]['uttak_stk'] if kk in A and A[kk]['uttak_stk'] else None
        return card('weight', round(w(k), 2), 'kg live weight', mlab(k), month_end(k),
                    'Harvested kilos divided by harvested fish in the month, live weight (about 0.888 of it gutted), all production zones.',
                    SRC, 'data/data.json → records[].uttak_kg / uttak_stk', 'monthly', cmp=pct(w(k), w(k - 100)), cmp_label=f'vs {mlab(k - 100)}')

    def sites():
        W, k = bw_week()
        n = lambda kk: sum(r.get('na') or 0 for r in W[kk]) if kk in W else None
        return card('sites', n(k), 'sea sites', f'week {k[1]}, {k[0]}', week_end(*k),
                    'Sea sites with a salmonid licence that reported lice and were not fallow that week (slaughter holding cages left out); latest complete week.',
                    'BarentsWatch Fish Health', 'data/data.json → bw_weekly.rows[].na', 'weekly', cmp=pct(n(k), n((k[0] - 1, k[1]))), cmp_label=f'vs week {k[1]}, {k[0] - 1}')

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', lambda: outlook('NO'))]


# ---------------------------------------------------------------- Chili
def chile():
    def reports():
        """Rapports sectoriels Subpesca : cumul de recolte de saumon atlantique depuis janvier, par mois de fin."""
        R = {}
        for r in load('chile_subpesca.json').get('reports') or []:
            s = (r.get('species') or {}).get('salar') or {}
            if r.get('k') and num(s.get('cum_kt')) is not None:
                R[int(r['k'])] = s
        return R
    SRC = 'Subpesca monthly sector reports (Sernapesca preliminary figures)'
    FILE = 'data/chile_subpesca.json → reports[].species.salar.cum_kt'

    def cmp_cum(R, k):
        """Variation sur un an du cumul : recalculee si le rapport d'un an plus tot est la, sinon celle que publie Subpesca."""
        if k - 100 in R:
            return pct(R[k]['cum_kt'], R[k - 100]['cum_kt'])
        return num(R[k].get('var_pct'))

    def harvest_year():
        R = reports(); y = max(k // 100 for k in R if k % 100 == 12); k = y * 100 + 12
        return card('harvest_year', round(R[k]['cum_kt'] * 1000), 'tonnes live weight', str(y), dt.date(y, 12, 31),
                    'Atlantic salmon only (coho and trout left out), harvest accumulated January–December, harvest (live) weight, preliminary.',
                    SRC, FILE, 'annual', cmp=cmp_cum(R, k), cmp_label=f'vs {y - 1}')

    def harvest_recent():
        R = reports(); k = max(R); y, m = divmod(k, 100)
        note = None
        if m > 1 and k - 1 in R:
            a = (R[k]['cum_kt'] - R[k - 1]['cum_kt']) * 1000
            b = (R[k - 100]['cum_kt'] - R[k - 101]['cum_kt']) * 1000 if k - 100 in R and k - 101 in R else None
            note = f'{mlab(k)} alone (difference of two cumulative reports): {fmt(a)} t' + (f' ({sg(pct(a, b))} % vs {mlab(k - 100)}).' if pct(a, b) is not None else '.')
        return card('harvest_recent', round(R[k]['cum_kt'] * 1000), 'tonnes live weight', f'Jan–{MON[m - 1]} {y}', month_end(k),
                    'Atlantic salmon only, harvest accumulated since January, harvest (live) weight, preliminary.',
                    SRC, FILE, 'monthly', cmp=cmp_cum(R, k), cmp_label=f'vs Jan–{MON[m - 1]} {y - 1}', note=note)

    def sernapesca_monthly(field):
        """Series mensuelles du rapport sanitaire annuel du Sernapesca : {annee: [12 mois]} -> (cle AAAAMM, valeur, un an avant)."""
        S = ((load('chili.json').get('biologie') or {}).get('sanitaire') or {}).get(field) or {}
        y = max(int(a) for a in S); vals = S[str(y)]
        i = max(j for j, v in enumerate(vals) if num(v) is not None)
        prev = S.get(str(y - 1)) or []
        return y * 100 + i + 1, vals[i], (prev[i] if i < len(prev) else None)

    def outlook_point():
        P = [p for p in ((load('chili.json').get('salmon_outlook') or {}).get('points') or []) if p.get('k')]
        return max(P, key=lambda p: p['k']) if P else None

    def stock():
        k, v, ly = sernapesca_monthly('biomasse_mer_t')
        note = None
        p = outlook_point()
        if p and p['k'] > k and num(((p.get('species') or {}).get('salar') or {}).get('t')) is not None:
            note = (f'Fresher but unofficial: {fmt(p["species"]["salar"]["t"])} t of Atlantic salmon ({fmt(p["total_t"])} t all salmonids) at the end of {mlab(p["k"])} '
                    f'(Salmon Outlook figures quoted by Salmonexpert, entered by hand; no year-earlier point).')
        return card('stock', round(v), 'tonnes live weight', f'end of {mlab(k)}', month_end(k),
                    'Biomass at sea of all farmed salmonids (Atlantic salmon, coho, trout), monthly series of Sernapesca\'s yearly health report; Chile publishes no current biomass for free.',
                    'Sernapesca, yearly salmon-farming health report', 'data/chili.json → biologie.sanitaire.biomasse_mer_t', 'annual',
                    cmp=pct(v, ly), cmp_label=f'vs {mlab(k - 100)}', note=note)

    def mortality():
        D = load('disease_manual.json')['CL']; ys = D['cycle_years']; v = D['cycle_mortality_pct']['Atlantic salmon']
        i = max(range(len(ys)), key=lambda j: ys[j]); y = ys[i]
        prev = v[ys.index(y - 1)] if y - 1 in ys else None
        return card('mortality', v[i], '% of fish over the cycle', str(y), dt.date(y, 12, 31),
                    'Atlantic salmon: share of the fish put to sea that died, on farms harvested in the year (closed cycles, count). A whole-cycle figure, not a monthly rate.',
                    D.get('source') or 'Sernapesca', 'data/disease_manual.json → CL.cycle_mortality_pct', 'annual', cmp=pts(v[i], prev), cmp_kind='pts', cmp_label=f'vs {y - 1}')

    def lice():
        C = load('chile_caligus.json'); E = C.get('entries') or []
        d = []
        for e in E:
            y, w = str(e.get('week', '')).split('-W'); d.append(dt.date.fromisocalendar(int(y), int(w), 4))
        ver = max(str(v.get('version')) for v in C.get('versions') or [])
        ver = dt.date(int(ver[:4]), int(ver[4:6]), int(ver[6:8]))
        # dernier trimestre termine ET couvert par la derniere version de la liste
        y, q = TODAY.year, (TODAY.month - 1) // 3 + 1
        for _ in range(6):
            q -= 1
            if q == 0:
                y, q = y - 1, 4
            if quarter_end(y, q) <= ver:
                break
        inq = lambda yy: sum(1 for x in d if x.year == yy and (x.month - 1) // 3 + 1 == q)
        v = inq(y); ly = inq(y - 1) if min(d) <= dt.date(y - 1, 3 * q - 2, 7) else None
        return card('lice', v, 'farm listings in the quarter', f'Q{q} {y}', quarter_end(y, q),
                    'Number of times a farm was listed as a high-dissemination centre: 3 or more egg-bearing female lice (Caligus) per fish at the check after the treatment window. '
                    'Chile publishes no farm-by-farm lice counts, so this count of flagged farms is the local measure.',
                    'Sernapesca, sea-lice programme: list of high-dissemination centres', 'data/chile_caligus.json → entries[].week', 'irregular',
                    cmp=pct(v, ly), cmp_label=f'vs Q{q} {y - 1}')

    def weight():
        H = load('chile_harvest_weights.json').get('companies') or {}
        Q = {c: {r['q']: r for r in rows if r.get('q') and num(r.get('kg')) and num(r.get('harvest_t'))} for c, rows in H.items()}
        q = max(k for v in Q.values() for k in v); ql = f'{int(q[:4]) - 1}{q[4:]}'
        both = [c for c in Q if q in Q[c] and ql in Q[c]]
        cos = both or [c for c in Q if q in Q[c]]
        w = lambda qq: sum(Q[c][qq]['harvest_t'] for c in cos) / sum(Q[c][qq]['harvest_t'] / Q[c][qq]['kg'] for c in cos)
        t = sum(Q[c][q]['harvest_t'] for c in cos)
        return card('weight', round(w(q), 2), 'kg whole-fish equivalent', f'Q{q[-1]} {q[:4]}', quarter_end(q[:4], q[-1]),
                    'Company figures, not a national average (none is published): Atlantic salmon harvested tonnes divided by harvested fish for the listed farmers that reported this quarter and the same quarter a year earlier.',
                    'Company quarterly reports (filed with the Chilean market regulator)', 'data/chile_harvest_weights.json → companies', 'quarterly',
                    cmp=pct(w(q), w(ql)) if both else None, cmp_label=f'vs Q{q[-1]} {ql[:4]}', note=f'Companies: {", ".join(cos)} ({fmt(t)} t harvested in the quarter).')

    def sites():
        k, v, ly = sernapesca_monthly('centres_mer')
        note = None
        p = outlook_point()
        if p and p['k'] > k and num(p.get('centres')) is not None:
            note = f'Fresher but unofficial: {p["centres"]} farms with fish at the end of {mlab(p["k"])} (Salmon Outlook quoted by Salmonexpert; may not count the same way).'
        return card('sites', v, 'sea farms', mlab(k), month_end(k),
                    'Sea farms in operation, all salmonids, monthly series of Sernapesca\'s yearly health report.',
                    'Sernapesca, yearly salmon-farming health report', 'data/chili.json → biologie.sanitaire.centres_mer', 'annual',
                    cmp=pct(v, ly), cmp_label=f'vs {mlab(k - 100)}', note=note)

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', lambda: outlook('CL'))]


# ---------------------------------------------------------------- Ecosse
def scotland():
    def harvest_year():
        S = load('scotland_survey.json'); P = {int(k): v for k, v in (S.get('production') or {}).items() if num(v) is not None}
        y = max(P)
        return card('harvest_year', round(P[y]), 'tonnes live weight', str(y), dt.date(y, 12, 31),
                    'Official yearly production of Atlantic salmon, live (wet) weight at harvest.',
                    'Scottish Fish Farm Production Survey (Marine Directorate)', 'data/scotland_survey.json → production', 'annual',
                    cmp=pct(P[y], P.get(y - 1)), cmp_label=f'vs {y - 1}')

    def harvest_recent():
        C = load('scotland_companies.json').get('companies') or {}
        ys = sorted({int(k) for c in C.values() for k in (c.get('ytd') or {}) if str(k).isdigit()})
        y = ys[-1]; tos = {(c.get('ytd') or {}).get('to') for c in C.values()}
        if len(tos) != 1:
            raise ValueError('the companies do not report to the same quarter')
        q = int(re.search(r'Q(\d)', tos.pop()).group(1))
        tot = lambda yy: sum(c['ytd'][str(yy)] for c in C.values()) if all(num((c.get('ytd') or {}).get(str(yy))) is not None for c in C.values()) else None
        share = sum(c.get('share_2025_pct') or 0 for c in C.values())
        qk, qkl = f'{y}Q{q}', f'{y - 1}Q{q}'
        note = None
        if all(num((c.get('quarters') or {}).get(qk)) is not None and num((c.get('quarters') or {}).get(qkl)) is not None for c in C.values()):
            a, b = sum(c['quarters'][qk] for c in C.values()), sum(c['quarters'][qkl] for c in C.values())
            note = f'Q{q} {y} alone: {fmt(a)} t ({sg(pct(a, b))} % vs Q{q} {y - 1}).'
        return card('harvest_recent', round(tot(y)), 'tonnes gutted weight', f'Q1–Q{q} {y}' if q > 1 else f'Q1 {y}', quarter_end(y, q),
                    f'Harvest of the listed farmers that report every quarter ({", ".join(C)}; about {share} % of Scottish harvest), gutted weight. No national monthly or quarterly harvest is published.',
                    'Company quarterly reports', 'data/scotland_companies.json → companies[].ytd', 'quarterly',
                    cmp=pct(tot(y), tot(y - 1)), cmp_label=f'vs Q1–Q{q} {y - 1}', note=note)

    def stock():
        S = {ym(x['k']): x for x in load('scotland_weekly.json').get('sepa') or [] if num(x.get('t')) is not None}
        k = max(S); v = S[k]['t'] * 1000; ly = S[k - 100]['t'] * 1000 if k - 100 in S else None
        return card('stock', round(v), 'tonnes live weight', f'end of {mlab(k)}', month_end(k),
                    'Biomass at sea summed over the farms\' monthly returns to the environment agency (published months in arrears).',
                    'SEPA monthly farm returns', 'data/scotland_weekly.json → sepa[].t', 'monthly', cmp=pct(v, ly), cmp_label=f'vs {mlab(k - 100)}')

    def mortality():
        M = load('scotland_weekly.json').get('mort') or {}
        I = {ym(k): v for k, v in (M.get('industry') or {}).items() if num(v) is not None}
        k = max(I)
        note = None
        B = {ym(a): b for a, b in (M.get('by_month') or {}).items()}
        if B and max(B) > k:
            kb = max(B); x, xl = B[kb], B.get(kb - 100)
            note = f'Fresher farm-level reports, {mlab(kb)}: {x.get("over5")} of {x.get("active")} reporting farms lost more than 5 % of their fish in the month'
            note += f' ({xl.get("over5")} of {xl.get("active")} in {mlab(kb - 100)}).' if xl else '.'
            note += ' The industry-wide rate is not in the repo after ' + mlab(k) + '.'
        return card('mortality', I[k], '% of fish in the month', mlab(k), month_end(k),
                    'Industry-wide monthly mortality: fish lost in the month as a share of the fish on the farms, as published in the header of the trade body\'s monthly report.',
                    'Salmon Scotland, monthly mortality report', 'data/scotland_weekly.json → mort.industry', 'monthly',
                    cmp=pts(I[k], I.get(k - 100)), cmp_kind='pts', cmp_label=f'vs {mlab(k - 100)}', note=note)

    def lice():
        W = load('scotland_weekly.json'); M = {ym(x['k']): x for x in W.get('months') or [] if num(x.get('af')) is not None}
        k = max(M); last = dt.date.fromisoformat((W.get('meta') or {})['last_week']) + dt.timedelta(days=6)
        asof = min(month_end(k), last) if ym(last.strftime('%Y%m')) >= k else month_end(k)
        return card('lice', M[k]['af'], 'adult female lice per fish', mlab(k), asof,
                    'Average of the weekly site counts of adult female lice per fish in the month (every count weighs the same; sites not counted that week are left out).',
                    'Scottish Government, weekly sea-lice counts by site', 'data/scotland_weekly.json → months[].af', 'weekly',
                    cmp=pct(M[k]['af'], (M.get(k - 100) or {}).get('af')), cmp_label=f'vs {mlab(k - 100)}')

    def weight():
        B = load('scotland_survey.json').get('by_class') or {}
        y = max(int(k) for k in B)
        def w(yy):
            X = [v for v in (B.get(str(yy)) or {}).values() if num(v[0]) and num(v[1])]
            return sum(t for t, kg in X) / sum(t / kg for t, kg in X) if X else None
        return card('weight', round(w(y), 2), 'kg live weight', str(y), dt.date(y, 12, 31),
                    'Official yearly production divided by the fish harvested, from the survey\'s tonnes and mean weight by year class; live weight.',
                    'Scottish Fish Farm Production Survey (Marine Directorate)', 'data/scotland_survey.json → by_class', 'annual',
                    cmp=pct(w(y), w(y - 1)), cmp_label=f'vs {y - 1}')

    def sites():
        W = load('scotland_weekly.json'); x = (W.get('weeks') or [])[-1]; d = dt.date.fromisoformat(x['d'])
        v = sum(x.get(f) or 0 for f in ('n', 'wd', 'stocked', 'vet'))
        ly = next((sum(z.get(f) or 0 for f in ('n', 'wd', 'stocked', 'vet')) for z in W.get('weeks') or [] if z.get('d') == (d - dt.timedelta(days=364)).isoformat()), None)
        A = (load('scotland_survey.json').get('companies') or {}).get('active_sites')
        y = max(int(k) for k in load('scotland_survey.json').get('production') or {'0': 0})
        note = f'The official yearly survey counts {A} active sea sites in {y} (any site used during the year).' if A else None
        return card('sites', v, 'sea sites', f'week of {d.day} {MON[d.month - 1]} {d.year}', d + dt.timedelta(days=6),
                    'Sites holding fish in the weekly sea-lice returns: sites with a count, plus sites not counted because of a withdrawal period before harvest, recent stocking or veterinary advice. Fallow sites left out.',
                    'Scottish Government, weekly sea-lice counts by site', 'data/scotland_weekly.json → weeks[] (n + wd + stocked + vet)', 'weekly',
                    cmp=pct(v, ly), cmp_label='vs same week a year earlier', note=note)

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', lambda: outlook('GB'))]


# ---------------------------------------------------------------- Feroe
def faroe():
    SRC = 'Faroese Food and Veterinary Authority (HFS)'

    def hfs():
        H = load('faroe_hfs.json'); M = H.get('meta') or {}
        return H, int(M['LY']), int(M['LW']), {int(x['y']): x for x in H.get('years') or []}

    def harvest_year():
        H, LY, LW, Y = hfs(); y = LY - 1
        v = Y[y]['kt'] * 1000; p = Y[y - 1]['kt'] * 1000 if y - 1 in Y else None
        return card('harvest_year', round(v), 'tonnes gutted weight', str(y), dt.date(y, 12, 31),
                    'National salmon harvest summed over the weekly slaughter statistics, gutted weight.',
                    SRC + ', weekly slaughter statistics', 'data/faroe_hfs.json → years[].kt', 'annual', cmp=pct(v, p), cmp_label=f'vs {y - 1}')

    def harvest_recent():
        H, LY, LW, Y = hfs()
        v = Y[LY]['ytd']['kt'] * 1000; p = Y[LY - 1]['ytd']['kt'] * 1000 if LY - 1 in Y else None
        note = None
        wk = next((x for x in H.get('weekly') or [] if x.get('w') == LW), None)
        if wk and wk.get(str(LY)):
            a = wk[str(LY)]['kt'] * 1000; b = (wk.get(str(LY - 1)) or {}).get('kt')
            note = f'Week {LW} alone: {fmt(a)} t' + (f' ({sg(pct(a, b * 1000))} % vs week {LW}, {LY - 1}).' if b else '.')
        return card('harvest_recent', round(v), 'tonnes gutted weight', f'weeks 1–{LW}, {LY}', week_end(LY, LW),
                    'National salmon harvest since week 1, weekly slaughter statistics, gutted weight.',
                    SRC + ', weekly slaughter statistics', 'data/faroe_hfs.json → years[].ytd.kt', 'weekly', cmp=pct(v, p), cmp_label=f'vs weeks 1–{LW}, {LY - 1}', note=note)

    def stock():
        H = load('faroe_hfs.json'); S = {int(x['k']): x for x in H.get('stock') or []}
        k = max(S); tot = lambda kk: sum(v for a, v in S[kk].items() if a != 'k' and num(v) is not None) if kk in S else None
        return card('stock', round(tot(k), 2), 'million fish', f'end of {mlab(k)}', month_end(k),
                    'Number of salmon in the sea at the end of the month, all farmers (fish counts by site; no national biomass in tonnes is published).',
                    SRC + ', fish by site', 'data/faroe_hfs.json → stock[]', 'monthly', cmp=pct(tot(k), tot(k - 100)), cmp_label=f'vs {mlab(k - 100)}')

    def mortality():
        A = {int(k): v for k, v in ((load('faroe.json').get('annual') or {}).get('mortality_pct') or {}).items() if num(v) is not None}
        y = max(A)
        return card('mortality', A[y], '% of fish in the year', str(y), dt.date(y, 12, 31),
                    'Company figure, not national: share of Bakkafrost\'s fish in the Faroes that died in the year. The Faroese authority publishes no national mortality rate.',
                    'Bakkafrost, sustainability data page', 'data/faroe.json → annual.mortality_pct', 'annual',
                    cmp=pts(A[y], A.get(y - 1)), cmp_kind='pts', cmp_label=f'vs {y - 1}')

    def lice():
        H, LY, LW, Y = hfs(); L = H.get('lice') or []
        W = [x for x in L if x.get(str(LY)) and num(x[str(LY)].get('m')) is not None and x[str(LY)].get('n')][-4:]
        mean = lambda yy, X: sum(x[str(yy)]['m'] * x[str(yy)]['n'] for x in X) / sum(x[str(yy)]['n'] for x in X)
        v = mean(LY, W); n = sum(x[str(LY)]['n'] for x in W)
        ok = all(x.get(str(LY - 1)) and x[str(LY - 1)].get('n') for x in W)
        ly = mean(LY - 1, W) if ok else None
        w0, w1 = W[0]['w'], W[-1]['w']
        last = (H.get('meta') or {}).get('lice_last')
        asof = min(week_end(LY, w1), dt.date.fromisoformat(last)) if last else week_end(LY, w1)
        return card('lice', round(v, 2), 'adult female lice per fish', f'weeks {w0}–{w1}, {LY}', asof,
                    f'Average of the site counts of adult female lice per fish over the latest four weeks with counts ({n} counts; every count weighs the same). The latest week can still be incomplete.',
                    SRC + ', lice counts by site', 'data/faroe_hfs.json → lice[]', 'weekly', cmp=pct(v, ly), cmp_label=f'vs weeks {w0}–{w1}, {LY - 1}')

    def weight():
        H, LY, LW, Y = hfs()
        v = Y[LY]['ytd']['w']; p = (Y.get(LY - 1) or {}).get('ytd', {}).get('w')
        return card('weight', v, 'kg gutted weight', f'weeks 1–{LW}, {LY}', week_end(LY, LW),
                    'Harvested kilos divided by harvested fish since week 1, national weekly slaughter statistics, gutted weight.',
                    SRC + ', weekly slaughter statistics', 'data/faroe_hfs.json → years[].ytd.w', 'weekly', cmp=pct(v, p), cmp_label=f'vs weeks 1–{LW}, {LY - 1}')

    def sites():
        H = load('faroe_hfs.json'); S = H.get('sites') or []
        v = sum(1 for s in S if (s.get('fish') or 0) > 0)
        d = dt.date.fromisoformat((H.get('meta') or {})['stock_date'])
        return card('sites', v, 'sea sites', f'end of {MON[d.month - 1]} {d.year}', d,
                    f'Sea sites holding fish at the end of the month, out of {len(S)} sites in the fish-by-site file. The repo keeps no site list for a year earlier, so there is no comparison.',
                    SRC + ', fish by site', 'data/faroe_hfs.json → sites[].fish', 'monthly')

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', lambda: outlook('FO'))]


# ---------------------------------------------------------------- Islande
def iceland():
    SRC = 'MAST (Icelandic Food and Veterinary Authority), aquaculture dashboard'

    def nat():
        return {ym(r['m']): r for r in load('iceland_mast.json').get('national') or []}

    def harvest_year():
        N = nat(); full = [y for y in sorted({k // 100 for k in N}) if all(y * 100 + m in N for m in range(1, 13))]
        y = full[-1]; tot = lambda yy: sum(N[yy * 100 + m].get('harvest_t') or 0 for m in range(1, 13))
        return card('harvest_year', round(tot(y)), 'tonnes (slaughtered biomass)', str(y), dt.date(y, 12, 31),
                    'Atlantic salmon from sea farms, slaughtered biomass summed over the twelve months of the dashboard (land-based farms left out; the file does not say whether the weight is live or gutted).',
                    SRC, 'data/iceland_mast.json → national[].harvest_t', 'annual', cmp=pct(tot(y), tot(y - 1)) if y - 1 in full else None, cmp_label=f'vs {y - 1}')

    def harvest_recent():
        N = nat(); k = max(N); y, m = divmod(k, 100)
        ytd = sum(N[y * 100 + i].get('harvest_t') or 0 for i in range(1, m + 1) if y * 100 + i in N)
        have = all((y - 1) * 100 + i in N for i in range(1, m + 1)) and all(y * 100 + i in N for i in range(1, m + 1))
        ly = sum(N[(y - 1) * 100 + i].get('harvest_t') or 0 for i in range(1, m + 1)) if have else None
        a, b = N[k].get('harvest_t'), (N.get(k - 100) or {}).get('harvest_t')
        note = f'{mlab(k)} alone: {fmt(a)} t' + (f' ({sg(pct(a, b))} % vs {mlab(k - 100)}).' if pct(a, b) is not None else '.')
        return card('harvest_recent', round(ytd), 'tonnes (slaughtered biomass)', f'Jan–{MON[m - 1]} {y}', month_end(k),
                    'Atlantic salmon from sea farms, slaughtered biomass since January (weight basis not stated in the file).',
                    SRC, 'data/iceland_mast.json → national[].harvest_t', 'monthly', cmp=pct(ytd, ly), cmp_label=f'vs Jan–{MON[m - 1]} {y - 1}', note=note)

    def stock():
        N = nat(); k = max(N); v = N[k].get('biomass_t'); ly = (N.get(k - 100) or {}).get('biomass_t')
        return card('stock', round(v), 'tonnes live weight', f'end of {mlab(k)}', month_end(k),
                    'Biomass of Atlantic salmon in sea cages at the end of the month, all sea farms.',
                    SRC, 'data/iceland_mast.json → national[].biomass_t', 'monthly', cmp=pct(v, ly), cmp_label=f'vs {mlab(k - 100)}')

    def mortality():
        N = nat(); k = max(N)
        r = lambda kk: 100 * N[kk]['mortality_t'] / N[kk]['biomass_t'] if kk in N and num(N[kk].get('mortality_t')) is not None and N[kk].get('biomass_t') else None
        return card('mortality', round(r(k), 2), '% of biomass in the month', mlab(k), month_end(k),
                    'Tonnes of dead fish in the month divided by the biomass at sea at the end of that month. A weight-based rate: not directly comparable with rates counted in fish.',
                    SRC, 'data/iceland_mast.json → national[].mortality_t / biomass_t', 'monthly', cmp=pts(r(k), r(k - 100)), cmp_kind='pts', cmp_label=f'vs {mlab(k - 100)}')

    def lice():
        return missing('lice', 'No lice level in the repo for Iceland: the builder reads only the sea temperature from MAST\'s lice reports, not the lice counts themselves.',
                       source=SRC, file='data/iceland_mast.json (no lice field)')

    def weight():
        I = load('iceland_mast.json'); N = nat(); k = ym(I.get('sites_last_month') or max(N))
        out = collections.defaultdict(float)
        for s in I.get('sites') or []:
            out[ym(s['m'])] += s.get('out') or 0
        w = lambda kk: N[kk]['harvest_t'] * 1000 / out[kk] if kk in N and N[kk].get('harvest_t') and out.get(kk) else None
        return card('weight', round(w(k), 2), 'kg (slaughtered biomass per fish)', mlab(k), month_end(k),
                    'Slaughtered tonnes of the month divided by the fish taken out of the sites (harvested fish, discards included), sea-farmed Atlantic salmon. Our own division of two dashboard series, not a published weight.',
                    SRC, 'data/iceland_mast.json → national[].harvest_t / sum of sites[].out', 'monthly', cmp=pct(w(k), w(k - 100)), cmp_label=f'vs {mlab(k - 100)}')

    def sites():
        I = load('iceland_mast.json'); n = collections.Counter(ym(s['m']) for s in I.get('sites') or [] if (s.get('fish') or 0) > 0)
        k = ym(I.get('sites_last_month') or max(n))
        return card('sites', n.get(k, 0), 'sea sites', f'end of {mlab(k)}', month_end(k),
                    'Sea sites holding Atlantic salmon at the end of the month (site-by-site fish counts).',
                    SRC, 'data/iceland_mast.json → sites[].fish', 'monthly', cmp=pct(n.get(k, 0), n.get(k - 100)), cmp_label=f'vs {mlab(k - 100)}')

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', lambda: outlook('IS'))]


# ---------------------------------------------------------------- Canada
def canada():
    DFO = 'Fisheries and Oceans Canada (DFO), British Columbia public reporting'

    def harvest_year():
        C = load('canada.json'); P = {int(y): ((v.get('Salmon') or {}).get('Canada')) for y, v in (C.get('provinces') or {}).items()}
        P = {y: v for y, v in P.items() if num(v) is not None}
        y = max(P); provs = [p for p in (C['provinces'][str(y)].get('Salmon') or {}) if p != 'Canada']
        note = '; '.join(f'{x.get("prov")} {x.get("year")}, from its own report: {fmt(x["t"])} t ({x.get("what")})' for x in C.get('provinces_extra') or [] if num(x.get('t')) is not None) or None
        return card('harvest_year', round(P[y]), 'tonnes (as published, weight basis not stated in the repo)', str(y), dt.date(y, 12, 31),
                    f'Farmed salmon production, sum of the provinces Statistics Canada publishes ({", ".join(provs)}). Provinces it suppresses are left out, Newfoundland and Labrador among them when not listed. The latest year published lags by more than a year.',
                    'Statistics Canada, aquaculture production by province', 'data/canada.json → provinces[year].Salmon.Canada', 'annual',
                    cmp=pct(P[y], P.get(y - 1)), cmp_label=f'vs {y - 1}', note=note)

    def harvest_recent():
        T = load('canada_trade.json'); M = collections.defaultdict(float)
        for r in T.get('rows') or []:
            M[int(r[0])] += r[5] or 0
        k = int((T.get('meta') or {}).get('last') or max(M)); y, m = divmod(k, 100)
        s = lambda yy: sum(M.get(yy * 100 + i, 0) for i in range(1, m + 1))
        have = all((y - 1) * 100 + i in M for i in range(1, m + 1))
        a, b = M.get(k), M.get(k - 100)
        note = f'{mlab(k)} alone: {fmt(a)} t' + (f' ({sg(pct(a, b))} % vs {mlab(k - 100)}).' if pct(a, b) is not None else '.')
        return card('harvest_recent', round(s(y)), 'tonnes product weight (exports)', f'Jan–{MON[m - 1]} {y}', month_end(k),
                    'Exports, not harvest (no monthly harvest is published): domestic exports of farmed Atlantic salmon since January, all provinces and product forms added as shipped (whole and fillets, not converted to whole fish).',
                    'Statistics Canada, merchandise trade database', 'data/canada_trade.json → rows[] (tonnes)', 'monthly',
                    cmp=pct(s(y), s(y - 1)) if have else None, cmp_label=f'vs Jan–{MON[m - 1]} {y - 1}', note=note)

    def stock():
        return missing('stock', 'No public figure: Canada publishes neither a national biomass nor fish numbers at sea (the federal files for British Columbia give stages and percentages per site, no fish or tonnes).',
                       source=DFO, file='data/canada_bc.json → meta.note')

    def mortality():
        B = load('canada_bc.json'); M = {int(x['k']): x for x in B.get('months') or [] if num(x.get('mort')) is not None}
        k = max(M)
        return card('mortality', M[k]['mort'], '% of fish in the month', mlab(k), month_end(k),
                    f'British Columbia only: simple average over the sea sites ({M[k].get("sites")} sites) of the monthly mortality percentage each site reports, Atlantic salmon. Nothing comparable is published for Atlantic Canada.',
                    DFO + ', carcass classification by facility', 'data/canada_bc.json → months[].mort', 'monthly',
                    cmp=pts(M[k]['mort'], (M.get(k - 100) or {}).get('mort')), cmp_kind='pts', cmp_label=f'vs {mlab(k - 100)}')

    def lice():
        C = load('canada.json'); L = {int(x['m']): x for x in C.get('lice') or [] if num(x.get('lice')) is not None}
        k = int((C.get('meta') or {}).get('lice_complete') or max(L))
        return card('lice', L[k]['lice'], 'motile lice per fish', mlab(k), month_end(k),
                    f'British Columbia only: average over sites ({L[k].get("sites")} sites reporting) of motile sea lice (Lepeophtheirus salmonis, all mobile stages, not only adult females) per fish at routine counts; latest complete month.',
                    DFO + ', sea-lice counts', 'data/canada.json → lice[].lice', 'monthly',
                    cmp=pct(L[k]['lice'], (L.get(k - 100) or {}).get('lice')), cmp_label=f'vs {mlab(k - 100)}')

    def weight():
        return missing('weight', 'No public figure: no average harvest weight is published for Canada, and the federal site files give neither fish numbers nor tonnes to work one out.',
                       source=DFO, file='data/canada_bc.json → meta.note')

    def sites():
        B = load('canada_bc.json'); S = {int(x['k']): x.get('sites') for x in B.get('stocked_same_month') or []}
        k = max(S)
        return card('sites', S[k], 'sea sites', mlab(k), month_end(k),
                    'British Columbia only: sea sites with a monthly report in the federal carcass file that month, that is, sites holding Atlantic salmon. No count of stocked sites is published for Atlantic Canada.',
                    DFO + ', carcass classification by facility', 'data/canada_bc.json → stocked_same_month[]', 'monthly',
                    cmp=pct(S[k], S.get(k - 100)), cmp_label=f'vs {mlab(k - 100)}')

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', lambda: outlook('CA'))]


# ---------------------------------------------------------------- Tasmanie
def australia():
    def fy():
        P = collections.defaultdict(float); lab = {}
        for r in load('australia.json').get('production') or []:
            if num(r.get('t')) is not None:
                P[int(r['fy_end'])] += r['t']; lab[int(r['fy_end'])] = r.get('fy')
        return P, lab

    def harvest_year():
        P, lab = fy(); y = max(P)
        return card('harvest_year', round(P[y]), 'tonnes (as published, weight basis not stated in the repo)', f'financial year {lab[y]} (July–June)', dt.date(y, 6, 30),
                    'Tasmanian salmon production added over the companies, by financial year ending 30 June.',
                    'NRE Tasmania, salmon farming portal', 'data/australia.json → production[]', 'annual',
                    cmp=pct(P[y], P.get(y - 1)), cmp_label=f'vs {lab.get(y - 1, y - 1)}')

    def harvest_recent():
        T = load('national_trade.json'); M = collections.defaultdict(float)
        for r in T.get('rows') or []:
            if r[1] == 'AU':
                M[int(r[0])] += r[4] or 0
        k = max(M); y, m = divmod(k, 100)
        s = lambda yy: sum(M.get(yy * 100 + i, 0) for i in range(1, m + 1))
        have = all((y - 1) * 100 + i in M for i in range(1, m + 1))
        a, b = M.get(k), M.get(k - 100)
        note = f'{mlab(k)} alone: {fmt(a)} t' + (f' ({sg(pct(a, b))} % vs {mlab(k - 100)}).' if pct(a, b) is not None else '.')
        return card('harvest_recent', round(s(y)), 'tonnes product weight (exports)', f'Jan–{MON[m - 1]} {y}', month_end(k),
                    'Exports, not harvest (no monthly or quarterly harvest is published): Australian salmon exports since January, all product forms added as shipped. Exports are well below the yearly production, so they show only part of the volume.',
                    'UN Comtrade, exports reported by Australia', 'data/national_trade.json → rows[] (origin AU, tonnes)', 'monthly',
                    cmp=pct(s(y), s(y - 1)) if have else None, cmp_label=f'vs Jan–{MON[m - 1]} {y - 1}', note=note)

    def stock():
        return missing('stock', 'No public figure: Tasmania publishes no biomass or fish numbers at sea (the repo holds a single company figure from one access-to-information release).',
                       source='EPA Tasmania / NRE Tasmania', file='data/australia.json → company_points')

    def mortality():
        M = {int(x['m']): x.get('total') for x in load('australia.json').get('mortality') or [] if num(x.get('total')) is not None}
        k = max(M); y, m = divmod(k, 100)
        s = lambda yy: sum(M[yy * 100 + i] for i in range(1, m + 1)) if all(yy * 100 + i in M for i in range(1, m + 1)) else None
        note = None
        if s(y) is not None:
            note = f'Jan–{MON[m - 1]} {y}: {fmt(s(y))} t' + (f' ({sg(pct(s(y), s(y - 1)))} % vs Jan–{MON[m - 1]} {y - 1}).' if s(y - 1) else '.')
        return card('mortality', round(M[k]), 'tonnes of dead fish in the month', mlab(k), month_end(k),
                    'Tonnes of dead salmon sent for disposal in the month (rendering, compost, landfill, ensiling, burial), all Tasmanian farms. A tonnage, not a rate: no monthly mortality percentage is published.',
                    'EPA Tasmania, salmon mortality waste', 'data/australia.json → mortality[].total', 'monthly',
                    cmp=pct(M[k], M.get(k - 100)), cmp_label=f'vs {mlab(k - 100)}', note=note)

    def lice():
        return missing('lice', 'No public figure: no sea-lice counts are published for Tasmanian salmon farms, and the repo has none.',
                       source='EPA Tasmania / NRE Tasmania', file=None)

    def weight():
        return missing('weight', 'No public figure: no average harvest weight is published for Tasmania, and the repo has no fish numbers to work one out.',
                       source='NRE Tasmania', file=None)

    def sites():
        L = load('australia.json').get('leases') or []
        zones = sorted({str(x.get('zone')) for x in L})
        return missing('sites', f'No count of farms holding fish is published. The repo only lists {len(L)} marine leases of one area ({"; ".join(zones)}), with no stocking status and no history.',
                       source='NRE Tasmania', file='data/australia.json → leases[]')

    def out():
        P, lab = fy(); y = max(P)
        return outlook('AU', year_done=TODAY > dt.date(y, 6, 30))

    return [safe('harvest_year', harvest_year), safe('harvest_recent', harvest_recent), safe('stock', stock), safe('mortality', mortality),
            safe('lice', lice), safe('weight', weight), safe('sites', sites), safe('outlook', out)]


# ---------------------------------------------------------------- sortie
BUILDERS = {'NO': norway, 'CL': chile, 'GB': scotland, 'FO': faroe, 'IS': iceland, 'CA': canada, 'AU': australia}


def main():
    basins = []
    for code, name in BASINS:
        try:
            cards = BUILDERS[code]()
        except Exception as e:  # noqa: BLE001
            cards = [missing(i, f'basin builder failed ({type(e).__name__}: {e})'[:300]) for i, _, _ in INDICATORS]
        # toujours huit cartes, dans l'ordre commun
        by = {c['id']: c for c in cards}
        cards = [by.get(i) or missing(i, 'card not built') for i, _, _ in INDICATORS]
        basins.append({'code': code, 'name': name, 'cards': cards})
    out = {'meta': {'generated': TODAY.isoformat(), 'indicators': [{'id': i, 'label': l} for i, l, _ in INDICATORS],
                    'note': 'Same eight indicators for every basin. Definitions differ between basins: read "measure". "cmp" is a % change, or a difference in points when cmp_kind is "pts". '
                            '"asof" is the end of the period described (for the outlook card, the date the estimate was built); age_days = generated − asof.'},
           'basins': basins}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write('\n')
    for b in basins:
        for c in b['cards']:
            if c['status'] == 'ok':
                print(f"{b['code']} {c['id']:<15} {c['value']:>12} {c['unit'][:28]:<28} {c['period']:<34} {c['asof']} {c['age_days']:>4} j  cmp {c['cmp']} {c['cmp_kind']}")
            else:
                print(f"{b['code']} {c['id']:<15} MISSING  {c['why_missing'][:120]}")
    n = sum(c['status'] == 'ok' for b in basins for c in b['cards'])
    print(f'basin_cards.json : {n} cartes renseignees sur {8 * len(basins)}, {8 * len(basins) - n} manquantes')


if __name__ == '__main__':
    main()
