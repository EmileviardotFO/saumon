#!/usr/bin/env python3
"""
Norvege : 6 kg+ des six prochains mois, tires du stock de poissons qui peuvent atteindre 6 kg a temps (regle en degres-jours).

    python3 scripts/build_six_stock.py      -> data/six_stock.json

1. Chaque mois du registre (Fiskeridirektoratet, data.json 'cohort', zone x generation) : poids moyen et nombre de poissons par lot ;
   dispersion lognormale (CV 0,27 ; vide = 0,888 x vif) pour estimer la biomasse au-dessus d'un poids donne, et les 6 kg+ recoltes
   dans le mois (meme calcul sur le poids moyen des poissons recoltes).
2. Seuil en degres-jours : un poisson atteint 6 kg vide (6,76 kg vif) dans j mois s'il pese aujourd'hui au moins w*, avec
   w*^(1/3) = 6760^(1/3) - TGC x degres-jours / 1000 ; TGC = croissance normale de la saison (3 ans), degres-jours = temperatures
   normales des memes mois (3 ans). L'ete, le seuil descend vers 3 kg ; l'hiver, il monte vers 5-6 kg : c'est ce qui change tout.
   Base = biomasse au-dessus de w*, moyenne sur les mois vises.
3. Prevision = base x rapport moyen (6 kg+ recoltes / base) des annees passees au meme mois. Fourchette = rapports le plus bas et le
   plus haut. Variante « si l'anomalie de temperature actuelle persiste » (anomalie amortie de 0,6 par mois).
4. Test : la regle rejouee a chaque mois depuis 2020 avec seulement les annees connues a ce moment-la ; comparee a la regle a seuil
   fixe (> 4 kg) et a « les memes mois qu'un an plus tot ». Journal des previsions figees a chaque nouveau registre.
5. Alerte precoce : part de 6 kg+ du marche spot (Sitagri / Sjomat Norge, hebdomadaire, hors Leroy, SalMar, Nordlaks) contre les
   memes semaines un an plus tot ; correlation 0,83 avec la part de 6 kg+ du registre du meme mois, qui ne parait que 3 a 4 semaines
   plus tard. Et « hors historique » : poids de recolte, croissance ou temperature au-dela de tout ce qu'on a vu depuis 2018.
"""
import calendar
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
TARGET = 6 / GUT                      # 6 kg vide en vif
HOR = [((1, 2, 3), 'next 3 months'), ((4, 5, 6), 'months 4-6')]
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
days = lambda k: calendar.monthrange(k // 100, k % 100)[1]


def above(w, lo_live):
    """part en kg des poissons au-dessus de lo_live kg vif, pour un poids moyen vif w"""
    s2 = math.log(1 + CV * CV)
    return 1 - PHI((math.log(lo_live) - (math.log(w) - s2 / 2) - s2) / math.sqrt(s2))


def sh(k, n):
    y, m = k // 100, k % 100 - 1 + n
    y += m // 12
    return y * 100 + m % 12 + 1


def ml(k):
    return f'{MON[k % 100 - 1]} {k // 100}'


def main():
    D = json.load(io.open(DATA, encoding='utf-8'))
    # temperature nationale par mois (BarentsWatch, semaine -> mois de son jeudi, ponderee par sites)
    tt = collections.defaultdict(lambda: [0.0, 0])
    for r in (D.get('bw_weekly') or {}).get('rows', []):
        if r.get('t') is None or not r.get('nt'):
            continue
        th = dt.date.fromisocalendar(r['y'], r['w'], 4)
        x = tt[th.year * 100 + th.month]
        x[0] += r['t'] * r['nt']
        x[1] += r['nt']
    T = {k: v[0] / v[1] for k, v in tt.items() if v[1]}
    C = collections.defaultdict(dict)
    for c in D['cohort']:
        if c['po'] and c['weight_kg']:
            C[(c['po'], c['cohort'])][c['year'] * 100 + c['month']] = c
    K = sorted({k for ser in C.values() for k in ser})
    last = K[-1]
    stockw = collections.defaultdict(list)
    hv, hvol, hw = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(lambda: [0.0, 0.0])
    for ser in C.values():
        for k, c in ser.items():
            if c['stock']:
                stockw[k].append((c['stock'] * c['weight_kg'] * GUT / 1e6, c['weight_kg']))
            if c['harv_stk'] and c['harv_kg']:
                hv[k] += c['harv_kg'] * GUT / 1e6 * above(c['harv_kg'] / c['harv_stk'], TARGET)
                hvol[k] += c['harv_kg'] * GUT / 1e6
                hw[k][0] += c['harv_kg']
                hw[k][1] += c['harv_stk']
    stock_above = lambda k, lo: sum(b * above(w, lo) for b, w in stockw[k])
    stock_fixed = {k: {lo: round(stock_above(k, lo / GUT), 1) for lo in (3, 4, 5, 6)} for k in K}

    def tgc_month(k):
        """TGC national du mois (poissons de plus de 1 kg), grammes"""
        t = T.get(k)
        if not t or t < 1:
            return None
        num = den = 0.0
        for ser in C.values():
            a, b = ser.get(sh(k, -1)), ser.get(k)
            if not a or not b or not a['stock'] or not b['stock'] or a['stock'] < 2e5 or a['weight_kg'] < 1:
                continue
            dead = (b.get('dead_stk') or 0) + (b.get('loss_stk') or 0)
            prod = b['stock'] * b['weight_kg'] - a['stock'] * a['weight_kg'] + (b.get('harv_kg') or 0) + dead * (a['weight_kg'] + b['weight_kg']) / 4
            gap = b['stock'] - a['stock'] + (b.get('harv_stk') or 0) + dead
            prod += -gap * 0.15 if gap > 0 else -gap * (a['weight_kg'] + b['weight_kg']) / 2
            gf = prod / ((a['stock'] + b['stock']) / 2)
            w0 = a['weight_kg']
            if w0 + gf <= 0:
                continue
            tg = ((w0 + gf) ** (1 / 3) - w0 ** (1 / 3)) * 10000 / (t * days(k))
            if -1 < tg < 6:
                num += tg * a['stock']
                den += a['stock']
        return num / den if den else None
    TG = {k: tgc_month(k) for k in K if k >= 201801}
    anomaly = lambda k: (T[k] - S.mean([T[sh(k, -12 * y)] for y in (1, 2, 3) if sh(k, -12 * y) in T])) if k in T and any(sh(k, -12 * y) in T for y in (1, 2, 3)) else 0.0

    def threshold(k, j, decay):
        """poids vif a partir duquel un poisson atteint 6 kg vide en j mois, aux conditions normales (+ anomalie amortie si decay)"""
        an = anomaly(k) if decay else 0.0
        dd = 0.0
        for m in range(1, j + 1):
            km = sh(k, m)
            tl = [T[sh(km, -12 * y)] for y in (1, 2, 3) if sh(km, -12 * y) in T]
            if not tl:
                return None
            dd += (S.mean(tl) + an * 0.6 ** m) * days(km)
        norm = [TG.get(sh(k, m - 12 * y)) for y in (1, 2, 3) for m in range(1, j + 1)]
        norm = [x for x in norm if x]
        if not norm:
            return None
        cube = (TARGET * 1000) ** (1 / 3) - S.mean(norm) * dd / 1000
        return cube ** 3 / 1000 if cube > 0 else None
    cacheB = {}

    def basis(k, js, decay=False):
        key = (k, js, decay)
        if key not in cacheB:
            v, ws = 0.0, []
            for j in js:
                w = threshold(k, j, decay)
                if w is None:
                    v = None
                    break
                ws.append(w)
                v += stock_above(k, w)
            cacheB[key] = (v / len(js), ws) if v is not None else (None, None)
        return cacheB[key]

    def H(k, js):
        ks = [sh(k, j) for j in js]
        return sum(hv[x] for x in ks) if max(ks) <= last and all(hvol[x] > 0 for x in ks) else None

    def ratios(k, js, kind, decay=False):
        """rapports des annees passees au meme mois, connus a la fin de k ; kind = 'dd' ou seuil fixe (vif)"""
        R = []
        for p in K:
            if p % 100 != k % 100 or p >= k or p < 201901 or sh(p, max(js)) > k or H(p, js) is None:
                continue
            b = basis(p, js, decay)[0] if kind == 'dd' else stock_above(p, kind)
            if b:
                R.append(H(p, js) / b)
        return R

    # ---- test sur le passe (regle degres-jours, seuil fixe > 4 kg, l'an dernier) ----
    tests = {}
    for js, lab in HOR:
        rows, e_dd, e_fx, e_ly, inr = [], [], [], [], []
        for k in K:
            a = H(k, js)
            if a is None or k < 202001:
                continue
            R, Rf = ratios(k, js, 'dd'), ratios(k, js, 4 / GUT)
            b = basis(k, js)[0]
            if len(R) < 2 or len(Rf) < 2 or not b:
                continue
            f, fx = S.mean(R) * b, S.mean(Rf) * stock_above(k, 4 / GUT)
            ly = H(sh(k, -12), js)
            e_dd.append(abs(f / a - 1))
            e_fx.append(abs(fx / a - 1))
            if ly:
                e_ly.append(abs(ly / a - 1))
            lo, hi = min(R) * b, max(R) * b
            inr.append(lo <= a <= hi)
            rows.append({'k': k, 'fcst': round(f, 1), 'lo': round(lo, 1), 'hi': round(hi, 1), 'fixed4': round(fx, 1), 'actual': round(a, 1), 'ly': round(ly, 1) if ly else None})
        tests[lab] = {'n': len(rows), 'mape': round(100 * S.mean(e_dd), 1), 'mape_fixed4': round(100 * S.mean(e_fx), 1), 'naive_mape': round(100 * S.mean(e_ly), 1),
                      'inside_range': round(100 * S.mean(inr)), 'rows': rows}

    # ---- prevision du dernier registre ----
    fc = []
    for js, lab in HOR:
        R = ratios(last, js, 'dd')
        b, ws = basis(last, js)
        bd = basis(last, js, True)[0]
        Rd = ratios(last, js, 'dd', True)
        ly = H(sh(last, -12), js)
        f = S.mean(R) * b
        months = []
        for j in js:
            Rj = [hv[sh(p, j)] / basis(p, js)[0] for p in K if p % 100 == last % 100 and p < last and p >= 201901 and sh(p, j) <= last and basis(p, js)[0] and hvol[sh(p, j)] > 0]
            months.append({'k': sh(last, j), 'fcst': round(S.mean(Rj) * b, 1) if Rj else None, 'ly': round(hv[sh(last, j - 12)], 1) if hvol[sh(last, j - 12)] else None})
        fc.append({'label': lab, 'span': f'{ml(sh(last, js[0]))} – {ml(sh(last, js[-1]))}', 'threshold_live_kg': [round(w, 2) for w in ws], 'threshold_gutted_kg': [round(w * GUT, 2) for w in ws],
                   'basis_kt': round(b, 1), 'basis_ly_kt': round(basis(sh(last, -12), js)[0] or 0, 1),
                   'fcst': round(f, 1), 'lo': round(min(R) * b, 1), 'hi': round(max(R) * b, 1), 'ly': round(ly, 1) if ly else None, 'chg': round(100 * (f / ly - 1), 1) if ly else None,
                   'fcst_if_anomaly_persists': round(S.mean(Rd) * bd, 1) if Rd and bd else None, 'temp_anomaly_c': round(anomaly(last), 2),
                   'years': len(R), 'months': months, 'mape': tests[lab]['mape'], 'mape_fixed4': tests[lab]['mape_fixed4'], 'naive_mape': tests[lab]['naive_mape']})

    # ---- alertes ----
    # 1) part de 6 kg+ du marche spot : semaines connues du mois en cours et du mois suivant le registre, contre un an plus tot
    sp = collections.defaultdict(list)
    for r in D.get('weekly') or []:
        if r.get('sh_6plus') is None:
            continue
        yy = r['report_year'] - (1 if r['price_week'] > r['report_week'] + 20 else 0)
        try:
            th = dt.date.fromisocalendar(yy, r['price_week'], 4)
        except ValueError:
            continue
        sp[th.year * 100 + th.month].append((r['price_week'], r['sh_6plus'], r.get('sh_5plus')))
    spot_last = max(sp) if sp else None
    spot = []
    if spot_last:
        for k in [sh(spot_last, -i) for i in (2, 1, 0)]:
            cur, ly_ = sp.get(k, []), sp.get(k - 100, [])
            wk = {w for w, _, _ in cur}
            lyw = [x for x in ly_ if x[0] in wk] or ly_
            reg = round(100 * hv[k] / hvol[k], 1) if hvol[k] > 0 else None
            regly = round(100 * hv[k - 100] / hvol[k - 100], 1) if hvol[k - 100] > 0 else None
            if cur:
                spot.append({'k': k, 'weeks': len(cur), 'spot6': round(S.mean(x[1] for x in cur), 1), 'spot6_ly': round(S.mean(x[1] for x in lyw), 1) if lyw else None,
                             'spot5': round(S.mean(x[2] for x in cur if x[2] is not None), 1) if any(x[2] is not None for x in cur) else None,
                             'register6': reg, 'register6_ly': regly})
    alerts = []
    s0 = spot[-1] if spot else None
    if s0 and s0['spot6_ly'] is not None and s0['weeks'] >= 2 and (s0['spot6'] - s0['spot6_ly'] >= 5 or (s0['spot6_ly'] > 0 and s0['spot6'] / s0['spot6_ly'] >= 1.6)):
        alerts.append({'level': 'high', 'what': 'spot_6plus_up', 'text': f"Spot market: 6 kg+ are {s0['spot6']} % of volumes in {ml(s0['k'])} (first {s0['weeks']} weeks) against {s0['spot6_ly']} % a year earlier — the register will probably show far more 6 kg+ than last year."})
    if s0 and s0['spot6_ly'] is not None and s0['weeks'] >= 2 and s0['spot6_ly'] - s0['spot6'] >= 5:
        alerts.append({'level': 'high', 'what': 'spot_6plus_down', 'text': f"Spot market: 6 kg+ are {s0['spot6']} % of volumes in {ml(s0['k'])} against {s0['spot6_ly']} % a year earlier — far fewer big fish than last year."})
    # 2) hors historique : poids de recolte (vs meme mois un an plus tot), temperature (anomalie), croissance (TGC vs normale saison)
    hist = {'hw_rel': [], 't_anom': [], 'tgc_rel': []}
    def feat(k):
        a = hw[k][0] / hw[k][1] / (hw[k - 100][0] / hw[k - 100][1]) if hw[k][1] and hw[k - 100][1] else None
        tn = [TG.get(sh(k, -12 * y)) for y in (1, 2, 3)]
        tn = [x for x in tn if x]
        g = TG[k] / S.mean(tn) if TG.get(k) and tn else None
        return a, anomaly(k) if k in T else None, g
    for k in K:
        if 201901 <= k < last:
            a, t, g = feat(k)
            if a: hist['hw_rel'].append(a)
            if t is not None: hist['t_anom'].append(t)
            if g: hist['tgc_rel'].append(g)
    a, t, g = feat(last)
    out_hist = {'harvest_weight_vs_ly': round(a, 3) if a else None, 'temp_anomaly_c': round(t, 2) if t is not None else None, 'tgc_vs_normal': round(g, 3) if g else None,
                'past_range': {k2: [round(min(v), 3), round(max(v), 3)] for k2, v in hist.items() if v}}
    if a and hist['hw_rel'] and (a > max(hist['hw_rel']) or a < min(hist['hw_rel'])):
        alerts.append({'level': 'high', 'what': 'harvest_weight_out_of_range', 'text': f"Harvested fish in {ml(last)} weigh {100 * (a - 1):+.0f} % against a year earlier — outside everything seen since 2019 ({100 * (min(hist['hw_rel']) - 1):+.0f} to {100 * (max(hist['hw_rel']) - 1):+.0f} %). The 6 kg+ rule is calibrated on normal years: expect the actual to land outside its range."})
    if t is not None and hist['t_anom'] and (t > max(hist['t_anom']) or t < min(hist['t_anom'])):
        alerts.append({'level': 'medium', 'what': 'temperature_out_of_range', 'text': f"Sea temperature in {ml(last)} is {t:+.1f} °C against the normal of the last 3 years — outside everything seen since 2019."})
    if g and hist['tgc_rel'] and (g > max(hist['tgc_rel']) or g < min(hist['tgc_rel'])):
        alerts.append({'level': 'medium', 'what': 'growth_out_of_range', 'text': f"Temperature-corrected growth (TGC) in {ml(last)} is {100 * (g - 1):+.0f} % against the seasonal normal — outside everything seen since 2019."})
    # alerte retrospective : la part spot aurait-elle prevenu en 2025 ? (pour la page)
    retro = []
    for k in (202410, 202510, 202511, 202512, 202601):
        cur, ly_ = sp.get(k, []), sp.get(k - 100, [])
        if cur and ly_:
            retro.append({'k': k, 'spot6': round(S.mean(x[1] for x in cur), 1), 'spot6_ly': round(S.mean(x[1] for x in ly_), 1),
                          'register6': round(100 * hv[k] / hvol[k], 1) if hvol[k] else None, 'register6_ly': round(100 * hv[k - 100] / hvol[k - 100], 1) if hvol[k - 100] else None})

    # ---- journal des previsions figees ----
    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    live = {e['made_from']: e for e in old.get('live', []) if e.get('rule') == 'dd'}
    if last not in live:
        live[last] = {'made_from': last, 'made': dt.date.today().isoformat(), 'rule': 'dd', 'forecasts': [{x: f[x] for x in ('label', 'span', 'fcst', 'lo', 'hi', 'ly', 'fcst_if_anomaly_persists')} for f in fc]}
    for e in live.values():
        for f, (js, lab) in zip(e['forecasts'], HOR):
            act = H(e['made_from'], js)
            if act is not None:
                f['actual'] = round(act, 1)
    stocks = [{'k': k, **{f'above{lo}': v for lo, v in stock_fixed[k].items()}, 'h6': round(hv[k], 1), 'share6': round(100 * hv[k] / hvol[k], 1) if hvol[k] else None,
               'harvest_w_gutted': round(hw[k][0] / hw[k][1] * GUT, 2) if hw[k][1] else None, 'temp': round(T[k], 2) if k in T else None, 'tgc': round(TG[k], 2) if TG.get(k) else None}
              for k in K if k >= 201901]
    out = {'meta': {'generated': dt.date.today().isoformat(), 'register': last, 'register_label': ml(last), 'rule': 'dd',
                    'method': 'Stock of fish that can reach 6 kg gutted within the horizon (threshold from normal seasonal growth, TGC, and normal degree-days; Biomasseregisteret, zone x generation, '
                              'lognormal size spread CV 0.27) x the average ratio of past years for the same month. Range = lowest and highest past ratio. Estimates from average weights, not weighings.'},
           'forecast': fc, 'tests': tests, 'alerts': alerts, 'spot': spot, 'spot_retro': retro, 'out_of_history': out_hist,
           'live': sorted(live.values(), key=lambda e: e['made_from']), 'stocks': stocks}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    for f in fc:
        print(f"{f['span']}: 6 kg+ {f['fcst']} kt ({f['lo']}-{f['hi']}; anomalie persistante {f['fcst_if_anomaly_persists']}), un an plus tot {f['ly']} ({f['chg']:+.0f} %) | seuils {f['threshold_gutted_kg']} kg vide, base {f['basis_kt']} kt vs {f['basis_ly_kt']} | erreur {f['mape']} % (seuil fixe {f['mape_fixed4']}, naif {f['naive_mape']})")
    for a_ in alerts:
        print('ALERTE', a_['level'], a_['text'])
    print('spot', spot, '\nhors historique', out_hist)


if __name__ == '__main__':
    main()
