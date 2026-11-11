#!/usr/bin/env python3
"""
Onglet Generations (Norvege) : les chiffres des quatre pages (Verdict, generation en recolte, generation suivante, zones).

    python3 scripts/build_generations.py      -> data/generations.json

Tout vient du registre de la biomasse (data.json 'cohort' : zone x generation x mois) et des releves BarentsWatch (temperature,
poux), plus les sorties de build_gen_outlook.py (scenarios de volumes) et build_six_stock.py (6 kg+ en degres-jours, alertes).
Rien n'est saisi a la main. Les textes de la page sont ecrits par la page a partir de ces chiffres.

Contenu :
  state        la generation en recolte (old) et la suivante (new) au dernier registre, contre la generation precedente au meme mois
  traj         poids moyen et poissons restants, mois par mois depuis janvier de l'annee de mise a l'eau, pour chaque generation
  depletion    poissons restants projetes au rythme de recolte de la generation precedente ; mois ou il en reste 20 %
  handover     part de la recolte faite par la nouvelle generation, saison passee et saison en cours projetee ; mois du passage a 50 %
  tgc, mort    TGC et mortalite sur 3 mois et depuis l'automne, generation contre generation
  smolt        poids a 1-3 mois et nombre de poissons des dernieres generations
  zones        par zone : poissons, poids, stock > 5 kg, TGC et temperature des 3 derniers mois, contre un an plus tot
  factors      les 8 facteurs de la vague de 6 kg+ de 2025-26, valeur actuelle contre un an plus tot, sens (up/down/mixed)
  volume       scenarios de volumes de build_gen_outlook (6 mois, tous calibres, 5 kg+, 6 kg+), budget de poissons (generation videe au
               rythme de l'an dernier x avance de poids), fourchette modele/budget et estimation du mois suivant
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
D_ = lambda f: json.load(io.open(os.path.join(ROOT, 'data', f), encoding='utf-8')) if os.path.exists(os.path.join(ROOT, 'data', f)) else None
OUT = os.path.join(ROOT, 'data', 'generations.json')
PHI = NormalDist().cdf
GUT, CV = 0.888, 0.27
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
days = lambda k: calendar.monthrange(k // 100, k % 100)[1]


def above(w, lo_gutted):
    s2 = math.log(1 + CV * CV)
    return 1 - PHI((math.log(lo_gutted / GUT) - (math.log(w) - s2 / 2) - s2) / math.sqrt(s2))


def sh(k, n):
    y, m = k // 100, k % 100 - 1 + n
    y += m // 12
    return y * 100 + m % 12 + 1


def r(v, d=2):
    return None if v is None else round(v, d)


def main():
    D = D_('data.json')
    G = D_('gen_outlook.json') or {}
    SIX = D_('six_stock.json') or {}
    C = collections.defaultdict(dict)
    for c in D['cohort']:
        if c['po'] and c['weight_kg']:
            C[(c['po'], c['cohort'])][c['year'] * 100 + c['month']] = c
    K = sorted({k for ser in C.values() for k in ser})
    last = K[-1]
    # temperature et poux par zone et mois ; aussi par zone et semaine ISO
    tt = collections.defaultdict(lambda: [0.0, 0])
    lw = collections.defaultdict(list)
    tw = collections.defaultdict(lambda: [0.0, 0])
    for x in (D.get('bw_weekly') or {}).get('rows', []):
        th = dt.date.fromisocalendar(x['y'], x['w'], 4)
        km = th.year * 100 + th.month
        if x.get('t') is not None and x.get('nt'):
            tt[(x['po'], km)][0] += x['t'] * x['nt']
            tt[(x['po'], km)][1] += x['nt']
            tw[(x['po'], x['y'], x['w'])][0] += x['t'] * x['nt']
            tw[(x['po'], x['y'], x['w'])][1] += x['nt']
        if x.get('lice') is not None:
            lw[(x['po'], x['y'], x['w'])].append(x['lice'])
    T = {k: v[0] / v[1] for k, v in tt.items() if v[1]}

    def gstate(gen, k):
        n = b = b5 = h = hk = dd = 0.0
        for (po, gg), ser in C.items():
            if gg != gen or k not in ser:
                continue
            c = ser[k]
            if c['stock']:
                n += c['stock']
                b += c['stock'] * c['weight_kg']
                b5 += c['stock'] * c['weight_kg'] * GUT / 1e6 * above(c['weight_kg'], 5)
            h += c['harv_stk'] or 0
            hk += c['harv_kg'] or 0
            dd += c['dead_stk'] or 0
        return dict(n=n / 1e6, w=b / n if n else None, bio=b * GUT / 1e6, b5=b5, h=h / 1e6, hw=hk / h if h else None, dead=dd / 1e6)

    # generation en recolte = celle qui a le plus de poissons de plus de 2,5 kg ; suivante = annee + 1
    cand = collections.defaultdict(float)
    for (po, gg), ser in C.items():
        c = ser.get(last)
        if c and c['stock'] and c['weight_kg'] >= 2.5:
            cand[gg] += c['stock']
    old = max(cand, key=cand.get) if cand else last // 100 - 1
    new = old + 1
    st = {'old': gstate(old, last), 'old_ly': gstate(old - 1, sh(last, -12)), 'new': gstate(new, last), 'new_ly': gstate(new - 1, sh(last, -12))}

    def traj(gen):
        out = []
        for i in range(0, 33):
            k = sh(gen * 100 + 1, i)
            s = gstate(gen, k) if k <= last else None
            out.append([k, r(s['w']) if s and s['n'] > 5 else None, r(s['n'], 1) if s and s['n'] > 0.5 else None])
        return out
    TR = {g: traj(g) for g in range(old - 6, new + 1)}

    def tgc_month(gen, k, zone=None):
        num = den = 0.0
        for (po, gg), ser in C.items():
            if gg != gen or (zone and po != zone):
                continue
            a, b = ser.get(sh(k, -1)), ser.get(k)
            t = T.get((po, k))
            if not a or not b or not a['stock'] or not b['stock'] or a['stock'] < 2e5 or not t or t < 1 or a['weight_kg'] < 0.3:
                continue
            dead = (b.get('dead_stk') or 0) + (b.get('loss_stk') or 0)
            prod = b['stock'] * b['weight_kg'] - a['stock'] * a['weight_kg'] + (b.get('harv_kg') or 0) + dead * (a['weight_kg'] + b['weight_kg']) / 4
            gap = b['stock'] - a['stock'] + (b.get('harv_stk') or 0) + dead
            prod += -gap * 0.15 if gap > 0 else -gap * (a['weight_kg'] + b['weight_kg']) / 2
            gf = prod / ((a['stock'] + b['stock']) / 2)
            w0 = a['weight_kg']
            if w0 + gf <= 0:
                continue
            v = ((w0 + gf) ** (1 / 3) - w0 ** (1 / 3)) * 10000 / (t * days(k))
            ddg = t * days(k)
            if -1 < v < 6:
                num += v * ddg * a['stock']
                den += ddg * a['stock']
        return num / den if den else None

    def tgc_win(gen, ks, zone=None):
        v = [tgc_month(gen, k, zone) for k in ks]
        v = [x for x in v if x]
        return r(S.mean(v)) if v else None
    L3 = [sh(last, -2), sh(last, -1), last]
    L3y = [sh(k, -12) for k in L3]
    since = [sh(sh(last, -12), i) for i in range(1, 13)]   # 12 derniers mois
    since_ly = [sh(k, -12) for k in since]
    tgc = {'old_3m': tgc_win(old, L3), 'old_ly_3m': tgc_win(old - 1, L3y), 'old_12m': tgc_win(old, since), 'old_ly_12m': tgc_win(old - 1, since_ly),
           'new_3m': tgc_win(new, L3), 'new_ly_3m': tgc_win(new - 1, L3y)}

    def mort3(gen, k):
        dd = n = 0.0
        for i in range(3):
            kk = sh(k, -i)
            for (po, gg), ser in C.items():
                if gg == gen and kk in ser and sh(kk, -1) in ser and ser[sh(kk, -1)]['stock']:
                    dd += ser[kk]['dead_stk'] or 0
                    n += ser[sh(kk, -1)]['stock']
        return 100 * dd / n if n else None
    mort = {'old': r(mort3(old, last)), 'old_ly': r(mort3(old - 1, sh(last, -12))), 'new': r(mort3(new, last)), 'new_ly': r(mort3(new - 1, sh(last, -12)))}

    # epuisement : rythme de la generation precedente a partir du meme mois
    dep_ly = [gstate(old - 1, sh(sh(last, -12), i))['n'] for i in range(0, 12)]
    ratio = [x / dep_ly[0] if dep_ly[0] else 0 for x in dep_ly]
    dep = [[sh(last, i), r(st['old']['n'] * ratio[i], 1)] for i in range(0, 12)]
    end20 = next((k for k, v in dep if v is not None and v <= 0.2 * st['old']['n']), None)
    end05 = next((k for k, v in dep if v is not None and v <= 0.05 * st['old']['n']), None)

    # passage de relais : part de la recolte faite par la generation la plus recente, d'octobre a septembre
    def share_new(gen, k):
        hn = sum((ser.get(k) or {}).get('harv_kg') or 0 for (po, gg), ser in C.items() if gg == gen)
        ht = sum((ser.get(k) or {}).get('harv_kg') or 0 for ser in C.values())
        return 100 * hn / ht if ht else None
    # saison = octobre de l'annee old-1 ... septembre ; la saison en cours part du mois qui suit le registre
    s0 = new * 100 + 10                       # saison ou la nouvelle generation prend le relais : octobre de son annee de mise a l'eau -> septembre
    season_prev = [[sh(s0, -12 + i), r(share_new(old, sh(s0, -12 + i)), 0)] for i in range(12)]
    season_prev2 = [[sh(s0, -24 + i), r(share_new(old - 1, sh(s0, -24 + i)), 0)] for i in range(12)]
    season_cur = [[sh(s0, i), r(share_new(new, sh(s0, i)), 0) if sh(s0, i) <= last else None] for i in range(12)]
    # projection : part observee jusqu'au registre, puis rythme de la saison passee (meme mois) ajuste du dernier ecart
    proj = []
    off = 0.0
    for i, (k, v) in enumerate(season_cur):
        pv = season_prev[i][1] or 0
        if v is not None:
            off = v - pv
            proj.append([k, v, True])
        else:
            proj.append([k, r(max(0, min(100, pv + off * 0.5)), 0), False])
    hand50 = next((k for k, v, _ in proj if v is not None and v >= 50), None)
    hand50_prev = next((k for k, v in season_prev if v is not None and v >= 50), None)
    hand50_prev2 = next((k for k, v in season_prev2 if v is not None and v >= 50), None)

    def smolt(gen):
        early = []
        for (po, gg), ser in C.items():
            if gg != gen:
                continue
            for kk, c in ser.items():
                if c['stock'] and c['stock'] > 2e5 and c['age_months'] is not None and 1 <= c['age_months'] <= 3:
                    early.append((c['weight_kg'], c['stock']))
        n_sep = sum((ser.get(gen * 100 + 9) or {}).get('stock') or 0 for (po, gg), ser in C.items() if gg == gen)
        n_dec = sum((ser.get(gen * 100 + 12) or {}).get('stock') or 0 for (po, gg), ser in C.items() if gg == gen) if gen * 100 + 12 <= last else None
        return dict(w=r(sum(a * b for a, b in early) / sum(b for a, b in early)) if early else None, n_sep=round(n_sep / 1e6) if n_sep else None, n_dec=round(n_dec / 1e6) if n_dec else None,
                    complete=gen * 100 + 12 <= last)
    SM = {g: smolt(g) for g in (new - 3, new - 2, new - 1, new)}

    Z = []
    for po in range(1, 14):
        def zs(gen, kk):
            c = C.get((po, gen), {}).get(kk)
            return (c['stock'] * c['weight_kg'] * GUT / 1e6 * above(c['weight_kg'], 5) if c and c['stock'] else 0, c['weight_kg'] if c and c['stock'] else None, (c['stock'] or 0) / 1e6 if c else 0)
        a, b = zs(old, last), zs(old - 1, sh(last, -12))
        tz = lambda ks: r(S.mean([T[(po, kk)] for kk in ks if (po, kk) in T]), 1) if any((po, kk) in T for kk in ks) else None
        Z.append(dict(po=po, n=r(a[2], 1), n_ly=r(b[2], 1), w=r(a[1]), w_ly=r(b[1]), b5=r(a[0], 1), b5_ly=r(b[0], 1), tgc=tgc_win(old, L3, po), tgc_ly=tgc_win(old - 1, L3y, po), t=tz(L3), t_ly=tz(L3y)))

    # ---- les huit facteurs ----
    hv = collections.defaultdict(float)
    hvol = collections.defaultdict(float)
    for ser in C.values():
        for k, c in ser.items():
            if c['harv_stk'] and c['harv_kg']:
                hv[k] += c['harv_kg'] * GUT / 1e6 * above(c['harv_kg'] / c['harv_stk'], 6)
                hvol[k] += c['harv_kg'] * GUT / 1e6
    # base : 6 kg+ recoltes d'octobre a mars de la derniere saison complete (et celle d'avant)
    # derniere saison complete d'octobre a mars : commence l'annee d'avant si mars est passe, sinon deux ans avant
    y_oct = last // 100 - 1 if last % 100 >= 4 else last // 100 - 2
    base_ks = [sh(y_oct * 100 + 10, i) for i in range(6)]
    base_ks_ly = [sh(k, -12) for k in base_ks]
    base = sum(hv[k] for k in base_ks)
    base_ly = sum(hv[k] for k in base_ks_ly)
    # semaines ISO des 3 derniers mois du registre (pour temperature et poux)
    def weeks_of(ks):
        out = set()
        for k in ks:
            for dday in range(1, days(k) + 1):
                iso = dt.date(k // 100, k % 100, dday).isocalendar()
                out.add((iso[0], iso[1]))
        return out
    W3, W3y = weeks_of(L3), weeks_of(L3y)
    def temp_nat(W):
        num = den = 0.0
        for (po, y, w), v in tw.items():
            if (y, w) in W:
                num += v[0]
                den += v[1]
        return num / den if den else None
    t_now, t_ly = temp_nat(W3), temp_nat(W3y)
    t_norm = [temp_nat(weeks_of([sh(k, -12 * y) for k in L3])) for y in (1, 2, 3)]
    t_norm = S.mean([x for x in t_norm if x]) if any(t_norm) else None
    def lice_zone(zs, W):
        v = [x for (po, y, w), L in lw.items() if po in zs and (y, w) in W for x in L]
        return S.mean(v) if v else None
    lice_n, lice_n_ly = lice_zone({10, 11, 12}, W3), lice_zone({10, 11, 12}, W3y)
    lice_s, lice_s_ly = lice_zone({4, 5, 6, 7}, W3), lice_zone({4, 5, 6, 7}, W3y)
    OH = SIX.get('out_of_history') or {}
    tgc_norm_now = OH.get('tgc_vs_normal')
    # rythme de recolte : part du stock d'il y a 3 mois recoltee sur les 3 derniers mois (generation en recolte)
    def pace(gen, k):
        n0 = gstate(gen, sh(k, -3))['n']
        h = sum(gstate(gen, sh(k, -i))['h'] for i in range(3))
        return 100 * h / n0 if n0 else None
    pace_now, pace_ly = pace(old, last), pace(old - 1, sh(last, -12))
    def mort_win(gen, k):
        n0 = gstate(gen, sh(k, -3))['n']
        dd = sum(gstate(gen, sh(k, -i))['dead'] for i in range(3))
        return 100 * dd / n0 if n0 else None
    m_now, m_ly = mort_win(old, last), mort_win(old - 1, sh(last, -12))
    o, oly = st['old'], st['old_ly']
    win = f'{MON[L3[0] % 100 - 1]}–{MON[last % 100 - 1]}'
    factors = [
        {'id': 'base', 'label': f'Base to beat: 6 kg+ harvested Oct {y_oct}–Mar {y_oct + 1}', 'now': f'{base:.0f} kt', 'ly': f'{base_ly:.0f} kt', 'dir': 'down' if base > base_ly * 1.15 else 'up' if base < base_ly * 0.85 else 'mixed',
         'why': 'Any % looks weak; read tonnes' if base > base_ly * 1.15 else 'Weak base: % will look strong' if base < base_ly * 0.85 else 'Normal base'},
        {'id': 'weight', 'label': f'Weight advance of G{old} in {MON[last % 100 - 1]}', 'now': f'{o["w"]:.2f} kg ({100 * (o["w"] / oly["w"] - 1):+.0f} %)', 'ly': f'{oly["w"]:.2f} kg', 'dir': 'up' if o['w'] > oly['w'] * 1.02 else 'down' if o['w'] < oly['w'] * 0.98 else 'mixed',
         'why': 'Bigger fish going into the winter' if o['w'] > oly['w'] * 1.02 else 'Smaller fish than a year ago'},
        {'id': 'temp', 'label': f'Sea temperature, {win}', 'now': f'{t_now:.1f} °C ({t_now - t_norm:+.1f} vs normal)' if t_now and t_norm else '—', 'ly': f'{t_ly:.1f} °C' if t_ly else '—',
         'dir': 'up' if t_now and t_ly and t_now > t_ly + 0.3 else 'down' if t_now and t_ly and t_now < t_ly - 0.3 else 'mixed', 'why': 'More degree-days' if t_now and t_ly and t_now > t_ly + 0.3 else 'Fewer degree-days' if t_now and t_ly and t_now < t_ly - 0.3 else 'About the same warmth'},
        {'id': 'lice_north', 'label': f'Lice, northern zones 10–12, {win}', 'now': f'{lice_n:.2f}' if lice_n is not None else '—', 'ly': f'{lice_n_ly:.2f}' if lice_n_ly is not None else '—',
         'dir': 'up' if lice_n is not None and lice_n_ly is not None and lice_n < lice_n_ly * 0.85 else 'down' if lice_n is not None and lice_n_ly is not None and lice_n > lice_n_ly * 1.15 else 'mixed',
         'why': 'Fewer forced harvests ahead' if lice_n is not None and lice_n_ly is not None and lice_n < lice_n_ly * 0.85 else 'Risk of forced harvests of small fish' if lice_n is not None and lice_n_ly is not None and lice_n > lice_n_ly * 1.15 else 'Unchanged'},
        {'id': 'lice_mid', 'label': f'Lice, zones 4–7, {win}', 'now': f'{lice_s:.2f}' if lice_s is not None else '—', 'ly': f'{lice_s_ly:.2f}' if lice_s_ly is not None else '—',
         'dir': 'up' if lice_s is not None and lice_s_ly is not None and lice_s < lice_s_ly * 0.85 else 'down' if lice_s is not None and lice_s_ly is not None and lice_s > lice_s_ly * 1.15 else 'mixed',
         'why': 'Fewer treatments, fish kept growing' if lice_s is not None and lice_s_ly is not None and lice_s < lice_s_ly * 0.85 else 'More handling, slower growth' if lice_s is not None and lice_s_ly is not None and lice_s > lice_s_ly * 1.15 else 'Unchanged'},
        {'id': 'tgc', 'label': f'Growth per degree-day (TGC), {win}, G{old}', 'now': f'{tgc["old_3m"]:.2f} ({100 * (tgc["old_3m"] / tgc["old_ly_3m"] - 1):+.0f} %)' if tgc['old_3m'] and tgc['old_ly_3m'] else '—', 'ly': f'{tgc["old_ly_3m"]:.2f}' if tgc['old_ly_3m'] else '—',
         'dir': 'up' if tgc['old_3m'] and tgc['old_ly_3m'] and tgc['old_3m'] > tgc['old_ly_3m'] * 1.03 else 'down' if tgc['old_3m'] and tgc['old_ly_3m'] and tgc['old_3m'] < tgc['old_ly_3m'] * 0.97 else 'mixed',
         'why': ('Out of the historical range' if tgc_norm_now and OH.get('past_range', {}).get('tgc_rel') and tgc_norm_now > OH['past_range']['tgc_rel'][1] else 'Fish grow faster for the same warmth') if tgc['old_3m'] and tgc['old_ly_3m'] and tgc['old_3m'] > tgc['old_ly_3m'] * 1.03 else 'Slower growth'},
        {'id': 'fish', 'label': f'Fish left in G{old}', 'now': f'{o["n"]:.0f} M ({100 * (o["n"] / oly["n"] - 1):+.0f} %)', 'ly': f'{oly["n"]:.0f} M', 'dir': 'mixed', 'why': 'Fewer tonnes to come, more room per fish' if o['n'] < oly['n'] else 'More tonnes to come, less room per fish'},
        {'id': 'pace', 'label': f'Harvest pace, {win} (share of the stock 3 months earlier)', 'now': f'{pace_now:.0f} %' if pace_now else '—', 'ly': f'{pace_ly:.0f} %' if pace_ly else '—',
         'dir': 'down' if pace_now and pace_ly and pace_now > pace_ly + 2 else 'up' if pace_now and pace_ly and pace_now < pace_ly - 2 else 'mixed', 'why': 'Reservoir empties sooner' if pace_now and pace_ly and pace_now > pace_ly + 2 else 'Fish kept longer' if pace_now and pace_ly and pace_now < pace_ly - 2 else 'Same pace'},
        {'id': 'mort', 'label': f'Mortality, {win}, G{old}', 'now': f'{m_now:.1f} %' if m_now is not None else '—', 'ly': f'{m_ly:.1f} %' if m_ly is not None else '—',
         'dir': 'up' if m_now is not None and m_ly is not None and m_now < m_ly - 0.3 else 'down' if m_now is not None and m_ly is not None and m_now > m_ly + 0.3 else 'mixed', 'why': 'Healthy fish, no emergency harvests' if m_now is not None and m_ly is not None and m_now < m_ly - 0.3 else 'Losses force early harvests' if m_now is not None and m_ly is not None and m_now > m_ly + 0.3 else 'Unchanged'}]

    REG0 = collections.defaultdict(float)      # registre complet (zones 0-13), kt vides : les scenarios (cohortes, zones 1-13) sont cales dessus
    for x in D['records']:
        REG0[x['year'] * 100 + x['month']] += (x.get('uttak_kg') or 0) * GUT / 1e6
    vol = {}
    for sc, s in (G.get('scenarios') or {}).items():
        vol[sc] = []
        for m in s['months'][:6]:
            scl = REG0[sh(m['k'], -12)] / m['ly_tot'] if m.get('ly_tot') and REG0.get(sh(m['k'], -12)) else 1.0
            vol[sc].append({'k': m['k'], 'tot': r(m['tot'] * scl, 1), 'ly': r(m['ly_tot'] * scl, 1), 'kt5': r(m['kt5'], 1), 'kt6': r(m['kt6'], 1), 'ly5': r(m['ly5'], 1), 'ly6': r(m['ly6'], 1)})
    NC = G.get('nowcast') or {}
    nc = NC.get('next')
    # le mois deja connu par les exportations remplace le modele (tonnes vives -> vides, comme le reste du panneau)
    if nc:
        for sc in vol.values():
            for m in sc:
                if m['k'] == nc['k']:
                    m['model'], m['tot'], m['known'] = m['tot'], r(nc['t'] * GUT / 1000, 1), True
    # mois suivant en cours : rythme des exportations de poisson entier contre les memes jours un an plus tot,
    # applique au meme mois de l'an dernier (registre) -> controle du modele, affiche a cote de la prevision
    pace = None
    af = NC.get('after')
    if af and af.get('days', 0) >= 7 and vol.get('central'):
        m = next((x for x in vol['central'] if x['k'] == af['k']), None)
        if m and m.get('ly'):
            alt = m['ly'] * (1 + af['yoy'] / 100)
            pace = {'k': af['k'], 'days': af['days'], 'yoy': r(af['yoy'], 1), 'tot': r(alt, 1), 'model': m['tot'], 'model_yoy': r(100 * (m['tot'] / m['ly'] - 1), 1), 'ly': m['ly'],
                    'gap': r(100 * (alt / m['tot'] - 1), 1)}
    # budget de poissons : volume des 6 prochains mois si la generation en recolte est videe au rythme de l'an dernier
    # (poissons restants x avance de poids), la nouvelle generation suit l'an dernier au prorata de sa biomasse, le reste comme l'an dernier
    def harv_kt(gen, k):
        g = gstate(gen, k)
        return g['h'] * (g['hw'] or 0) * GUT if g['h'] else 0.0      # M poissons x kg = kt, vide
    def harv_all_kt(k):
        return sum(((ser.get(k) or {}).get('harv_kg') or 0) for ser in C.values()) * GUT / 1e6
    o, oly, nw, nwly = st['old'], st['old_ly'], st['new'], st['new_ly']
    f_old = (o['n'] / oly['n'] if oly['n'] else 1) * (o['w'] / oly['w'] if oly['w'] and o['w'] else 1)
    f_new = nw['bio'] / nwly['bio'] if nwly['bio'] else 1
    budget = []
    REG = collections.defaultdict(float)      # registre complet (zones 0-13), kt vides, pour caler le budget sur le total publie
    for x in D['records']:
        REG[x['year'] * 100 + x['month']] += (x.get('uttak_kg') or 0) * GUT / 1e6
    for i in range(1, 7):
        k = sh(last, i); kl = sh(k, -12)
        if kl > last:
            break
        ly_old, ly_new, ly_all = harv_kt(old - 1, kl), harv_kt(new - 1, kl), harv_all_kt(kl)
        scale = REG[kl] / ly_all if ly_all and REG.get(kl) else 1.0      # part du registre absente des cohortes (zone 0 surtout)
        ly_old, ly_new, ly_all = ly_old * scale, ly_new * scale, ly_all * scale
        ly_oth = max(0.0, ly_all - ly_old - ly_new)
        go_, gn_ = gstate(old - 1, kl), gstate(new - 1, kl)
        fo_ = go_['h'] * (o['n'] / oly['n'] if oly['n'] else 1)
        fn_ = gn_['h'] * (nw['n'] / nwly['n'] if nwly['n'] else 1)
        f_all = sum(((ser.get(kl) or {}).get('harv_stk') or 0) for ser in C.values()) / 1e6
        budget.append({'k': k, 'tot': r(ly_old * f_old + ly_new * f_new + ly_oth, 1), 'ly': r(ly_all, 1), 'old': r(ly_old * f_old, 1), 'new': r(ly_new * f_new, 1), 'ly_old': r(ly_old, 1), 'ly_new': r(ly_new, 1),
                       'fish': r((fo_ + fn_ + max(0.0, f_all - go_['h'] - gn_['h'])) * scale, 2), 'fish_ly': r(f_all * scale, 2), 'fish_old': r(fo_ * scale, 2), 'fish_new': r(fn_ * scale, 2), 'scale': r(scale, 4)})
    cen = vol.get('central') or []
    recon = []
    for b in budget:
        m = next((x for x in cen if x['k'] == b['k']), None)
        if m:
            recon.append({'k': b['k'], 'lo': r(min(m['tot'], b['tot']), 1), 'hi': r(max(m['tot'], b['tot']), 1), 'mid': r((m['tot'] + b['tot']) / 2, 1), 'ly': b['ly']})
    # budget avec croissance et temperature : memes poissons, meme rythme, mais le poids de recolte suit les degres-jours attendus
    # (temperature normale des 3 dernieres annees + anomalie actuelle amortie de 0,6 par mois ; variante : anomalie maintenue),
    # avec la TGC de la generation precedente au meme mois x l'avance de croissance actuelle gardee a 70 % (comme le scenario central)
    TN = {}
    for (po, km), v in tt.items():
        if v[1]:
            TN.setdefault(km, [0.0, 0.0])
            TN[km][0] += v[0]
            TN[km][1] += v[1]
    TN = {k: v[0] / v[1] for k, v in TN.items() if v[1]}
    def tnorm(k):
        v = [TN[sh(k, -12 * y)] for y in (1, 2, 3) if sh(k, -12 * y) in TN]
        return S.mean(v) if v else None
    t_last = max(k for k in TN if tnorm(k) and k <= sh(last, 1)) if TN else None
    anom = (TN[t_last] - tnorm(t_last)) if t_last else 0.0
    rho = (tgc['old_3m'] / tgc['old_ly_3m']) if tgc.get('old_3m') and tgc.get('old_ly_3m') else 1.0
    rho_eff = 1 + 0.7 * (rho - 1)
    def budget_growth(persist):
        out, adv = [], (o['w'] ** (1 / 3) - oly['w'] ** (1 / 3)) if o['w'] and oly['w'] else 0.0
        for i in range(1, 7):
            k = sh(last, i); kl = sh(k, -12)
            if kl > last:
                break
            nrm, tly, g = tnorm(k), TN.get(kl), tgc_month(old - 1, kl)
            if nrm is None or tly is None or not g:
                return None
            steps = max(0, i - (t_last - last) if t_last else i)
            tj = nrm + anom * (1.0 if persist else 0.6 ** steps)
            adv += g * days(k) * (rho_eff * tj - tly) / 10000
            gl = gstate(old - 1, kl)
            if not gl['w'] or not gl['hw']:
                return None
            wproj = max(0.5, gl['w'] ** (1 / 3) + adv) ** 3
            hw = gl['hw'] * wproj / gl['w']
            fish = gl['h'] * (o['n'] / oly['n'] if oly['n'] else 1)      # poissons recoltes l'an dernier ce mois-la, au prorata du stock restant
            b0 = next((b for b in budget if b['k'] == k), None)
            if not b0:
                break
            fish *= b0.get('scale', 1.0)
            out.append({'k': k, 'tot': r(fish * hw * GUT + b0['new'] + max(0.0, b0['ly'] - b0['ly_old'] - b0['ly_new']), 1), 'ly': b0['ly'], 'old': r(fish * hw * GUT, 1), 'new': b0['new'], 'hw': r(hw, 2), 'hw_ly': r(gl['hw'], 2), 'w': r(wproj, 2), 'w_ly': r(gl['w'], 2), 't': r(tj, 1), 't_ly': r(tly, 1)})
        return out
    budget_dd_nat, budget_dd_nat_persist = budget_growth(False), budget_growth(True)
    # meme budget, zone par zone : poissons, poids, TGC, temperature normale et anomalie propres a chaque zone de production
    # (une zone sans temperature ou sans TGC l'an dernier retombe sur les valeurs nationales)
    def tnorm_z(po, k):
        v = [T[(po, sh(k, -12 * y))] for y in (1, 2, 3) if (po, sh(k, -12 * y)) in T]
        return S.mean(v) if v else None
    zone_watch = []
    def budget_zones(persist):
        zones = sorted({po for (po, gg) in C})
        tot = collections.defaultdict(float)
        fishz = collections.defaultdict(float)
        covered = collections.defaultdict(float)      # recolte de l'an dernier des zones traitees, pour completer les zones absentes au facteur national
        detail = {}
        for po in zones:
            a, b = C.get((po, old), {}).get(last), C.get((po, old - 1), {}).get(sh(last, -12))
            if not a or not b or not a['stock'] or not b['stock'] or a['stock'] < 2e5:
                continue
            n_ratio = a['stock'] / b['stock']
            adv = a['weight_kg'] ** (1 / 3) - b['weight_kg'] ** (1 / 3)
            g_now, g_ly = tgc_win(old, L3, po), tgc_win(old - 1, L3y, po)
            rho_z = min(1.5, max(0.7, g_now / g_ly)) if g_now and g_ly else rho
            rho_zeff = 1 + 0.7 * (rho_z - 1)
            tl = t_last if (po, t_last) in T and tnorm_z(po, t_last) else None
            an_z = (T[(po, tl)] - tnorm_z(po, tl)) if tl else anom
            vol = {}
            for i in range(1, 7):
                k = sh(last, i); kl = sh(k, -12)
                cl = C.get((po, old - 1), {}).get(kl)
                if kl > last or not cl:
                    break
                nrm, tly, g = tnorm_z(po, k), T.get((po, kl)), tgc_month(old - 1, kl, po)
                if nrm is None or tly is None:
                    nrm, tly = tnorm(k), TN.get(kl)
                if not g:
                    g = tgc_month(old - 1, kl)
                if nrm is None or tly is None or not g:
                    return None, None
                steps = max(0, i - (t_last - last) if t_last else i)
                tj = nrm + an_z * (1.0 if persist else 0.6 ** steps)
                adv += g * days(k) * (rho_zeff * tj - tly) / 10000
                if not cl['stock'] or not cl['weight_kg']:
                    vol[k] = 0.0
                    continue
                wproj = max(0.3, cl['weight_kg'] ** (1 / 3) + adv) ** 3
                hw_ly = (cl['harv_kg'] / cl['harv_stk']) if cl.get('harv_stk') and cl.get('harv_kg') else cl['weight_kg'] * 1.15
                hw = hw_ly * wproj / cl['weight_kg']
                fish = (cl.get('harv_stk') or 0) * n_ratio / 1e6
                vol[k] = fish * hw * GUT
                tot[k] += vol[k]
                fishz[k] += fish
                covered[k] += (cl.get('harv_kg') or 0) * GUT / 1e6
            if not persist:
                detail[po] = {'n': r(a['stock'] / 1e6, 1), 'n_ly': r(b['stock'] / 1e6, 1), 'w': r(a['weight_kg']), 'w_ly': r(b['weight_kg']), 'tgc': g_now, 'tgc_ly': g_ly, 'rho': r(rho_z, 2), 'anom': r(an_z, 2),
                              'vol3': r(sum(v for kk, v in vol.items() if kk <= sh(last, 3)), 1), 'vol3_ly': r(sum((C.get((po, old - 1), {}).get(sh(kk, -12)) or {}).get('harv_kg', 0) or 0 for kk in vol if kk <= sh(last, 3)) * GUT / 1e6, 1)}
        out = []
        for b0 in budget:
            if b0['k'] not in tot:
                break
            sc_ = b0.get('scale', 1.0)
            rest = max(0.0, b0['ly_old'] - covered[b0['k']] * sc_) * f_old
            out.append({'k': b0['k'], 'tot': r(tot[b0['k']] * sc_ + rest + b0['new'] + max(0.0, b0['ly'] - b0['ly_old'] - b0['ly_new']), 1), 'ly': b0['ly'], 'old': r(tot[b0['k']] * sc_ + rest, 1), 'new': b0['new'],
                        'fish': r(fishz[b0['k']] * sc_ + (b0['fish'] - b0['fish_old']), 2), 'fish_ly': b0['fish_ly'], 'hw': r(tot[b0['k']] / GUT / fishz[b0['k']], 2) if fishz[b0['k']] else None})
        return out, detail
    budget_dd, zone_detail = budget_zones(False)
    budget_dd_persist, _ = budget_zones(True)
    if not budget_dd or len(budget_dd) < 6:
        budget_dd, budget_dd_persist, zone_detail = budget_dd_nat, budget_dd_nat_persist, None
    # suivi de la TGC et des degres-jours par zone : depuis le registre, semaines BarentsWatch (temperature x 7 jours) contre les memes semaines l'an dernier
    wk_last = max((y, w) for (po, y, w) in tw) if tw else None
    def dd_since(po, y0):
        tot_dd = n = 0.0
        for (p2, y, w), v in tw.items():
            if p2 != po or not v[1]:
                continue
            th = dt.date.fromisocalendar(y, w, 4)
            km = th.year * 100 + th.month
            if km > (last if y0 == 0 else sh(last, -12)) and (y, w) <= ((wk_last[0] - y0, wk_last[1]) if wk_last else (0, 0)):
                tot_dd += 7 * v[0] / v[1]
                n += 1
        return tot_dd, n
    tgc_watch = []
    for po, d in sorted((zone_detail or {}).items()):
        dd_now, wn = dd_since(po, 0)
        dd_ly, wl = dd_since(po, 1)
        g_norm = [tgc_win(old - 1 - y, [sh(k, -12 * y) for k in L3y], po) for y in (0, 1, 2)]
        g_norm = r(S.mean([x for x in g_norm if x])) if any(g_norm) else None
        nw = min(wn, wl)      # meme nombre de semaines des deux cotes (une semaine peut manquer dans une zone)
        tgc_watch.append({'po': po, **d, 'tgc_norm': g_norm, 'dd_since': r(dd_now / wn * nw, 0) if wn and wl else None, 'dd_since_ly': r(dd_ly / wl * nw, 0) if wn and wl else None, 'weeks': int(nw)})
    tgc_watch_meta = {'since': sh(last, 1), 'to_week': f'{wk_last[0]}-W{wk_last[1]:02d}' if wk_last else None, 'window': win}
    growth_note = (f"growth budget: same fish and pace, harvest weight follows expected degree-days — temperature normal of the last 3 years "
                   f"{'+ ' if anom >= 0 else '− '}{abs(anom):.1f} °C anomaly of {MON[t_last % 100 - 1] if t_last else '?'} fading by 0.6 a month (or kept), "
                   f"TGC of G{old - 1} at the same month × {rho_eff:.2f} (G{old}'s advance {rho:.2f}, kept at 70 %)") if t_last else None
    # periodes : 3 prochains mois et les 3 suivants ; si les 3 prochains mois suivent le modele (confirme par les exports), ce qui reste du
    # budget de 6 mois dit ce que les 3 suivants peuvent donner
    def psum(A, a, b, key='tot'):
        return sum(x[key] for x in A[a:b])
    periods = None
    if len(budget) >= 6 and len(cen) >= 6:
        q1m, q2m = psum(cen, 0, 3), psum(cen, 3, 6)
        q1b, q2b = psum(budget, 0, 3), psum(budget, 3, 6)
        q1l, q2l = psum(budget, 0, 3, 'ly'), psum(budget, 3, 6, 'ly')
        periods = {'p1': {'span': f"{MON[budget[0]['k'] % 100 - 1]}–{MON[budget[2]['k'] % 100 - 1]} {budget[2]['k'] // 100}", 'model': r(q1m, 1), 'budget': r(q1b, 1), 'ly': r(q1l, 1)},
                   'p2': {'span': f"{MON[budget[3]['k'] % 100 - 1]}–{MON[budget[5]['k'] % 100 - 1]} {budget[5]['k'] // 100}", 'model': r(q2m, 1), 'budget': r(q2b, 1), 'ly': r(q2l, 1), 'implied': r(q1b + q2b - q1m, 1)},
                   'verdict': ('brought_forward' if q1m > q1b * 1.02 else 'held_back' if q1m < q1b * 0.98 else 'in_line')}
        for key, B in (('dd', budget_dd), ('dd_persist', budget_dd_persist)):
            if B and len(B) >= 6:
                a, b = psum(B, 0, 3), psum(B, 3, 6)
                periods['p1'][key] = r(a, 1)
                periods['p2'][key] = r(b, 1)
                periods['p2']['implied_' + key] = r(a + b - q1m, 1)
    budget_note = (f"fish budget: G{old} emptied at G{old - 1}'s pace of last year ({o['n']:.0f} M fish left against {oly['n']:.0f} M, x{f_old:.3f} with the weight advance), "
                   f"G{new} follows G{new - 1} in proportion to its biomass (x{f_new:.3f}), older fish as last year; no growth or temperature effect")
    out = {'meta': {'generated': dt.date.today().isoformat(), 'register': last, 'register_label': f'{MON[last % 100 - 1]} {last // 100}', 'old': old, 'new': new, 'window': win},
           'state': {k: {x: r(v, 3) for x, v in d.items()} for k, d in st.items()}, 'traj': TR, 'tgc': tgc, 'mort': mort,
           'depletion': {'proj': dep, 'ly': [[sh(sh(last, -12), i), r(v, 1)] for i, v in enumerate(dep_ly)], 'end20': end20, 'end05': end05},
           'handover': {'prev2': season_prev2, 'prev': season_prev, 'cur': proj, 'k50': hand50, 'k50_prev': hand50_prev, 'k50_prev2': hand50_prev2},
           'smolt': {str(g): v for g, v in SM.items()}, 'zones': Z, 'factors': factors,
           'volume': {'scenarios': vol, 'budget': budget, 'budget_f': {'old': r(f_old, 3), 'new': r(f_new, 3)}, 'budget_note': budget_note, 'reconciled': recon, 'budget_dd': budget_dd, 'budget_dd_persist': budget_dd_persist, 'growth': {'anomaly_c': r(anom, 2), 'anomaly_month': t_last, 'tgc_ratio': r(rho, 3), 'tgc_ratio_used': r(rho_eff, 3), 'note': growth_note, 'by_zone': zone_detail is not None, 'national': {'dd': budget_dd_nat, 'dd_persist': budget_dd_nat_persist}}, 'tgc_watch': tgc_watch, 'tgc_watch_meta': tgc_watch_meta, 'periods': periods, 'nowcast': {'k': nc['k'], 't': r(nc['t'] * GUT / 1000, 1), 'ly': r(nc['ly'] * GUT / 1000, 1)} if nc else None, 'pace': pace, 'tested': 'Replayed since Jan 2021: 3.4 % average error on the next 5 months; Q4 forecasts made each November missed by 7–11 points in 2022–2025'},
           'six': {'forecast': SIX.get('forecast'), 'alerts': SIX.get('alerts'), 'tests': {k: {x: v.get(x) for x in ('mape', 'mape_fixed4', 'naive_mape', 'inside_range')} for k, v in (SIX.get('tests') or {}).items()}}}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    # ---- journal des previsions figees : une entree par registre, ecrite une seule fois (jamais reecrite), pour comparer
    # plus tard prevision et realite ; le controle au rythme des exportations est note a chaque nouvelle semaine SSB
    AP = os.path.join(ROOT, 'data', 'generations_archive.json')
    AR = D_('generations_archive.json') or {'note': 'Harvest outlook (onglet Generations) fige a chaque registre : volumes par scenario (kt vides), 6 kg+, dates de fin de generation et de relais ; pace = controle au rythme des exportations SSB, une ligne par nombre de jours connus. Les entrees ne sont jamais reecrites.', 'entries': {}}
    key = str(out['meta']['register'])
    V_ = out['volume']
    if key not in AR['entries']:
        AR['entries'][key] = {'made': out['meta']['generated'], 'register': out['meta']['register'],
                              'scenarios': {sc: [{'k': m['k'], 'tot': m.get('model', m['tot']), 'ly': m['ly'], 'kt5': m['kt5'], 'ly5': m['ly5'], 'kt6': m['kt6'], 'ly6': m['ly6']} for m in ms] for sc, ms in (V_.get('scenarios') or {}).items()},
                              'budget': [{'k': b['k'], 'tot': b['tot'], 'ly': b['ly']} for b in (V_.get('budget') or [])],
                              'six': [{x: f_.get(x) for x in ('span', 'fcst', 'lo', 'hi', 'ly')} for f_ in ((out.get('six') or {}).get('forecast') or [])],
                              'end20': (out.get('depletion') or {}).get('end20'), 'handover50': (out.get('handover') or {}).get('k50'),
                              'state': {g: {x: r(st[g].get(x), 3) for x in ('n', 'w', 'bio', 'b5')} for g in ('old', 'new')}, 'nowcast': [], 'pace': []}
    E = AR['entries'][key]
    if V_.get('nowcast') and not any(x['k'] == V_['nowcast']['k'] for x in E['nowcast']):
        E['nowcast'].append(dict(V_['nowcast'], made=out['meta']['generated']))
    if V_.get('pace') and not any(x['k'] == V_['pace']['k'] and x['days'] == V_['pace']['days'] for x in E['pace']):
        E['pace'].append(dict(V_['pace'], made=out['meta']['generated']))
    io.open(AP, 'w', encoding='utf-8').write(json.dumps(AR, ensure_ascii=False, indent=1))
    print(f"generations.json : registre {out['meta']['register_label']}, G{old} en recolte ({st['old']['n']:.1f} M, {st['old']['w']:.2f} kg), G{new} suivante ({st['new']['n']:.1f} M, {st['new']['w']:.2f} kg) ; fin 20 % {end20}, relais 50 % {hand50} (saison passee {hand50_prev})")
    for f in factors:
        print(f"  {f['dir']:5s} {f['label']}: {f['now']} vs {f['ly']} — {f['why']}")


if __name__ == '__main__':
    main()
