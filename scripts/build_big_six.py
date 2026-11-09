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
    s25, s26 = (S.mean(sh[y]) if sh.get(y) else None for y in (2025, 2026))
    g = lire('gen_outlook.json'); sc = g.get('scenarios') or {}; st = g.get('state') or {}
    def ratio(k):
        m = [x for x in (sc.get(k) or {}).get('months', []) if 202701 <= x['k'] <= 202709]
        a, b = sum(x['kt6'] for x in m), sum(x['ly6'] for x in m)
        return a / b if b else None
    if no and s25 and s26:
        v25, v26 = no['v2025'] * s25 / 100, no['e2026'] * s26 / 100
        rc, rl, rh = ratio('central'), ratio('fade'), ratio('fast')
        out['basins'].append({'id': 'NO', 'name': 'Norway', 'v2025': round(v25, 1), 'v2026': round(v26, 1), 'v2027': round(v26 * rc, 1) if rc else None,
            'lo': round(v26 * rl, 1) if rl else None, 'hi': round(v26 * rh, 1) if rh else None, 'share': [round(s25, 1), round(s26, 1)],
            'how': f'Harvest ({no["v2025"]:,.0f} kt in 2025, {no["e2026"]:,.0f} kt in 2026) × share of 6 kg+ in the harvest from Sjømat Norge\'s weekly size report ({s25:.1f} % in 2025, {s26:.1f} % so far in 2026). '
                   f'2027: our generations model, 6 kg+ harvested January–September 2027 against the same months of 2026: {100 * (rc - 1):+.0f} % central ({100 * (rl - 1):+.0f} % if the new generation loses its growth advance, {100 * (rh - 1):+.0f} % if it keeps all of it).',
            'known': [f'Fish over 5 kg at sea at the end of September: {st.get("old_b5", 0):.0f} kt gutted against {st.get("old_b5_ly", 0):.0f} kt a year earlier ({100 * (st["old_b5"] / st["old_b5_ly"] - 1):+.0f} %).' if st.get('old_b5_ly') else '',
                      f'The generation being harvested grows {abs(100 * (st["old_gr"] / st["old_gr_ly"] - 1)):.0f} % {"faster" if st["old_gr"] >= st["old_gr_ly"] else "slower"} per fish and loses {st["old_mort"]:.2f} % of its fish a month ({st["old_mort_ly"]:.2f} % a year earlier).' if st.get('old_gr_ly') else '',
                      f'Next generation: {st.get("new_fish", 0):.0f} M fish at {st.get("new_w", 0):.2f} kg ({st.get("new_fish_ly", 0):.0f} M at {st.get("new_w_ly", 0):.2f} kg a year earlier).' if st.get('new_fish_ly') else '',
                      'October 2026: 14.5 % of the harvest in 6 kg+ (13.1 % a year earlier), from harvest-boat visits.'],
            'up': ['The new generation keeps its growth advance: a wave of 6 kg+ in spring–summer 2027 (+30 % case).', 'Low mortality and fewer lice treatments let farmers keep fish longer.'],
            'down': ['Algae (spring 2026 in the south, 2025 in the north), ISA or a jellyfish year force early harvests of smaller fish.', 'Weak premium for big sizes pushes farmers to harvest earlier.', 'Norway is at its legal biomass limit: more 6 kg+ means fewer small fish, not more salmon.'],
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
            'tab': 'chile'})
    # ---------------- Feroe ----------------
    fo = own.get('FO') or {}; MAN = lire('big_six_manual.json'); FB = (MAN.get('faroe_bakkafrost') or {}).get('rows') or []
    def wavg(pref, months=None):
        R = [r for r in FB if r[0].startswith(pref) and (months is None or r[0][5:] in months)]
        t = sum(r[1] for r in R); return (sum(r[1] * r[2] for r in R) / t if t else None), t
    if fo and FB:
        w25, _ = wavg('2025'); w26, _ = wavg('2026'); wh1_25, _ = wavg('2025', ['01', '02', '03', 'Q2']); wh1_26, _ = wavg('2026', ['01', '02', '03', '04', '05', '06']); wq3, _ = wavg('2026', ['07', '08', '09'])
        p25, p26 = part6(w25), part6(w26)
        out['basins'].append({'id': 'FO', 'name': 'Faroe Islands', 'v2025': round(fo['v2025'] * p25 / 100, 1), 'v2026': round(fo['e2026'] * p26 / 100, 1),
            'v2027': round(fo['c2027'] * part6(w25) / 100, 1), 'lo': round(fo['c2027'] * (1 + fo['lo'] / 100) * part6(4.9) / 100, 1), 'hi': round(fo['c2027'] * (1 + fo['hi'] / 100) * part6(5.6) / 100, 1),
            'share': [round(p25, 1), round(p26, 1)], 'estimated': True, 'weights': {'h1_2025': round(wh1_25, 2), 'h1_2026': round(wh1_26, 2), 'q3_2026': round(wq3, 2), 'y2025': round(w25, 2)},
            'how': f'Harvest ({fo["v2025"]:.0f} kt in 2025, {fo["e2026"]:.0f} kt in 2026) × share of 6 kg+ estimated from Bakkafrost\'s average harvest weight (gutted): {wh1_26:.1f} kg in H1 2026 against {wh1_25:.1f} kg in H1 2025, back to {wq3:.1f} kg in Q3 2026 '
                   f'(estimated share {p25:.0f} % in 2025, {p26:.0f} % in 2026, assuming the usual spread of weights). 2027: flat harvest (Bakkafrost plans as much as in 2026) at the 2025 weight; low case 4.9 kg, high case 5.6 kg.',
            'known': [f'H1 2026 was a big-fish half-year: {wh1_26:.1f} kg on average against {wh1_25:.1f} kg a year earlier; Q3 2026 back to {wq3:.1f} kg.', MAN['faroe_bakkafrost'].get('guidance', ''), MAN['faroe_bakkafrost'].get('premium_note', '')],
            'up': ['Larger smolts (527 g in Q1 2026) and good biology let fish reach 6 kg+ again in 2027.'], 'down': ['The H1 2026 bulge came from one strong generation; the fish harvested since July are lighter.', 'Bakkafrost may harvest earlier if the premium for big fish stays small.'],
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


if __name__ == '__main__':
    main()
