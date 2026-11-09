#!/usr/bin/env python3
"""
Norvege : 6 kg+ des six prochains mois, tires du stock de gros poissons en mer (methode simple, testee sur le passe).

    python3 scripts/build_six_stock.py      -> data/six_stock.json

1. Chaque mois du registre (Fiskeridirektoratet, data.json 'cohort', zone x generation) :
   - stock en mer au-dessus de 3, 4, 5 et 6 kg vide (biomasse, kt vide), a partir du poids moyen et d'une dispersion
     lognormale (coefficient de variation 0,27, vide = 0,888 x vif) ;
   - 6 kg+ recoltes dans le mois (meme calcul sur le poids moyen des poissons recoltes).
2. Prevision faite a la fin du mois k :
   - mois k+1 a k+3 : 6 kg+ recoltes = stock au-dessus de 4 kg x rapport moyen des annees passees au meme mois ;
   - mois k+4 a k+6 : meme chose avec le stock au-dessus de 3 kg (les poissons qui auront 6 kg dans 4 a 6 mois).
   Fourchette = rapports le plus bas et le plus haut des annees passees. Aucun scenario, aucun avis : une regle de trois.
3. Test : la meme regle rejouee a chaque mois depuis 2020 avec seulement les annees connues a ce moment-la ;
   erreur moyenne comparee a "les memes mois qu'un an plus tot".
4. Journal : la prevision de chaque nouveau registre est figee (live) pour juger la methode sur des mois jamais vus.

Le stock et les 6 kg+ recoltes sont des estimations tirees des poids moyens du registre, pas des pesees.
"""
import collections
import datetime as dt
import io
import json
import math
import os
import statistics as S
from statistics import NormalDist

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
OUT = os.path.join(ROOT, 'data', 'six_stock.json')
PHI = NormalDist().cdf
GUT, CV = 0.888, 0.27
HOR = [((1, 2, 3), '4', 'next 3 months'), ((4, 5, 6), '3', 'months 4-6')]
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def kg_above(w, lo):
    """part en kg des poissons au-dessus de lo kg vide, pour un poids moyen vif w"""
    s2 = math.log(1 + CV * CV)
    sd, mu = math.sqrt(s2), math.log(w) - s2 / 2
    return 1 - PHI((math.log(lo / GUT) - mu - s2) / sd)


def sh(k, n):
    y, m = k // 100, k % 100 - 1 + n
    y += m // 12
    return y * 100 + m % 12 + 1


def ml(k):
    return f'{MON[k % 100 - 1]} {k // 100}'


def main():
    D = json.load(io.open(DATA, encoding='utf-8'))
    st = collections.defaultdict(lambda: collections.defaultdict(float))
    hv = collections.defaultdict(float)
    for c in D['cohort']:
        if not c['po'] or not c['weight_kg']:
            continue
        k = c['year'] * 100 + c['month']
        if c['stock']:
            b = c['stock'] * c['weight_kg'] * GUT / 1e6
            for lo in (3, 4, 5, 6):
                st[k][str(lo)] += b * kg_above(c['weight_kg'], lo)
        if c['harv_stk'] and c['harv_kg']:
            hv[k] += c['harv_kg'] * GUT / 1e6 * kg_above(c['harv_kg'] / c['harv_stk'], 6)
    K = sorted(st)
    last = K[-1]
    H1 = lambda k: hv.get(k) if k <= last else None

    def H(k, js):
        v = [H1(sh(k, j)) for j in js]
        return sum(v) if None not in v else None

    def ratios(k, js, lo, j=None):
        """rapports des annees passees, au meme mois, connus a la fin du mois k"""
        P = [p for p in K if p % 100 == k % 100 and p < k and sh(p, max(js)) <= k and st[p][lo] > 0 and H(p, js) is not None]
        if j is not None:
            return [H1(sh(p, j)) / st[p][lo] for p in P]
        return [H(p, js) / st[p][lo] for p in P]

    # test sur le passe
    tests = {}
    for js, lo, lab in HOR:
        rows, err, naive = [], [], []
        for k in K:
            a = H(k, js)
            if a is None or k < 202001:
                continue
            R = ratios(k, js, lo)
            if len(R) < 2:
                continue
            f = S.mean(R) * st[k][lo]
            err.append(abs(f / a - 1))
            ly = H(sh(k, -12), js)
            if ly:
                naive.append(abs(ly / a - 1))
            rows.append({'k': k, 'fcst': round(f, 1), 'lo': round(min(R) * st[k][lo], 1), 'hi': round(max(R) * st[k][lo], 1), 'actual': round(a, 1), 'ly': round(ly, 1) if ly else None})
        tests[lab] = {'stock': lo, 'n': len(err), 'mape': round(100 * S.mean(err), 1), 'naive_mape': round(100 * S.mean(naive), 1),
                      'inside_range': round(100 * sum(r['lo'] <= r['actual'] <= r['hi'] for r in rows) / len(rows)), 'rows': rows}

    # prevision du dernier registre
    fc = []
    for js, lo, lab in HOR:
        R = ratios(last, js, lo)
        ly = H(sh(last, -12), js)
        months = []
        for j in js:
            Rj = ratios(last, js, lo, j)
            months.append({'k': sh(last, j), 'fcst': round(S.mean(Rj) * st[last][lo], 1), 'ly': round(H1(sh(last, j - 12)), 1) if H1(sh(last, j - 12)) else None})
        f = S.mean(R) * st[last][lo]
        fc.append({'label': lab, 'span': f'{ml(sh(last, js[0]))} – {ml(sh(last, js[-1]))}', 'stock_above': int(lo), 'stock_kt': round(st[last][lo], 1),
                   'stock_ly_kt': round(st[sh(last, -12)][lo], 1), 'fcst': round(f, 1), 'lo': round(min(R) * st[last][lo], 1), 'hi': round(max(R) * st[last][lo], 1),
                   'ly': round(ly, 1) if ly else None, 'chg': round(100 * (f / ly - 1), 1) if ly else None, 'years': len(R), 'months': months,
                   'mape': tests[lab]['mape'], 'naive_mape': tests[lab]['naive_mape']})

    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    live = {e['made_from']: e for e in old.get('live', [])}
    if last not in live:
        live[last] = {'made_from': last, 'made': dt.date.today().isoformat(), 'forecasts': [{x: f[x] for x in ('label', 'span', 'fcst', 'lo', 'hi', 'ly')} for f in fc]}
    # verdict des previsions figees dont les mois sont maintenant connus
    for e in live.values():
        for f, (js, lo, lab) in zip(e['forecasts'], HOR):
            a = H(e['made_from'], js)
            if a is not None:
                f['actual'] = round(a, 1)
    stocks = [{'k': k, **{f'above{lo}': round(st[k][lo], 1) for lo in ('3', '4', '5', '6')}, 'h6': round(hv[k], 1)} for k in K if k >= 201901]
    out = {'meta': {'generated': dt.date.today().isoformat(), 'register': last, 'register_label': ml(last),
                    'method': 'Big-fish stock at sea (Biomasseregisteret, zone x generation, lognormal size spread CV 0.27) x the average ratio of past years for the same month. '
                              'Next 3 months from the stock above 4 kg gutted, months 4-6 from the stock above 3 kg. Range = lowest and highest past ratio. Estimates from average weights, not weighings.'},
           'forecast': fc, 'tests': tests, 'live': sorted(live.values(), key=lambda e: e['made_from']), 'stocks': stocks}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    for f in fc:
        print(f"{f['span']}: 6 kg+ {f['fcst']} kt ({f['lo']}-{f['hi']}), un an plus tot {f['ly']} ({f['chg']:+.0f} %) | stock > {f['stock_above']} kg {f['stock_kt']} kt vs {f['stock_ly_kt']} | erreur moyenne {f['mape']} % (naif {f['naive_mape']} %)")


if __name__ == '__main__':
    main()
