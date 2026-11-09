#!/usr/bin/env python3
"""
Gros poissons (6 kg+) : offre 2025, estimation 2026 et projection 2027 par bassin, avec ce qu'on sait aujourd'hui et ce qui
pourrait changer la projection. Offre seulement (pas de demande pour l'instant).

    python3 scripts/build_big_six.py      -> data/big_six.json   (onglet « Big fish 6+ outlook » et encart du Summary)

Sources, toutes deja collectees par le site (aucun appel exterieur) :
  - Norvege : recolte (own_supply.json), part des 6 kg+ dans la recolte (rapport hebdomadaire de Sjomat Norge, data.json
    weekly sh_6plus), modele des generations (gen_outlook.json : 6 kg+ mois par mois jusqu'a septembre 2027, trois
    scenarios), stock de poissons de plus de 5 kg en mer ;
  - Chili : recolte (own_supply.json) x part des 6 kg+ estimee depuis le poids moyen de recolte de Camanchaca et Multi X
    (chile_harvest_weights.json) ; les douanes (part des 6 kg+ dans le poisson entier exporte) donnent le sens de l'evolution ;
  - Feroe : recolte (own_supply.json) x part des 6 kg+ estimee depuis le poids moyen de recolte de Bakkafrost (big_six_manual.json),
    en supposant la meme dispersion des poids qu'ailleurs sur le site (coefficient de variation 0,27) ;
  - Islande : poissons de plus de 5 kg en mer (iceland_outlook.json, MAST) ; Ecosse : texte (pas de statistique de taille).
Tonnes : equivalent poisson vide (gutted), comme l'onglet Global supply.
"""
import datetime as dt
import io
import json
import math
import os
import statistics as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda n: os.path.join(ROOT, 'data', n)
CV = 0.27


def lire(n):
    try:
        return json.load(io.open(D(n), encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def part6(w):
    """part des poissons de 6 kg+ (en poids) pour un poids moyen w, loi normale de coefficient de variation CV (approximation)."""
    if not w: return None
    s = CV * w
    # part en poids : E[X ; X>6] / E[X]
    z = (6 - w) / s
    pdf = math.exp(-z * z / 2) / math.sqrt(2 * math.pi); sf = 0.5 * math.erfc(z / math.sqrt(2))
    return 100 * (w * sf + s * pdf) / w


def main():
    own = (lire('own_supply.json').get('basins') or {})
    out = {'meta': {'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'), 'unit': 'thousand tonnes gutted (6 kg+ fish)',
                    'note': 'Supply only. 2026 = harvest to date plus the rest of the year at the same pace; 2027 = our harvest projection times the 6 kg+ share expected, low and high cases in brackets.'},
           'basins': []}
    # ---------------- Norvege ----------------
    no = own.get('NO') or {}
    W = lire('data.json').get('weekly') or []
    sh = {}
    for r in W:
        if r.get('sh_6plus') is not None: sh.setdefault(r['report_year'], []).append(r['sh_6plus'])
    s25i, s26i = (S.mean(sh[y]) if sh.get(y) else None for y in (2025, 2026))
    g = lire('gen_outlook.json'); sc = g.get('scenarios') or {}; st = g.get('state') or {}
    # 6 kg+ recoltes mois par mois (tonnes videes), d'apres le registre de la biomasse (modele des generations) :
    # realise = valeurs « un an plus tot » des previsions archivees et du modele ; projection = trois scenarios
    act = {}
    for v in (lire('big_fish_archive.json') or {}).values():
        for r in v.get('norway', []):
            if r.get('ly_t6') is not None: act.setdefault(r['month'] - 100, (r['ly_t6'] / 1000, r['ly_harvest_t'] / 1000))
    for x in (sc.get('central') or {}).get('months', []): act[x['k'] - 100] = (x['ly6'], x['ly_tot'])
    def proj(k):
        M = {x['k']: x for x in (sc.get(k) or {}).get('months', [])}
        y26 = sum(act[m][0] for m in act if 202601 <= m <= 202612 and m not in M) + sum(M[m]['kt6'] for m in M if 202601 <= m <= 202612)
        j27 = [M[m] for m in M if 202701 <= m <= 202709]; r = sum(x['kt6'] for x in j27) / sum(x['ly6'] for x in j27)
        q4 = sum(M[m]['kt6'] for m in M if 202610 <= m <= 202612)
        return y26, sum(x['kt6'] for x in j27) + q4 * r, r
    y25 = sum(act[m][0] for m in act if 202501 <= m <= 202512) if all(m in act for m in range(202501, 202513)) else None
    h25 = sum(act[m][1] for m in act if 202501 <= m <= 202512) if y25 else None
    if no and y25 and sc.get('central'):
        y26, c27, rc = proj('central'); _, l27, rl = proj('fade'); _, h27, rh = proj('fast')
        h26 = sum(act[m][1] for m in act if 202601 <= m <= 202609); j26 = sum(act[m][0] for m in act if 202601 <= m <= 202609)
        h1_25 = sum(act[m][0] for m in range(202501, 202507)); h1_26 = sum(act[m][0] for m in range(202601, 202607))
        out['basins'].append({'id': 'NO', 'name': 'Norway', 'v2025': round(y25, 1), 'v2026': round(y26, 1), 'v2027': round(c27, 1), 'lo': round(l27, 1), 'hi': round(h27, 1),
            'share': [round(100 * y25 / h25, 1), round(100 * j26 / h26, 1)],
            'h1': [round(h1_25, 1), round(h1_26, 1)],
            'how': f'6 kg+ harvested month by month from the biomass register (every farm, gutted weight, our size model): {y25:.0f} kt in 2025, {j26:.0f} kt from January to September 2026, '
                   f'plus October–December from the generations model. 2027: the model gives January–September 2027 against the same months of 2026: {100 * (rc - 1):+.0f} % central, '
                   f'{100 * (rl - 1):+.0f} % if the new generation loses its growth advance, {100 * (rh - 1):+.0f} % if it keeps all of it; October–December 2027 carried at the same rate. '
                   f'Cross-check: the size split of the Sitagri price index (fresh whole salmon traded on the spot market by the exporters that report to the index, not the whole harvest) shows 6 kg+ at {s25i:.1f} % of the volume in 2025 and {s26i:.1f} % so far in 2026, the same direction.',
            'known': [f'H1 2026: {h1_26:.0f} kt of 6 kg+ against {h1_25:.0f} kt in H1 2025 ({100 * (h1_26 / h1_25 - 1):+.0f} %).',
                      f'Fish over 5 kg at sea at the end of September: {st.get("old_b5", 0):.0f} kt gutted against {st.get("old_b5_ly", 0):.0f} kt a year earlier ({100 * (st["old_b5"] / st["old_b5_ly"] - 1):+.0f} %).' if st.get('old_b5_ly') else '',
                      f'The generation being harvested grows {abs(100 * (st["old_gr"] / st["old_gr_ly"] - 1)):.0f} % {"faster" if st["old_gr"] >= st["old_gr_ly"] else "slower"} per fish and loses {st["old_mort"]:.2f} % of its fish a month ({st["old_mort_ly"]:.2f} % a year earlier).' if st.get('old_gr_ly') else '',
                      f'Next generation: {st.get("new_fish", 0):.0f} M fish at {st.get("new_w", 0):.2f} kg ({st.get("new_fish_ly", 0):.0f} M at {st.get("new_w_ly", 0):.2f} kg a year earlier).' if st.get('new_fish_ly') else '',
                      'October 2026: 14.5 % of the harvest in 6 kg+ (13.1 % a year earlier), from harvest-boat visits.'],
            'up': [f'Stock already in the water: {st.get("old_b5", 0):.0f} kt of fish over 5 kg at the end of September ({100 * (st["old_b5"] / st["old_b5_ly"] - 1):+.0f} %), and they keep growing through the winter: most of the 6 kg+ of H1 2027 are these fish.' if st.get('old_b5_ly') else '',
                   f'The next generation is ahead: {st.get("new_w", 0):.2f} kg per fish against {st.get("new_w_ly", 0):.2f} kg a year earlier, growing faster. If it keeps the advance, it reaches 6 kg in spring–summer 2027 and the usual April–July gap in big fish disappears ({100 * (rh - 1):+.0f} % case).' if st.get('new_w_ly') else '',
                   'Fewer losses: the generation being harvested loses 0.85 % of its fish a month against 1.43 % a year earlier, so more fish reach large sizes.',
                   'Farmers can keep fish longer when lice and disease leave them alone: fewer forced harvests of small fish.'],
            'down': [f'The growth advance fades: if the new generation grows like an average one, 6 kg+ are only {100 * (rl - 1):+.0f} % in January–September 2027.',
                     'Biology goes back to normal (see the box): more lice, more delousing, more handling deaths, more early harvests.',
                     'Algae (spring 2026 in the south, 2025 in the north), ISA, pasteurellosis or a jellyfish year force early harvests of smaller fish.',
                     'Weak premium for big sizes: farmers may prefer to harvest earlier and free biomass for the next generation.',
                     'Norway is at its legal biomass limit (MTB): more 6 kg+ means fewer small fish, not more salmon; if farmers near their limit, they harvest earlier.'],
            'biology': norway_biology(),
            'tab': 'generations'})
    # ---------------- Chili ----------------
    cl = own.get('CL') or {}; CM = lire('chile_customs.json').get('months') or {}
    def g6(keys):
        t = h = 0
        for k in keys:
            for f in ('atlantic|fresh whole', 'atlantic|frozen whole'):
                z = ((CM.get(k) or {}).get('sizes') or {}).get(f)
                if z and z.get('hist_t'): t += sum(z['hist_t']); h += sum(z['hist_t'][5:])
        return 100 * h / t if t else None
    mk = sorted(CM)
    HW = (lire('chile_harvest_weights.json').get('companies') or {})
    def wy(y):
        R = [x for L in HW.values() for x in L if isinstance(x, dict) and str(x.get('q', '')).startswith(y) and x.get('kg') and x.get('harvest_t')]
        t = sum(x['harvest_t'] for x in R); return (sum(x['kg'] * x['harvest_t'] for x in R) / t if t else None), sorted({x['q'] for x in R})
    if cl and mk:
        s6 = g6(mk[-6:]); s6ly = g6([str(int(k) - 100) for k in mk[-6:]]); e25 = g6([k for k in mk if k.startswith('2025')])
        (w25, q25), (w26, q26) = wy('2025'), wy('2026')
        G = 0.9      # poids vif (WFE) -> vide
        p25, p26 = part6(w25 * G), part6(w26 * G)
        lo27 = cl['e2026'] * (1 + cl['lo'] / 100); hi27 = cl['e2026'] * (1 + cl['hi'] / 100)
        out['basins'].append({'id': 'CL', 'name': 'Chile', 'v2025': round(cl['v2025'] * p25 / 100, 1), 'v2026': round(cl['e2026'] * p26 / 100, 1), 'v2027': round(cl['c2027'] * p26 / 100, 1),
            'lo': round(lo27 * part6((w26 - 0.3) * G) / 100, 1), 'hi': round(hi27 * p25 / 100, 1), 'share': [round(p25, 1), round(p26, 1)], 'estimated': True,
            'how': f'Atlantic harvest ({cl["v2025"]:,.0f} kt in 2025, {cl["e2026"]:,.0f} kt in 2026) × share of 6 kg+ estimated from the average harvest weight reported by Camanchaca and Multi X '
                   f'({w25:.2f} kg live in 2025, {w26:.2f} kg in {", ".join(q26)}; estimated share {p25:.0f} % and {p26:.0f} %, assuming the usual spread of weights). '
                   f'Customs confirm the direction: 6 kg+ were {s6:.0f} % of the whole Atlantic salmon exported over the last six months against {s6ly:.0f} % a year earlier. '
                   f'2027: harvest {cl["chg2027"]:+.1f} % at the 2026 weight; low case: harvest {cl["lo"]:+.0f} % and 0.3 kg lighter fish; high case: harvest {cl["hi"]:+.0f} % and back to 2025 weights.',
            'known': ['Standing biomass about 7 % below a year earlier; harvest slowing since August.', 'Record El Niño: Chilean sea 1–3 °C above normal; preventive algae emergency from 1 Nov 2026 to 30 Jun 2027.',
                      'Sea lice at a high (65 farms above the threshold in Q3 2026); SRS causes 53 % of infectious mortality (2025) and forced early harvests at Camanchaca in Q1 2026.', 'FOB price of 6 kg+ up 16 % in Q3 2026 as volumes fell.'],
            'up': ['A mild algae season and calmer El Niño let farmers grow fish to full size.', 'Fewer early harvests for lice and SRS.'],
            'down': ['A bloom like 2016 or 2021 in the inner seas (Los Lagos, Aysén) or new losses in Magallanes.', 'Warm water speeds growth but pushes farmers to harvest early, at smaller sizes, to limit risk.', 'Companies changing hands (Blumar sold to Agrosuper) may change harvest plans.'],
            'tab': 'chile', 'question': chile_h1(g6)})
    # ---------------- Feroe ----------------
    fo = own.get('FO') or {}; MAN = lire('big_six_manual.json'); FB = (MAN.get('faroe_bakkafrost') or {}).get('rows') or []
    def wavg(pref, months=None):
        R = [r for r in FB if r[0].startswith(pref) and (months is None or r[0][5:] in months)]
        t = sum(r[1] for r in R); return (sum(r[1] * r[2] for r in R) / t if t else None), t
    nt = lire('national_trade.json').get('rows') or []; tt = sum(r[4] for r in nt if r[1] == 'FO' and r[0] >= 202601 and r[3] in (0, 1)) or 1
    US_FO = 100 * sum(r[4] for r in nt if r[1] == 'FO' and r[0] >= 202601 and r[3] in (0, 1) and r[2] == 'US') / tt
    CN_FO = 100 * sum(r[4] for r in nt if r[1] == 'FO' and r[0] >= 202601 and r[3] in (0, 1) and r[2] in ('CN', 'HK')) / tt
    if fo and FB:
        w25, _ = wavg('2025'); w26, _ = wavg('2026'); wh1_25, _ = wavg('2025', ['01', '02', '03', 'Q2']); wh1_26, _ = wavg('2026', ['01', '02', '03', '04', '05', '06']); wq3, _ = wavg('2026', ['07', '08', '09'])
        p25, p26 = part6(w25), part6(w26)
        W27 = 5.4      # recoltes plus regulieres en 2027 : moins lourd qu'au S1 2026 (5,7 kg), plus lourd qu'au T3 2026 (5,0 kg)
        h1_25 = sum(r[1] * part6(r[2]) / 100 for r in FB if r[0] < '2025-07' or r[0] == '2025-Q2'); h1_26 = sum(r[1] * part6(r[2]) / 100 for r in FB if '2026' <= r[0] < '2026-07')
        out['basins'].append({'id': 'FO', 'name': 'Faroe Islands', 'v2025': round(fo['v2025'] * p25 / 100, 1), 'v2026': round(fo['e2026'] * p26 / 100, 1),
            'v2027': round(fo['c2027'] * part6(W27) / 100, 1), 'lo': round(fo['c2027'] * (1 + fo['lo'] / 100) * part6(5.1) / 100, 1), 'hi': round(fo['c2027'] * (1 + fo['hi'] / 100) * part6(5.6) / 100, 1),
            'share': [round(p25, 1), round(p26, 1)], 'estimated': True, 'h1_bakkafrost': [round(h1_25, 1), round(h1_26, 1)], 'weights': {'h1_2025': round(wh1_25, 2), 'h1_2026': round(wh1_26, 2), 'q3_2026': round(wq3, 2), 'y2025': round(w25, 2)},
            'how': f'Harvest ({fo["v2025"]:.0f} kt in 2025, {fo["e2026"]:.0f} kt in 2026) × share of 6 kg+ estimated from Bakkafrost\'s average harvest weight (gutted): {wh1_26:.1f} kg in H1 2026 against {wh1_25:.1f} kg in H1 2025, back to {wq3:.1f} kg in Q3 2026 '
                   f'(estimated share {p25:.0f} % in 2025, {p26:.0f} % in 2026, assuming the usual spread of weights). 2027: flat harvest (Bakkafrost plans as much as in 2026) with more even harvests through the year: fewer big fish than in H1 2026 and slightly fewer over the year, '
                   f'but still mostly large fish, aimed at the United States and China; we take {W27} kg on average (low case 5.1 kg, high case 5.6 kg).',
            'known': [f'H1 2026 was a big-fish half-year: {wh1_26:.1f} kg on average against {wh1_25:.1f} kg a year earlier (about {h1_26:.0f} kt of 6 kg+ at Bakkafrost against {h1_25:.0f} kt, estimated); Q3 2026 back to {wq3:.1f} kg.',
                      f'Where Faroese whole salmon goes in 2026: United States {US_FO:.0f} %, China {CN_FO:.0f} % of the tonnes (Faroese export statistics).', MAN['faroe_bakkafrost'].get('guidance', ''), MAN['faroe_bakkafrost'].get('premium_note', '')],
            'up': ['Strategy: keep most of the harvest large for the United States and China (Faroese salmon has entered the US duty-free since August 2026, against about 12 % for Norway and Chile).', 'Larger smolts (527 g in Q1 2026) and good biology.'],
            'down': ['More even harvests through 2027: fewer 6 kg+ in the first half than in H1 2026.', 'The fish harvested since July 2026 are lighter (5.0 kg); a weak premium for big sizes makes earlier harvests tempting.'],
            'tab': 'faroe', 'sources': sorted({r[3] for r in FB if r[3].startswith('http')})})
    # ---------------- Islande, Ecosse (sans chiffre de 6 kg+) ----------------
    io_ = lire('iceland_outlook.json').get('structure') or {}
    if io_.get('now'):
        a, b = io_['now'].get('5 kg+', {}), io_['year_before'].get('5 kg+', {}); c, d = io_['now'].get('4–5 kg', {}), io_['year_before'].get('4–5 kg', {})
        out['basins'].append({'id': 'IS', 'name': 'Iceland', 'qualitative': True,
            'known': [f'Fish over 5 kg at sea in {io_.get("k")}: {a.get("t", 0) / 1000:.1f} kt against {b.get("t", 0) / 1000:.1f} kt a year earlier ({100 * (a["t"] / b["t"] - 1):+.0f} %); 4–5 kg: {c.get("t", 0) / 1000:.1f} kt against {d.get("t", 0) / 1000:.1f} kt (MAST).',
                      f'Iceland harvest 2027: {own.get("IS", {}).get("chg2027", 0):+.1f} % (our projection).'], 'direction': 'down', 'tab': 'iceland'})
    sc_ = MAN.get('scotland') or {}
    if sc_:
        out['basins'].append({'id': 'GB', 'name': 'Scotland', 'qualitative': True, 'known': [sc_['text']], 'url': sc_.get('url'), 'direction': 'down', 'tab': 'scotland'})
    # rappel : offre totale (toutes tailles) par bassin, comme l'onglet Global supply
    NM = {'NO': 'Norway', 'CL': 'Chile', 'GB': 'Scotland', 'FO': 'Faroe Islands', 'IS': 'Iceland', 'CA': 'Canada', 'AU': 'Tasmania'}
    six = {b['id']: b for b in out['basins'] if not b.get('qualitative')}
    out['supply'] = [{'id': k, 'name': NM.get(k, k), 'v2025': round(v['v2025'], 1), 'v2026': round(v['e2026'], 1), 'v2027': round(v['c2027'], 1), 'chg2026': v.get('chg2026'), 'chg2027': v.get('chg2027'),
                      'lo': v.get('lo'), 'hi': v.get('hi'), 'six2027': six[k]['v2027'] if k in six else None}
                     for k, v in sorted(own.items(), key=lambda kv: -kv[1]['e2026']) if v.get('e2026')]
    Q = [b for b in out['basins'] if not b.get('qualitative')]
    tot = lambda k: round(sum(b[k] for b in Q if b.get(k) is not None), 1)
    out['total'] = {'basins': [b['name'] for b in Q], 'v2025': tot('v2025'), 'v2026': tot('v2026'), 'v2027': tot('v2027'), 'lo': tot('lo'), 'hi': tot('hi')}
    T = out['total']
    ch = {b['name']: 100 * (b['v2027'] / b['v2026'] - 1) for b in Q if b.get('v2026')}
    upn = [n for n, v in ch.items() if v >= 3]; dn = [n for n, v in ch.items() if v <= -3] + [b['name'] for b in out['basins'] if b.get('qualitative') and b.get('direction') == 'down']
    drv = max(Q, key=lambda b: abs(b['v2027'] - b['v2026']))['name'] if Q else ''
    out['lead'] = (f'6 kg+ salmon from Norway, Chile and the Faroes: about {T["v2026"]:.0f} kt in 2026 ({100 * (T["v2026"] / T["v2025"] - 1):+.0f} % on 2025) and {T["v2027"]:.0f} kt in 2027 '
                   f'({100 * (T["v2027"] / T["v2026"] - 1):+.0f} %, range {T["lo"]:.0f}–{T["hi"]:.0f} kt). {drv} drives the change'
                   + (f'; more big fish in {", ".join(upn)}' if upn else '') + (f'; fewer in {", ".join(dn)}' if dn else '') + '.')
    io.open(D('big_six.json'), 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, indent=1))
    print(out['lead'])
    for b in Q: print(f'  {b["id"]} {b["v2025"]} {b["v2026"]} {b["v2027"]} ({b["lo"]}–{b["hi"]}) part {b["share"]}')


def norway_biology():
    """La biologie de 2026 en Norvege contre les annees precedentes (memes semaines / memes mois), et pourquoi elle peut ne pas durer."""
    d = lire('data.json'); R = d.get('records') or []; B = (d.get('bw_weekly') or {}).get('rows') or []
    if not R or not B: return None
    c = {}
    for r in R:
        if 0 <= (r.get('po') if r.get('po') is not None else -1) <= 13 and r.get('behfisk_stk'):
            q = c.setdefault((r['year'], r['month']), [0, 0]); q[0] += r.get('dodfisk_stk') or 0; q[1] += r['behfisk_stk']
    Y, M = max(k for k in c)
    def mort(y):
        s = 1
        for m in range(1, M + 1):
            a, b = c.get((y, m), (0, 0))
            if b: s *= 1 - a / b
        return 100 * (1 - s)
    dead = lambda y: sum(c.get((y, m), (0, 0))[0] for m in range(1, M + 1)) / 1e6
    W = max(r['w'] for r in B if r['y'] == Y)
    agg = {}
    for r in B:
        if r['w'] > W: continue
        q = agg.setdefault(r['y'], [0, 0, 0, 0, 0, 0])
        if r.get('lice') is not None and r.get('nl'): q[0] += r['lice'] * r['nl']; q[1] += r['nl']
        q[2] += (r.get('trt') or {}).get('IKKE_MEDIKAMENTELL', 0); q[3] += r.get('ov', 0)
        if r.get('t') is not None and r.get('nt'): q[4] += r['t'] * r['nt']; q[5] += r['nt']
    yrs = [y for y in range(Y - 7, Y) if y in agg and (y, M) in c]
    li = lambda y: agg[y][0] / agg[y][1]; tm = lambda y: agg[y][4] / agg[y][5]
    MN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    mo = {y: mort(y) for y in yrs + [Y]}
    best = min(mo[y] for y in yrs)
    lines = [f'Mortality at sea, January–{MN[M - 1]}: {mo[Y]:.1f} % of the fish ({dead(Y):.0f} M fish) against {mo[Y - 1]:.1f} % ({dead(Y - 1):.0f} M) in {Y - 1} and {min(mo[y] for y in yrs):.1f}–{max(mo[y] for y in yrs):.1f} % in {yrs[0]}–{Y - 1}: the lowest since at least {yrs[0]}.' if mo[Y] < best else
             f'Mortality at sea, January–{MN[M - 1]}: {mo[Y]:.1f} % against {mo[Y - 1]:.1f} % in {Y - 1}.',
             f'Sea lice, weeks 1–{W}: {li(Y):.3f} adult females per fish on average against {li(Y - 1):.3f} in {Y - 1} ({min(li(y) for y in yrs):.3f}–{max(li(y) for y in yrs):.3f} since {yrs[0]}).',
             f'Farm-weeks above the lice limit: {agg[Y][3]} against {agg[Y - 1][3]} in {Y - 1} ({min(agg[y][3] for y in yrs)}–{max(agg[y][3] for y in yrs)} since {yrs[0]}).',
             f'Non-medicinal delousing (thermal, mechanical, freshwater) reported: {agg[Y][2]:,} against {agg[Y - 1][2]:,} in {Y - 1} ({100 * (agg[Y][2] / agg[Y - 1][2] - 1):+.0f} %): fewer handlings, fewer injuries.',
             f'Sea at the farms {tm(Y):.1f} °C on average against {tm(Y - 1):.1f} °C in {Y - 1}: the cool summer slowed lice; the fish still grew faster than a year earlier.']
    limits = ['A year this good is rarely repeated: low mortality and few treatments in 2026 left more and bigger fish at sea, which is why the 2027 projection is high. If 2027 is an ordinary year, part of that advance is lost.',
              f'Temperature: a warmer 2027 (like {Y - 1}, {tm(Y - 1):.1f} °C) brings lice back, then delousing and handling deaths, and earlier harvests of smaller fish.',
              'After low-lice years, pressure tends to come back: 2023 was as calm as 2026 for lice, and 2024 was one of the worst.',
              'More big fish at sea also means more biomass to manage under the MTB limit: farmers close to their limit harvest earlier, which caps the 6 kg+.',
              'The algae episode of March 2026 in the south (about 1.7 million fish in zone 1) shows the risk is still there, even in a good year.']
    return {'title': f'Biology in {Y}: the best year in a long time — and a limit for {Y + 1}', 'lines': lines, 'limits': limits,
            'source': 'Biomass register (Fiskeridirektoratet), monthly; BarentsWatch weekly lice and treatment reports by farm.'}


def chile_h1(g6):
    """Le premier semestre 2026 (recolte en hausse, beaucoup de gros poissons au T1) peut-il se repeter au S1 2027 ?"""
    bio = (lire('chili.json').get('biologie') or {}); san = bio.get('sanitaire') or {}
    B = san.get('biomasse_mer_t') or {}; FW = san.get('poissons_eau_douce_m') or {}
    R = sorted([r for r in (lire('chile_subpesca.json').get('reports') or []) if r.get('k') and (r.get('species') or {}).get('salar')], key=lambda r: r['k'])
    by = {r['k']: r['species']['salar'] for r in R}
    L = []
    if 202604 in by and 202606 in by:
        L.append(f'H1 2026 was strong: Atlantic harvest {by[202604]["var_pct"]:+.1f} % on a year earlier in January–April and {by[202606]["var_pct"]:+.1f} % in January–June (Subpesca).')
    q1 = [(m, g6([f'2026{m:02d}']), g6([f'2025{m:02d}'])) for m in (1, 2, 3)]
    if all(a and b for _, a, b in q1):
        L.append('Big fish were plentiful early in 2026: 6 kg+ were ' + ', '.join(f'{a:.0f} % of whole exports in {["Jan", "Feb", "Mar"][m - 1]} ({b:.0f} % a year earlier)' for m, a, b in q1) + '.')
    if B.get('2024') and B.get('2025'):
        r = [100 * (a / b - 1) for a, b in zip(B['2025'], B['2024'])]
        L.append(f'That came from a record stock at sea in 2025: biomass {min(r):+.0f} to {max(r):+.0f} % above 2024 month by month (Sernapesca).')
    if FW.get('2024') and FW.get('2025'):
        r = [100 * (a / b - 1) for a, b in zip(FW['2025'][9:], FW['2024'][9:])]
        L.append(f'Most fish harvested in H1 2027 went to sea between mid-2025 and early 2026. The pipeline behind them is not bigger: fish in freshwater farms (all salmonids, future smolts) were {", ".join(sg_(v) for v in r)} in October–December 2025 against a year earlier (Sernapesca).')
    if R:
        mm = [(r['k'], r['species']['salar']['cum_kt']) for r in R]
        d = {k: v for k, v in mm}
        last = [k for k in (202608, 202609) if k in d and k - 1 in d]
        if last: L.append('The harvest has already turned down: ' + ', '.join(f'{["Aug", "Sep"][k % 100 - 8]} {sg_(pct_m(by, k))}' for k in last if pct_m(by, k) is not None) + ' on a year earlier.')
    L.append('Health and climate weigh on H1 2027: preventive algae emergency to June 2027 under a record El Niño, sea lice at a high, SRS behind 53 % of infectious deaths; all push farmers to harvest earlier and smaller.')
    verdict = 'Unlikely: H1 2027 should bring a flat or lower harvest and fewer 6 kg+ than H1 2026. It would take a mild algae season and fewer early harvests to get close.'
    return {'q': 'Could H1 2027 look like H1 2026 in Chile?', 'lines': L, 'verdict': verdict,
            'caveat': 'Chile publishes no current stock at sea: Sernapesca\'s monthly biomass comes once a year (2025 figures published in March 2026). Subpesca\'s stocking resolutions give the number of fish allowed per farm, not the number actually stocked, so they are not used here.'}


def pct_m(by, k):
    """variation d'un mois seul sur un an, a partir de deux cumuls consecutifs (Subpesca donne le cumul et sa variation)."""
    a, b = by.get(k), by.get(k - 1)
    if not a or not b: return None
    m = a['cum_kt'] - b['cum_kt']; ly = a['cum_kt'] / (1 + a['var_pct'] / 100) - b['cum_kt'] / (1 + b['var_pct'] / 100)
    return 100 * (m / ly - 1) if ly else None


def sg_(v):
    return ('+' if v >= 0 else '−') + f'{abs(v):.0f} %'


if __name__ == '__main__':
    main()
