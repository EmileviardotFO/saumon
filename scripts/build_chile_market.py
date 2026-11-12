#!/usr/bin/env python3
"""
Chili : disponibilite du saumon -> data/chile_market.json (bloc « Availability » de l'onglet Chile).

    python3 scripts/build_chile_market.py

Trois lectures, toutes a partir de fichiers deja collectes (aucun acces reseau) :

1. BIOMASSE EN MER ESTIMEE. Le Chili ne publie sa biomasse qu'une fois par an (Sernapesca, rapport sanitaire :
   serie mensuelle, tous salmonides). Entre deux rapports on la reconstitue par bilan :
        biomasse(fin de mois) = biomasse(mois precedent) x (1 + taux de croissance du mois) - recolte du mois
   - recolte : Subpesca, cumul mensuel par espece (les mois isoles = difference de deux cumuls) ;
   - taux de croissance « normal » du mois : celui qu'on retrouve en 2024 et 2025 en inversant le bilan sur la serie
     officielle (croissance nette : poids pris + mises a l'eau - mortalite, rapportee a la biomasse) ;
   - calage : le dernier point publie par un analyste (data/chile_anchors.json, tenu a la main) fixe de combien la
     croissance de l'annee s'ecarte de la normale (facteur s). Sans point de calage, s = 1.
   Le resultat est une estimation, publiee sans engagement et recalee a chaque nouveau point (philosophie du projet).
   Controle : rejouer 2025 avec les taux de 2024 derive de -8 % en aout -> la fourchette « croissance normale » est large.

2. POIDS : poids moyen du saumon atlantique entier frais exporte (douanes, calibre ecrit sur le produit), mois par mois
   contre un an plus tot. Signal independant du point de calage.

3. PRIX ET CONGELE : prix FOB par produit (douanes), contre un an plus tot, et part du congele dans les exports.
   L'ecart congele - frais n'est PAS un indicateur de rarete a lui seul : il s'inverse chaque fois que le frais est abondant.
"""
import datetime as dt
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DD = os.path.join(ROOT, 'data')
OUT = os.path.join(DD, 'chile_market.json')
YIELD = {'fresh whole': 1 / 0.9, 'frozen whole': 1 / 0.9, 'fresh fillets': 1 / 0.58, 'frozen fillets': 1 / 0.58}
FORMS = ['fresh whole', 'frozen whole', 'fresh fillets', 'frozen fillets']


def J(f):
    p = os.path.join(DD, f)
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None


r = lambda v, d=1: None if v is None else round(v, d)
prev = lambda k: k - 1 if k % 100 > 1 else (k // 100 - 1) * 100 + 12


def harvest(S):
    """recolte mensuelle par espece (kt vif) a partir des cumuls Subpesca ; l'annee precedente vient de la variation publiee"""
    cum = {}
    for rep in S.get('reports') or []:
        if not rep.get('k'):
            continue
        for sp, v in (rep.get('species') or {}).items():
            if v.get('cum_kt') is None:
                continue
            cum.setdefault(sp, {})[rep['k']] = v['cum_kt']
            if v.get('var_pct') is not None:
                cum[sp].setdefault(rep['k'] - 100, v['cum_kt'] / (1 + v['var_pct'] / 100))
    H = {}
    for sp, c in cum.items():
        H[sp] = {}
        for y in sorted({k // 100 for k in c}):
            last, pm = 0, 0
            for m in range(1, 13):
                k = y * 100 + m
                if k in c:
                    n = m - pm   # un rapport manquant : la difference est repartie a parts egales sur les mois couverts
                    for j in range(pm + 1, m + 1):
                        H[sp][y * 100 + j] = ((c[k] - last) / n, n > 1)
                    last, pm = c[k], m
    return H, cum


def biomass_block(S, C, A):
    off = ((C.get('biologie') or {}).get('sanitaire') or {}).get('biomasse_mer_t') or {}
    bio = {int(y) * 100 + i + 1: v / 1000 for y, a in off.items() for i, v in enumerate(a)}
    if not bio:
        return None
    H, cum = harvest(S)
    if 'salar' not in H:
        return None
    L0 = max(bio)                                   # dernier mois officiel
    # dernier mois ou la recolte de l'atlantique ET du coho est connue (la truite, publiee irregulierement, est completee)
    L = max(k for k in H['salar'] if k in H.get('coho', {}))

    def hv(k):   # recolte toutes especes ; une espece sans chiffre ce mois-la reprend son mois de l'annee precedente
        t, est = 0, False
        for sp in H:
            if k in H[sp]:
                t += H[sp][k][0]
                est = est or H[sp][k][1]
            elif k - 100 in H[sp]:
                t += H[sp][k - 100][0]
                est = True
        return t, est

    g = {}
    for k in sorted(bio):
        p = prev(k)
        if p in bio and all(k in H[sp] for sp in ('salar', 'coho')):
            g[k] = (bio[k] - bio[p] + hv(k)[0]) / bio[p]
    gm = {m: [g[k] for k in g if k % 100 == m] for m in range(1, 13)}
    if any(not gm[m] for m in range(1, 13)):
        return None
    mean = lambda a: sum(a) / len(a)
    months = []
    k = L0
    while k < L:
        k = k + 1 if k % 100 < 12 else (k // 100 + 1) * 100 + 1
        months.append(k)

    def path(s, pick=mean, start=None, ms=None, hscale=None):
        b, o = (bio[L0] if start is None else start), {}
        for k in (months if ms is None else ms):
            h = hv(k)[0] if hscale is None else hscale * hv(k - 100)[0]
            b = b * (1 + s * pick(gm[k % 100])) - h
            o[k] = b
        return o

    normal = {'central': path(1), 'low': path(1, min), 'high': path(1, max)}
    anchors = [a for a in (A or {}).get('anchors') or [] if a.get('metric') == 'biomass_yoy_pct' and a.get('use') and a['k'] in normal['central'] and a['k'] - 100 in bio]
    anc = max(anchors, key=lambda a: a['k']) if anchors else None
    s, target = 1.0, None
    if anc:
        target = bio[anc['k'] - 100] * (1 + anc['value'] / 100)
        lo, hi = 0.4, 1.4
        for _ in range(60):
            s = (lo + hi) / 2
            if path(s)[anc['k']] > target:
                hi = s
            else:
                lo = s
    est = path(s)
    # croissance nette cumulee jusqu'au point de calage, contre la meme periode un an plus tot
    grow = None
    if anc:
        ms = [k for k in months if k <= anc['k']]
        if all(prev(k - 100) in bio or k - 100 in bio for k in ms) and prev(ms[0] - 100) in bio:
            g_now = est[anc['k']] - bio[L0] + sum(hv(k)[0] for k in ms)
            g_ly = bio[anc['k'] - 100] - bio[prev(ms[0] - 100)] + sum(hv(k - 100)[0] for k in ms)
            grow = {'now': r(g_now, 0), 'ly': r(g_ly, 0), 'pct': r(100 * (g_now / g_ly - 1), 1), 'harv': r(sum(hv(k)[0] for k in ms), 0), 'harv_ly': r(sum(hv(k - 100)[0] for k in ms), 0)}
    # controle hors echantillon : la deuxieme annee officielle rejouee avec les taux de la premiere
    ys = sorted({k // 100 for k in bio})
    replay = None
    if len(ys) >= 2:
        y0, y1 = ys[-2], ys[-1]
        ks = [y1 * 100 + m for m in range(1, 13) if y0 * 100 + m in g and y1 * 100 + m in bio]
        if ks and prev(ks[0]) in bio:
            b, errs = bio[prev(ks[0])], []
            for k in ks:
                b = b * (1 + g[k - 100]) - hv(k)[0]
                errs.append(100 * (b / bio[k] - 1))
            replay = {'year': y1, 'rates_of': y0, 'max_abs_pct': r(max(abs(e) for e in errs), 1), 'at_anchor_month_pct': r(errs[min(len(errs) - 1, (anc['k'] % 100 if anc else L % 100) - ks[0] % 100)], 1)}
    # et ensuite : la recolte des 3 mois suivants selon l'ecart de biomasse vise en fin de periode
    nxt, kk = [], L
    for _ in range(3):
        kk = kk + 1 if kk % 100 < 12 else (kk // 100 + 1) * 100 + 1
        nxt.append(kk)
    scen = None
    if all(k - 100 in bio for k in nxt) and all(k - 100 in H['salar'] for k in nxt):
        ly_h = sum(hv(k - 100)[0] for k in nxt)
        gapL = est[L] / bio[L - 100] - 1
        scen = {'months': nxt, 'ly_harvest': r(ly_h, 0), 'rows': []}
        for lab, gap in (('the gap stays as it is', gapL), ('the gap is halved', gapL / 2), ('harvest equals last year', None)):
            if gap is None:
                end = path(s, start=est[L], ms=nxt, hscale=1)[nxt[-1]]
                scen['rows'].append({'label': lab, 'harvest': r(ly_h, 0), 'harvest_pct': 0.0, 'end_gap_pct': r(100 * (end / bio[nxt[-1] - 100] - 1), 1)})
                continue
            tgt = bio[nxt[-1] - 100] * (1 + gap)
            lo, hi = 0.2, 2.0
            for _ in range(60):
                q = (lo + hi) / 2
                if path(s, start=est[L], ms=nxt, hscale=q)[nxt[-1]] > tgt:
                    lo = q
                else:
                    hi = q
            scen['rows'].append({'label': lab, 'harvest': r(q * ly_h, 0), 'harvest_pct': r(100 * (q - 1), 1), 'end_gap_pct': r(100 * gap, 1)})
    series = [{'k': k, 'est': r(est[k], 0), 'ly': r(bio.get(k - 100), 0), 'normal': r(normal['central'][k], 0), 'normal_lo': r(normal['low'][k], 0), 'normal_hi': r(normal['high'][k], 0),
               'harvest': r(hv(k)[0], 1), 'harvest_ly': r(hv(k - 100)[0], 1), 'harvest_est': hv(k)[1]} for k in months]
    return {'official': {'last': L0, 'kt': r(bio[L0], 1), 'yoy_pct': r(100 * (bio[L0] / bio[L0 - 100] - 1), 1) if L0 - 100 in bio else None,
                         'series': [{'k': k, 'kt': r(v, 1)} for k, v in sorted(bio.items())],
                         'source': "Sernapesca, yearly salmon-farming health report (monthly series, all farmed salmonids)"},
            'last': L, 'est': r(est[L], 0), 'est_yoy_pct': r(100 * (est[L] / bio[L - 100] - 1), 1) if L - 100 in bio else None,
            'factor': r(s, 3), 'shortfall_pct': r(100 * (s - 1), 1), 'anchor': anc, 'anchor_target': r(target, 0), 'growth': grow, 'replay': replay,
            'rates': {str(m): [r(100 * x, 1) for x in gm[m]] for m in range(1, 13)}, 'series': series, 'scenarios': scen,
            'method': "Balance: biomass = previous biomass x (1 + monthly growth rate) - harvest. Growth rates per calendar month come from the official 2024-2025 series; "
                      "the latest analyst figure fixes how far this year's growth is from that norm. All farmed salmonids, live weight. An estimate, re-fitted at each new published figure."}


def weights_block(M):
    out = []
    ks = sorted(M)
    for k in ks[-14:]:
        a = ((M[k].get('sizes') or {}).get('atlantic|fresh whole') or {})
        b = ((M.get(str(int(k) - 100), {}).get('sizes') or {}).get('atlantic|fresh whole') or {})
        if a.get('mean_kg') and b.get('mean_kg') and int(k) // 100 == int(ks[-1]) // 100:
            h, hl = a['hist_t'], b['hist_t']
            out.append({'k': int(k), 'kg': a['mean_kg'], 'kg_ly': b['mean_kg'], 'pct': r(100 * (a['mean_kg'] / b['mean_kg'] - 1), 1),
                        'sh6': r(100 * (h[5] + h[6]) / (sum(h) or 1), 0), 'sh6_ly': r(100 * (hl[5] + hl[6]) / (sum(hl) or 1), 0)})
    return out


def prices_block(M):
    ks = sorted(M)

    def one(k):
        sf = (M.get(str(k)) or {}).get('species_form') or {}
        o, wfe, fz = {}, 0, 0
        for f in FORMS:
            t, v = sf.get('atlantic|' + f, (0, 0))
            o[f] = {'t': r(t, 0), 'p': r(v / t, 2) if t else None}
            wfe += t * YIELD[f]
            fz += t * YIELD[f] if 'frozen' in f else 0
        o['frozen_share'] = r(100 * fz / wfe, 1) if wfe else None
        o['frozen_kt'] = r(fz / 1000, 1)
        o['wfe_kt'] = r(wfe / 1000, 1)
        return o

    series = []
    for k in ks[-24:]:
        a = one(int(k))
        series.append({'k': int(k), **{f.replace(' ', '_'): a[f]['p'] for f in FORMS}, 'frozen_share': a['frozen_share'], 'frozen_kt': a['frozen_kt'], 'wfe_kt': a['wfe_kt']})
    L = int(ks[-1])
    last, ly = one(L), one(L - 100)
    q = [L, prev(L), prev(prev(L))]
    fz3 = sum(one(k)['frozen_kt'] or 0 for k in q)
    fz3l = sum(one(k - 100)['frozen_kt'] or 0 for k in q)
    return {'last': L, 'forms': [{'form': f, 'p': last[f]['p'], 'p_ly': ly[f]['p'], 'pct': r(100 * (last[f]['p'] / ly[f]['p'] - 1), 1) if last[f]['p'] and ly[f]['p'] else None,
                                  't': last[f]['t'], 't_ly': ly[f]['t']} for f in FORMS],
            'frozen_share': last['frozen_share'], 'frozen_share_ly': ly['frozen_share'], 'frozen_3m_kt': r(fz3, 1), 'frozen_3m_kt_ly': r(fz3l, 1),
            'frozen_3m_pct': r(100 * (fz3 / fz3l - 1), 1) if fz3l else None, 'series': series,
            'note': "FOB prices and tonnes from the customs declarations, Atlantic salmon; frozen share in live-weight equivalent (whole / 0.90, fillets / 0.58)."}


def main():
    S, C, A, X = J('chile_subpesca.json') or {}, J('chili.json') or {}, J('chile_anchors.json'), J('chile_customs.json') or {}
    M = X.get('months') or {}
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M+00:00'),
                    'sources': 'Sernapesca (official biomass), Subpesca (monthly harvest), Chilean customs (prices, sizes), analyst figures kept by hand in data/chile_anchors.json'},
           'biomass': biomass_block(S, C, A), 'weights': weights_block(M) if M else [], 'prices': prices_block(M) if M else None,
           'anchors': (A or {}).get('anchors') or []}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    b = out['biomass']
    print('chile_market.json :', (f"biomasse estimee {b['est']} kt fin {b['last']} ({b['est_yoy_pct']:+} % sur un an), croissance {b['shortfall_pct']:+} % vs normale" if b else 'pas de biomasse'),
          '| prix', out['prices']['last'] if out['prices'] else None, '| poids', len(out['weights']), 'mois')


if __name__ == '__main__':
    main()
