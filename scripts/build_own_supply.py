#!/usr/bin/env python3
"""
data/own_supply.json : notre propre estimation de l'offre de saumon par bassin, 2025 reel, 2026 estime, 2027 projete,
calculee UNIQUEMENT a partir des donnees primaires du tableau de bord (registres officiels, recoltes mensuelles,
exportations, nos modeles), sans Kontali ni banques. Les estimations d'analystes restent dans data/global_supply.json
et ne servent plus que de comparaison.

Unite commune : milliers de tonnes, poids vide (GWT / equivalent poisson entier vide). Conversions :
  vif -> vide x 0,888 ; filets / 0,62 ; fume / 0,5 ; prepare / 0,67 (rendements usuels du saumon atlantique).

Par bassin (detail dans 'method') :
  NO  registre de biomasse (Fiskeridirektoratet) : recolte mensuelle ; 2027 = scenarios par generation (gen_outlook.json)
  CL  rapports sectoriels mensuels de Subpesca : recolte cumulee de saumon atlantique ; 2027 = rythme du dernier trimestre
  GB  SEPA (biomasse, aliment) + exportations britanniques ; 2027 = biomasse en mer et annonces des societes
  FO  exportations (Hagstova) ; 2027 = annonces de Bakkafrost (societe, pas analyste)
  IS  rapports de MAST ; 2027 = notre simulation ferme par ferme (iceland_outlook.json)
  CA  exportations par province (Statistique Canada, CIMT) ; 2027 = cycles des fermes de Colombie-Britannique (DFO)
  AU  production par societe (EPA / NRE Tasmanie), exercices juillet-juin ; 2027 = tendance de la mortalite (EPA)

    python3 scripts/build_own_supply.py
"""
import collections
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda f: json.load(open(os.path.join(ROOT, 'data', f), encoding='utf-8'))
OUT = os.path.join(ROOT, 'data', 'own_supply.json')
GUT = 0.888
FAC_NT = {0: 1, 1: 1, 2: 1 / 0.62, 3: 1 / 0.62, 5: 2, 6: 1 / 0.67}      # national_trade.json : formes
FAC_CT = [1, 1 / 0.62, 1, 1 / 0.62, 2]                                  # canada_trade.json
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
pc = lambda a, b: round(100 * (a / b - 1), 1) if a and b else None


def kt(v):
    return round(v / 1000, 1) if v is not None else None


def norway():
    R = D('data.json')['records']
    m = collections.defaultdict(float)
    for r in R:
        m[(r['year'], r['month'])] += (r['uttak_kg'] or 0) * GUT / 1000     # tonnes vides
    last = max(k for k, v in m.items() if v > 0)
    Y, M = last
    y = lambda yy, ms: sum(m.get((yy, mm), 0) for mm in ms)
    v25 = y(Y - 1, range(1, 13))
    ytd, ytd_ly = y(Y, range(1, M + 1)), y(Y - 1, range(1, M + 1))
    G = D('gen_outlook.json')['scenarios']
    per = lambda sc, k: G[sc]['periods'][k]['tot'] / 100
    # reste de l'annee : meme periode un an plus tot x scenario central "3 prochains mois"
    rest_ly = y(Y - 1, range(M + 1, 13))
    e26 = ytd + rest_ly * (1 + per('central', 'next 3 months'))
    # 2027 : Jan-Mar, Apr-Jul, Aug-Sep (scenarios) ; Oct-Dec suppose egal a 2026
    q1, aj, asp, od = y(Y, [1, 2, 3]), y(Y, [4, 5, 6, 7]), y(Y, [8, 9]), e26 - y(Y, range(1, 10))
    def y27(sc):
        return q1 * (1 + per(sc, 'months 4-6')) + aj * (1 + per(sc, 'Apr-Jul 2027')) + asp * (1 + per(sc, 'months 10-12')) + od
    c, lo, hi = y27('central'), min(y27('fade'), y27('fast')), max(y27('fade'), y27('fast'))
    return {'v2025': kt(v25), 'ytd': {'to': f'{MON[M - 1]} {Y}', 'kt': kt(ytd), 'chg': pc(ytd, ytd_ly)}, 'e2026': kt(e26), 'chg2026': pc(e26, v25),
            'c2027': kt(c), 'chg2027': pc(c, e26), 'lo': pc(lo, e26), 'hi': pc(hi, e26),
            'source': 'Fiskeridirektoratet biomass register, monthly harvest by farm (live weight × 0.888)',
            'method': 'Actual harvest to the last month published; rest of the year = same months a year earlier × our generation model (fish at sea, weights, growth, mortality — Generations tab). 2027 = the three generation scenarios (advance fades, central, advance kept), Oct–Dec 2027 assumed equal to 2026.',
            'tab': 'outlook'}


def chile():
    P = [r for r in D('chile_subpesca.json')['reports'] if r.get('k') and (r.get('species') or {}).get('salar')]
    cum = {r['k']: r['species']['salar']['cum_kt'] * 1000 * GUT for r in P}   # tonnes vides
    var = {r['k']: r['species']['salar'].get('var_pct') for r in P}
    last = max(cum); Y, M = divmod(last, 100)
    v25 = cum.get((Y - 1) * 100 + 12)
    ly = lambda k: cum[k] / (1 + var[k] / 100) if var.get(k) is not None else None      # cumul un an plus tot, deduit de la variation publiee
    ytd, ytd_ly = cum[last], ly(last)
    k3 = last - 3 if M > 3 else None
    q_now = ytd - cum[k3] if k3 in cum else None
    q_ly = (ytd_ly - ly(k3)) if k3 in cum and ly(k3) else None
    pace = q_now / q_ly - 1 if q_now and q_ly else (ytd / ytd_ly - 1)
    rest_ly = v25 - ytd_ly
    e26 = ytd + rest_ly * (1 + pace)
    c = e26 * (1 + pace)
    return {'v2025': kt(v25), 'ytd': {'to': f'{MON[M - 1]} {Y}', 'kt': kt(ytd), 'chg': pc(ytd, ytd_ly)}, 'last3': round(100 * pace, 1), 'e2026': kt(e26), 'chg2026': pc(e26, v25),
            'c2027': kt(c), 'chg2027': round(100 * pace, 1), 'lo': round(100 * pace - 7, 1), 'hi': round(100 * pace + 3, 1),
            'source': 'Subpesca monthly sector reports: cumulative Atlantic salmon harvest (live weight × 0.888)',
            'method': f'Actual Atlantic salmon harvest to {MON[M - 1]} {Y}; the last three months ran at {100 * pace:+.1f} % on a year earlier (it was +16 % for 2025 as a whole) — the rest of 2026 and 2027 are carried at that pace. Range skewed down (−7 / +3 points): an extraordinary El Niño and an algae emergency raise the risk of mass mortality; Chile publishes no current biomass for free.',
            'tab': 'chile'}


def exports_wfe(org):
    T = D('national_trade.json')
    rows = [r for r in T['rows'] if r[1] == org]
    m = collections.defaultdict(float)
    for r in rows:
        m[r[0]] += r[4] * FAC_NT.get(r[3], 1)
    return m, max(m)


def from_exports(org, src, lo, hi, c27, method, tab, extra=None):
    m, last = exports_wfe(org); Y, M = divmod(last, 100)
    y = lambda yy, ms: sum(m.get(yy * 100 + mm, 0) for mm in ms)
    v25, ytd, ytd_ly = y(Y - 1, range(1, 13)), y(Y, range(1, M + 1)), y(Y - 1, range(1, M + 1))
    e26 = ytd + y(Y - 1, range(M + 1, 13)) * (ytd / ytd_ly if ytd_ly else 1)
    o = {'v2025': kt(v25), 'ytd': {'to': f'{MON[M - 1]} {Y}', 'kt': kt(ytd), 'chg': pc(ytd, ytd_ly)}, 'e2026': kt(e26), 'chg2026': pc(e26, v25),
         'chg2027': c27, 'c2027': kt(e26 * (1 + c27 / 100)) if c27 is not None else None, 'lo': lo, 'hi': hi, 'source': src, 'method': method, 'tab': tab}
    if extra:
        o.update(extra)
    return o


def faroe():
    return from_exports('FO', 'Hagstova (Statistics Faroe Islands): salmon exports by month, converted to whole-fish equivalent', -5, 5, 0,
                        'Almost all Faroese salmon is exported, so exports measure the harvest month by month. 2026 = exports to date + the rest of the year at the same pace. 2027: Bakkafrost — most of Faroese salmon — plans the same Faroese harvest in 2027 as in 2026 (97,000 t) with as many smolts put to sea; we keep 0 % ± 5.', 'faroe')


def scotland():
    s = D('scotland.json'); n = s['national']; last = max(n); ly = int(last[:4]) if last.endswith('12') else int(last[:4]) - 1
    get = lambda y, i: sum(v[i] for k, v in n.items() if k.startswith(str(y)))
    FCRB = 1.22   # aliment par kg de croissance (rapport biologique), ordre de grandeur ecossais

    def harvest(y):   # bilan de masse : croissance (aliment / FCR) + biomasse de debut - biomasse de fin - poissons morts
        b0, b1 = n.get(f'{y - 1}12', [0])[0], n.get(f'{y}12', [0])[0]
        return (get(y, 2) / FCRB + b0 - b1 - get(y, 1)) * GUT
    v25 = harvest(ly)
    m, lx = exports_wfe('GB'); Y, M = divmod(lx, 100)
    ytd, ytd_ly = sum(m.get(Y * 100 + i, 0) for i in range(1, M + 1)), sum(m.get((Y - 1) * 100 + i, 0) for i in range(1, M + 1))
    e26 = v25 * (ytd / ytd_ly) if ytd_ly else v25
    b, b_ly = n[last][0], n[str(int(last) - 100)][0]
    return {'v2025': kt(v25), 'ytd': {'to': f'{MON[M - 1]} {Y} (UK exports)', 'kt': kt(ytd), 'chg': pc(ytd, ytd_ly)}, 'e2026': kt(e26), 'chg2026': pc(e26, v25),
            'c2027': kt(e26 * 1.08), 'chg2027': 8, 'lo': -5, 'hi': 15, 'sepa_last': last, 'sepa_biomass_chg': pc(b, b_ly), 'confidence': 'low',
            'source': 'SEPA monthly biomass, feed and mortality reports (mass balance) and UK salmon exports (HMRC)',
            'method': f'{ly} harvest rebuilt from SEPA farm reports: growth (feed ÷ {FCRB}) + biomass at the start − biomass at the end − dead fish = {v25 / 1000:,.0f} kt gutted. SEPA publishes with a long delay (last month {MON[int(last[4:]) - 1]} {last[:4]}), so 2026 follows UK exports to date ({pc(ytd, ytd_ly):+.0f} %) — a rough guide, since UK exports also move with the home market. '
                      '2027: the companies have more fish to harvest after two poor years (Bakkafrost Scotland plans 28,000 t against 20,000 t, Mowi Scotland 76,000 t against 74,000 t); we read +8 % (−5 to +15 %) as Scottish biology has disappointed several years in a row.',
            'tab': 'scotland'}


def iceland():
    I = D('iceland_outlook.json')['year']; A = I['actual_quarters']; S = I['scenarios']
    yr = lambda y: sum(v for k, v in A.items() if k.startswith(str(y)))
    v25 = yr(2025)
    ytd_q = [k for k in A if k.startswith('2026')]
    ytd = sum(A[k] for k in ytd_q); ytd_ly = sum(A['2025' + k[4:]] for k in ytd_q)
    e26 = ytd + S['central'].get('2026-Q4', 0)
    t27 = {sc: sum(v for k, v in q.items() if k.startswith('2027')) for sc, q in S.items()}
    c = t27['central']
    return {'v2025': kt(v25), 'ytd': {'to': f'Q{len(ytd_q)} 2026', 'kt': kt(ytd), 'chg': pc(ytd, ytd_ly)}, 'e2026': kt(e26), 'chg2026': pc(e26, v25),
            'c2027': kt(c), 'chg2027': pc(c, e26), 'lo': min(pc(v, e26) for v in t27.values()), 'hi': max(max(pc(v, e26) for v in t27.values()), pc(c, e26) + 5),
            'source': 'MAST monthly farm reports (fish, weights, harvest by site)',
            'method': 'Harvest to date from MAST; Q4 2026 and 2027 from our farm-by-farm simulation (growth, harvest weights, mortality) in three scenarios. The simulation has run high in past tests, so read the direction (down after a record 2026, with 30 % fewer fish over 4 kg at sea) more than the level.',
            'tab': 'iceland'}


def canada():
    T = D('canada_trade.json'); A = ['NB', 'NS', 'NL', 'PE']
    m = collections.defaultdict(float)
    for r in T['rows']:
        if r[1] == 'BC' or r[1] in A:
            m[r[0]] += r[5] * FAC_CT[r[2]]
    last = max(m); Y, M = divmod(last, 100)
    y = lambda yy, ms: sum(m.get(yy * 100 + mm, 0) for mm in ms)
    x25, ytd, ytd_ly = y(Y - 1, range(1, 13)), y(Y, range(1, M + 1)), y(Y - 1, range(1, M + 1))
    x26 = ytd + y(Y - 1, range(M + 1, 13))          # reste de l'annee = meme mois un an plus tot (methode la mieux testee)
    # niveau : production de Statistique Canada (Terre-Neuve absente depuis 2004 : rapport provincial), en poids vif, portee en 2025 par les exportations
    CA = D('canada_atl.json'); P = CA['production']; ys = sorted(P['Canada']['Salmon']); yb = ys[-1]
    prod = P['Canada']['Salmon'][yb][0] + ((CA.get('nl_facts') or {}).get('production') or {}).get(yb, 0)
    xb = y(int(yb), range(1, 13))
    v25 = prod * GUT * (x25 / xb) if xb else x25
    e26 = v25 * x26 / x25
    O = D('canada_extra.json').get('outlook') or {}
    obs = O.get('observed') or {}; Q = {q['q']: q['t'] for q in (O.get('current') or {}).get('quarters', [])}
    val = lambda q: obs.get(q, Q.get(q))
    tot = lambda yy: sum(val(f'{yy}Q{i}') or 0 for i in range(1, 5))
    bc = pc(tot(Y + 1), tot(Y)) if tot(Y) else None
    bc_share = sum(r[5] * FAC_CT[r[2]] for r in T['rows'] if r[1] == 'BC' and r[0] // 100 == Y - 1) / x25
    c27 = round((bc or 0) * bc_share, 1)
    return {'v2025': kt(v25), 'ytd': {'to': f'{MON[M - 1]} {Y} (exports)', 'kt': kt(ytd), 'chg': pc(ytd, ytd_ly)}, 'e2026': kt(e26), 'chg2026': pc(e26, v25),
            'c2027': kt(e26 * (1 + c27 / 100)), 'chg2027': c27, 'lo': round(c27 - 7, 1), 'hi': round(c27 + 5, 1), 'bc_2027': bc, 'level_note': f'production {yb} (Statistics Canada + Newfoundland report) carried to 2025 by exports',
            'source': 'Statistics Canada (CIMT): domestic exports by province of origin, whole-fish equivalent',
            'method': f'Level: Canadian salmon production of {yb} (Statistics Canada, plus Newfoundland\'s own report as Statistics Canada suppresses it), carried to 2025 by exports. Exports by province measure the change month by month. 2026 = exports to date + the rest of the year as a year earlier (the rule that tested best). 2027: British Columbia ({100 * bc_share:.0f} % of the volume) from the cycle of every farm (DFO): {bc:+.0f} %; the Atlantic provinces held flat, with downside from ISA in New Brunswick.',
            'tab': 'canada'}


def australia():
    A = D('australia.json')
    fy = collections.defaultdict(float)
    for p in A['production']:
        fy[p['fy_end']] += p['t']
    yrs = sorted(fy); l, p = yrs[-1], yrs[-2]
    mo = {x['m']: x['total'] for x in A['mortality'] if x.get('total') is not None}
    lm = max(mo); Y, M = divmod(lm, 100)
    d26 = sum(v for k, v in mo.items() if k // 100 == Y); d25 = sum(v for k, v in mo.items() if k // 100 == Y - 1 and k % 100 <= M)
    return {'v2025': kt(fy[p]), 'ytd': {'to': f'FY {l - 1}/{str(l)[2:]}', 'kt': kt(fy[l]), 'chg': pc(fy[l], fy[p])}, 'e2026': kt(fy[l]), 'chg2026': pc(fy[l], fy[p]),
            'c2027': kt(fy[l] * 1.05), 'chg2027': 5, 'lo': 0, 'hi': 10, 'deaths_ytd': round(d26), 'deaths_ly': round(d25), 'deaths_chg': pc(d26, d25),
            'source': 'Tasmanian production by company (financial years July–June) and EPA Tasmania monthly mortality disposal',
            'method': f'Volumes are Tasmanian financial years (FY {p - 1}/{str(p)[2:]} shown as "2025", FY {l - 1}/{str(l)[2:]} as "2026"). Dead fish disposed of Jan–{MON[M - 1]} {Y}: {d26:,.0f} t, {pc(d26, d25):+.0f} % on a year earlier. If mortality keeps falling, more fish reach harvest: +5 % (0 to +10 %); the summer of 2027 (January–March) is the test.',
            'tab': 'australia'}


def main():
    out = {'meta': {'built': time.strftime('%Y-%m-%d'), 'unit': 'thousand tonnes gutted weight (GWT) or whole-fish equivalent',
                    'note': 'Built only from primary data (official registers, monthly harvest, exports, our own models). Analysts (Kontali, banks) appear only as a comparison.'},
           'basins': {}}
    for k, f in [('NO', norway), ('CL', chile), ('GB', scotland), ('FO', faroe), ('IS', iceland), ('CA', canada), ('AU', australia)]:
        try:
            out['basins'][k] = f(); print(k, {x: out['basins'][k][x] for x in ('v2025', 'e2026', 'chg2026', 'c2027', 'chg2027', 'lo', 'hi')})
        except Exception as e:  # noqa: BLE001
            print(k, 'ERREUR', repr(e))
    B = [v for v in out['basins'].values() if v.get('e2026') and v.get('c2027')]
    t25, t26, t27 = sum(v['v2025'] or 0 for v in B), sum(v['e2026'] for v in B), sum(v['c2027'] for v in B)
    lo = sum(v['e2026'] * (1 + v['lo'] / 100) for v in B); hi = sum(v['e2026'] * (1 + v['hi'] / 100) for v in B)
    out['tracked'] = {'v2025': round(t25, 1), 'e2026': round(t26, 1), 'chg2026': pc(t26, t25), 'c2027': round(t27, 1), 'chg2027': pc(t27, t26), 'lo': pc(lo, t26), 'hi': pc(hi, t26),
                      'note': 'Sum of the seven basins we follow (about 95 % of farmed Atlantic salmon). Ireland, the United States, Russia, New Zealand and other small producers are not tracked.'}
    print('total', out['tracked'])
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # la synthese redigee (global_supply.json) prend nos chiffres ; les analystes y restent en comparaison
    gp = os.path.join(ROOT, 'data', 'global_supply.json'); G = json.load(open(gp, encoding='utf-8'))
    sg = lambda v: f'{v:+.0f}'.replace('+0', '0').replace('-', '−')
    for b in G.get('basins', []):
        o = out['basins'].get(b['id'])
        if not o or o.get('chg2027') is None:
            continue
        b.setdefault('analysts_2027', b.get('y2027'))
        b['y2027'] = f"{sg(o['chg2027'])} % ({sg(o['lo'])} to {sg(o['hi'])} %), our projection"
        b['dir'] = 'up' if o['chg2027'] >= 2 else 'down' if o['chg2027'] <= -2 else 'flat'
        b['r2027'] = [round(o['lo']), round(o['hi'])]; b['c2027'] = o['chg2027']
    W, T = G['world'], out['tracked']
    W.setdefault('analysts_2027', f"{W.get('y2027')} — {W.get('y2027_note', '')}"); W.setdefault('analysts_2026', f"{W.get('y2026')} — {W.get('y2026_note', '')}")
    W['y2027'] = f"{sg(T['chg2027'])} %"; W['y2027_note'] = f"Our projection for the seven basins: {T['c2027'] / 1000:.2f} Mt, range {sg(T['lo'])} to {sg(T['hi'])} %."
    W['y2026'] = f"{sg(T['chg2026'])} %"; W['y2026_note'] = f"Our estimate: {T['e2026'] / 1000:.2f} Mt — actual harvest or exports to date, the rest of the year projected."
    W['v2025_own'] = T['v2025']; W['r2027'] = [round(T['lo']), round(T['hi'])]; W['c2027'] = T['chg2027']
    json.dump(G, open(gp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
