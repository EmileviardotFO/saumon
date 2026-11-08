#!/usr/bin/env python3
"""
Summary « What matters this week » : les signaux importants de tous les bassins, classes, et le tableau de bord d'ensemble.

    python3 scripts/build_summary.py      -> data/summary.json   (lu par l'onglet Summary de docs/production.html)

Tout est calcule a partir des fichiers deja collectes (aucun appel exterieur, aucune API payante). Chaque signal porte :
  - sa valeur, sa comparaison (un an plus tot, normale) et le texte d'explication ;
  - un score = ecart a la normale de la serie / variation habituelle de cette serie (plus le score est haut, plus c'est inhabituel),
    ou un score fixe quand la serie est trop courte pour mesurer sa variation habituelle ;
  - l'effet attendu sur les prix (supports / weighs / risk / watch) et l'onglet ou lire le detail.
Les chiffres absents (fichier manquant, serie pas encore publiee) font simplement disparaitre le signal.
"""
import collections
import datetime as dt
import io
import json
import os
import statistics as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda n: os.path.join(ROOT, 'data', n)
OUT = D('summary.json')
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def lire(n):
    try:
        return json.load(io.open(D(n), encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None


def pct(a, b):
    return 100 * (a / b - 1) if b else None


def sg(v, d=1, u=' %'):
    return ('+' if v > 0 else '−' if v < 0 else '±') + f'{abs(v):.{d}f}{u}'


def ml(k):
    return f'{MON[k % 100 - 1]} {k // 100}'


def z(v, hist):
    """Ecart rapporte a la variation habituelle de la serie (ecart-type de ses variations passees)."""
    h = [x for x in hist if x is not None]
    if len(h) < 6: return None
    sd = S.pstdev(h) or 1e-9
    return abs(v - S.mean(h)) / sd


def main():
    sig, notes = [], []
    d = lire('data.json') or {}
    # ---------------- Norvege : recolte sur 12 mois, poids ----------------
    m = collections.defaultdict(lambda: [0.0, 0.0])
    for r in d.get('records') or []:
        k = r['year'] * 100 + r['month']; m[k][0] += r.get('uttak_kg') or 0; m[k][1] += r.get('uttak_stk') or 0
    ks = sorted(m)
    if len(ks) >= 36:
        def s12(i): K = ks[i - 11:i + 1]; return sum(m[k][0] for k in K), sum(m[k][1] for k in K)
        i = len(ks) - 1; h, c = s12(i); h0, c0 = s12(i - 12)
        yoy = [pct(s12(j)[0], s12(j - 12)[0]) for j in range(23, i)]
        ch = pct(h, h0); w, w0 = h / c, h0 / c0
        rec = h >= max(s12(j)[0] for j in range(11, i))
        sig.append({'basin': 'Norway', 'title': ('Record harvest' if rec else 'Harvest') + (', heavier fish' if w > w0 + .1 else ''), 'value': f'{h / 1e6:,.0f} kt',
                    'text': f'live weight over the 12 months to {ml(ks[i])} ({sg(ch)}); harvest weight {w:.2f} kg ({w0:.2f} a year earlier).',
                    'effect': 'weighs', 'tab': 'outlook', 'score': (z(ch, yoy) or 1) + (1 if rec else 0)})
    # exportations hebdomadaires et prix (SSB)
    fr = {r[0]: (r[2], r[3]) for r in ((d.get('ssb_weekly') or {}).get('rows') or []) if r[1] == 0}
    if fr:
        lw = max(fr); y, wk = divmod(lw, 100)
        p, p0 = fr[lw][1], (fr.get(lw - 100) or (None, None))[1]
        v = sum(x[0] for k, x in fr.items() if k // 100 == y and k % 100 <= wk); v0 = sum(x[0] for k, x in fr.items() if k // 100 == y - 1 and k % 100 <= wk)
        if p0:
            ch = pct(p, p0); hist = [pct(fr[k][1], fr[k - 100][1]) for k in fr if k - 100 in fr]
            sig.append({'basin': 'Market', 'title': f'Norwegian export price {"below" if ch < 0 else "above"} last year', 'value': f'{p:.1f} NOK/kg',
                        'text': f'fresh salmon, week {wk} ({p0:.1f} a year earlier, {sg(ch, 0)}); export volume since January {sg(pct(v, v0), 0)}.',
                        'effect': 'price', 'tab': 'prices', 'score': z(ch, hist) or 1})
    # gros poissons norvegiens (prevision du mois, recalee par les bateaux de recolte)
    bf = lire('big_fish.json') or {}
    N = ((bf.get('ranking') or {}).get('norway') or [])
    if N:
        x = N[0]; dd = x['share6'] - x['ly_share6']
        nc = ((bf['ranking'].get('nowcast') or {}).get(str(x['month'])) or {})
        top = sorted([(po, z_) for po, z_ in nc.items() if z_.get('share6_blend') is not None and z_.get('share6_G') is not None and abs(z_['share6_blend'] - z_['share6_G']) >= 3],
                     key=lambda t: -abs(t[1]['share6_blend'] - t[1]['share6_G']))[:2]
        fm = [f for f in (bf['ranking'].get('farmers') or []) if f.get('co') == 'Nordlaks']
        sig.append({'basin': 'Norway', 'title': f'{"More" if dd > 0 else "Fewer"} 6 kg+ than last year in {MON[x["month"] % 100 - 1]}', 'value': f'{x["share6"]:.1f} %',
                    'text': f'of the harvest in 6 kg+ ({x["ly_share6"]:.1f} % a year earlier), adjusted with harvest-boat visits' +
                            (': ' + ', '.join(f'zone {po} {z_["share6_G"]:.0f} → {z_["share6_blend"]:.0f} %' for po, z_ in top) if top else '') + '.',
                    'effect': 'weighs' if dd > 0 else 'supports', 'tab': 'genmap', 'score': 1 + abs(dd) / 2})
    # ---------------- Chili ----------------
    cc = lire('chile_customs.json') or {}
    CM = cc.get('months') or {}
    def g6(k):
        t = h6 = 0
        for f in ('atlantic|fresh whole', 'atlantic|frozen whole'):
            zz = ((CM.get(k) or {}).get('sizes') or {}).get(f)
            if zz and zz.get('hist_t'): t += sum(zz['hist_t']); h6 += sum(zz['hist_t'][5:])
        return 100 * h6 / t if t else None
    mk = sorted(CM)
    if len(mk) >= 15:
        L = [(k, g6(k), g6(str(int(k) - 100))) for k in mk[-6:]]
        L = [x for x in L if x[1] is not None and x[2] is not None]
        if L:
            ds = [a - b for _, a, b in L]; neg = sum(1 for x in ds if x < 0)
            hist = [g6(k) - g6(str(int(k) - 100)) for k in mk if g6(k) is not None and g6(str(int(k) - 100)) is not None]
            fob = []
            for k in mk[-3:]:
                for cl in ('5', '6'):
                    for f in ('fresh whole', 'frozen whole'):
                        for v in (((CM[k].get('size_dest') or {}).get(f'{f}|{cl}')) or {}).values(): fob.append(v)
            fob0 = []
            for k in [str(int(k) - 100) for k in mk[-3:]]:
                for cl in ('5', '6'):
                    for f in ('fresh whole', 'frozen whole'):
                        for v in ((((CM.get(k) or {}).get('size_dest') or {}).get(f'{f}|{cl}')) or {}).values(): fob0.append(v)
            pr = sum(v[1] for v in fob) / sum(v[0] for v in fob) if fob and sum(v[0] for v in fob) else None
            pr0 = sum(v[1] for v in fob0) / sum(v[0] for v in fob0) if fob0 and sum(v[0] for v in fob0) else None
            sig.append({'basin': 'Chile', 'title': f'{"Fewer" if neg >= len(ds) / 2 else "More"} big fish exported in the last {len(L)} months',
                        'value': f'{min(ds):+.0f} to {max(ds):+.0f} pt'.replace('+-', '−').replace('-', '−'),
                        'text': f'share of 6 kg+ in whole Atlantic exports vs a year earlier ({ml(int(L[-1][0]))}: {L[-1][1]:.0f} % vs {L[-1][2]:.0f} %).' +
                                (f' FOB price of 6 kg+ {sg(pct(pr, pr0), 0)} over the last 3 months ({pr:.2f} $/kg).' if pr and pr0 else ''),
                        'effect': 'supports' if neg >= len(ds) / 2 else 'weighs', 'tab': 'chile', 'score': (z(S.mean(ds), hist) or 1) + 0.5})
    sp = lire('chile_subpesca.json') or {}
    R = sorted([r for r in sp.get('reports') or [] if r.get('k') and not r.get('unread') and (r.get('species') or {}).get('salar')], key=lambda r: r['k'])
    if len(R) >= 4:
        def mois(i):
            a, b = R[i], R[i - 1]
            if a['k'] // 100 != b['k'] // 100 or a['k'] - b['k'] != 1: return None
            c1, c0 = a['species']['salar']['cum_kt'], b['species']['salar']['cum_kt']; v1, v0 = a['species']['salar']['var_pct'], b['species']['salar']['var_pct']
            ly1, ly0 = c1 / (1 + v1 / 100), c0 / (1 + v0 / 100)
            return pct(c1 - c0, ly1 - ly0)
        mm = [(R[i]['k'], mois(i)) for i in range(len(R) - 3, len(R))]
        mm = [x for x in mm if x[1] is not None]
        last = R[-1]['species']['salar']
        if mm:
            sig.append({'basin': 'Chile', 'title': 'Atlantic harvest slowing' if S.mean([x[1] for x in mm]) < last['var_pct'] else 'Atlantic harvest',
                        'value': sg(last['var_pct']), 'text': f'Jan–{MON[R[-1]["k"] % 100 - 1]} on a year earlier, but month by month: ' + ', '.join(f'{MON[k % 100 - 1]} {sg(v, 0)}' for k, v in mm) + '.',
                        'effect': 'supports' if S.mean([x[1] for x in mm]) < 0 else 'weighs', 'tab': 'chile', 'score': 1 + abs(S.mean([x[1] for x in mm]) - last['var_pct']) / 4})
    cal = lire('chile_caligus.json') or {}
    q = collections.Counter()
    for e in cal.get('entries') or []:
        try:
            y, w = e['week'].split('-W'); dd_ = dt.date.fromisocalendar(int(y), int(w), 4); q[f'{dd_.year}Q{(dd_.month - 1) // 3 + 1}'] += 1
        except Exception:  # noqa: BLE001
            pass
    full = sorted(k for k in q if k < f'{dt.date.today().year}Q{(dt.date.today().month - 1) // 3 + 1}')
    if len(full) >= 4:
        lq = full[-1]; oth = [q[k] for k in full[:-1]]
        if q[lq] > max(oth):
            sig.append({'basin': 'Chile', 'title': 'Sea lice at a high', 'value': f'{q[lq]} farms', 'text': f'listed as high-dissemination sites in {lq[:4]} Q{lq[-1]} ({min(oth)} to {max(oth)} in the other quarters since {full[0][:4]}).',
                        'effect': 'supports', 'tab': 'chile', 'score': 1 + (q[lq] - max(oth)) / max(1, S.pstdev(oth) or 1)})
    # ---------------- mer, El Niño, chlorophylle ----------------
    st = lire('sea_temp.json') or {}
    P = st.get('points') or []
    lastm = max((max(p['monthly']) for p in P if p.get('monthly')), default=None)
    rng = lambda b: [p['anomaly'].get(lastm) for p in P if p['basin'] == b and p.get('anomaly', {}).get(lastm) is not None]
    en = st.get('enso') or {}; W = en.get('weekly_nino34') or []
    if W:
        a = W[-1][2]; cl = rng('CL')
        sig.append({'basin': 'Chile · El Niño', 'title': ('Extreme El Niño' if a >= 2 else 'El Niño' if a >= .5 else 'La Niña' if a <= -.5 else 'Neutral Pacific') + (', warm Chilean water' if cl and max(cl) >= 1 else ''),
                    'value': sg(a, 1, ' °C'), 'text': f'Niño 3.4 index (week of {W[-1][0]})' + (f'; Chilean sea {sg(min(cl), 1, "")} to {sg(max(cl), 1, " °C")} vs normal in {MON[int(lastm[5:]) - 1]}' if cl else '') +
                    (f'. NOAA: {en["synopsis"]}' if en.get('synopsis') else '.'), 'effect': 'risk', 'tab': 'seatemp', 'score': abs(a) * 1.3})
    chl = lire('chlorophyll.json') or {}
    for p in sorted(chl.get('points') or [], key=lambda p: -(p.get('anom_pct') or 0))[:1]:
        if (p.get('anom_pct') or 0) >= 30:
            sig.append({'basin': p.get('basin_name', p.get('basin')), 'title': 'Unusually high chlorophyll (algae) in the water', 'value': sg(p['anom_pct'], 0),
                        'text': f'{p["label"]}: satellite chlorophyll, {p.get("period", "last 8 days")}, vs the same weeks of past years. Algae biomass, not toxicity: a sign to watch for blooms, not a bloom.',
                        'effect': 'risk', 'tab': 'seatemp', 'score': 1 + p['anom_pct'] / 40})
    # ---------------- sujets suivis (watch.json) ----------------
    today = dt.date.today().isoformat()
    for t in ((lire('watch.json') or {}).get('topics') or []):
        if t.get('until', '9999') >= today:
            sig.append({'basin': {'AU': 'Tasmania', 'CL': 'Chile', 'NO': 'Norway', 'GB': 'Scotland'}.get(t.get('basin'), t.get('basin')), 'title': t['label'].split('·')[-1].strip().capitalize() + ': decision pending',
                        'value': '', 'text': t.get('status', ''), 'effect': 'watch', 'tab': {'AU': 'australia', 'CL': 'chile'}.get(t.get('basin'), 'news'), 'score': 1.2})
    sig.sort(key=lambda s: -s['score'])
    for s in sig: s['score'] = round(s['score'], 2)
    # ---------------- producteurs et consommateurs ----------------
    own = (lire('own_supply.json') or {}).get('basins') or {}
    NAME = {'NO': 'Norway', 'CL': 'Chile', 'GB': 'Scotland', 'FO': 'Faroe Islands', 'IS': 'Iceland', 'CA': 'Canada', 'AU': 'Tasmania'}
    sup = {}
    if own:
        a = sum(v['e2026'] for v in own.values()); b = sum(v['v2025'] for v in own.values()); c = sum(v['c2027'] for v in own.values())
        sup = {'world': round(pct(a, b), 1), 'world_next': round(pct(c, a), 1), 'world_kt': round(a), 'basins': [[NAME.get(k, k), v['chg2026']] for k, v in sorted(own.items(), key=lambda kv: -kv[1]['chg2026'])]}
    wi = (lire('world_imports.json') or {}).get('rows') or []
    H = {'030214', '030441', '030313', '030481'}
    EU = set('POL FRA DEU ESP ITA NLD DNK SWE BEL PRT LTU FIN AUT CZE GRC IRL LVA EST SVK SVN HRV ROU BGR HUN LUX'.split())
    NM = {'EU': 'EU', 'USA': 'USA', 'BRA': 'Brazil', 'GBR': 'UK', 'JPN': 'Japan', 'CAN': 'Canada', 'MEX': 'Mexico', 'THA': 'Thailand', 'ISR': 'Israel', 'CHE': 'Switzerland', 'HKG': 'Hong Kong'}
    R_ = collections.defaultdict(lambda: collections.defaultdict(float))
    for ym, rep, hs, p_, kg, usd in wi:
        if hs in H and p_ == 'W': R_[rep][ym] += kg
    agg = collections.defaultdict(lambda: [0.0, 0.0]); lastmo = 0
    for rep, mm_ in R_.items():
        l = max((ym for ym in mm_ if ym // 100 == dt.date.today().year), default=None)
        if not l: continue
        a = sum(v for ym, v in mm_.items() if ym // 100 == l // 100 and ym % 100 <= l % 100); b = sum(v for ym, v in mm_.items() if ym // 100 == l // 100 - 1 and ym % 100 <= l % 100)
        if b < 1e6: continue
        g = 'EU' if rep in EU else rep; agg[g][0] += a; agg[g][1] += b; lastmo = max(lastmo, l)
    dem = {}
    if agg:
        T = [sum(x[0] for x in agg.values()), sum(x[1] for x in agg.values())]
        dem = {'world': round(pct(*T), 1), 'to': lastmo, 'markets': sorted([[NM.get(g, g), round(pct(*x), 1)] for g, x in sorted(agg.items(), key=lambda kv: -kv[1][0])[:8] if x[0] >= 8e6], key=lambda m_: -m_[1])}
    # ---------------- tableau par bassin ----------------
    B = []
    for k, n in NAME.items():
        v = own.get(k) or {}; r = rng(k) or ([] if k != 'GB' else [])
        if k == 'GB': r = rng('GB') + rng('IE')
        B.append({'basin': n, 'v2026': v.get('e2026'), 'chg2026': v.get('chg2026'), 'chg2027': v.get('chg2027'), 'lo': v.get('lo'), 'hi': v.get('hi'),
                  'sea': [round(min(r), 1), round(max(r), 1)] if r else None, 'tab': v.get('tab')})
    # ---------------- agenda ----------------
    t = dt.date.today(); nxt = (t.replace(day=20) if t.day <= 20 else (t.replace(day=1) + dt.timedelta(days=32)).replace(day=20))
    ag = [{'d': nxt.isoformat(), 't': f'Norwegian biomass register for {MON[(nxt.month - 2) % 12]} (around the 20th)'}]
    for x in ((lire('summary_manual.json') or {}).get('agenda') or []):
        if x.get('until', x.get('d', '9999')) >= today: ag.append(x)
    ag.sort(key=lambda x: x['d'])
    # ---------------- texte d'ouverture ----------------
    lead = []
    if sup: lead.append(f'Supply grows {sg(sup["world"], 0)} in 2026 across the seven basins and {sg(sup["world_next"], 1)} in 2027.')
    SHORT = {'Extreme El Niño': 'a record El Niño', 'Sea lice at a high': 'sea lice at a high', 'Atlantic harvest slowing': 'a slowing harvest', 'Fewer big fish': 'fewer big fish', 'warm Chilean water': 'warm water'}
    cls = [next((v for k_, v in SHORT.items() if s['title'].startswith(k_)), None) for s in sig if s['basin'].startswith('Chile')]
    cls = [c for c in cls if c]
    if cls: lead.append('Chile is the main source of change: ' + (', '.join(cls[:-1]) + ' and ' + cls[-1] if len(cls) > 1 else cls[0]) + '.')
    no = [s for s in sig if s['basin'] == 'Norway']
    if no: lead.append('Norway carries the growth' + (' with heavier fish and more 6 kg+.' if any('6 kg+' in s['title'] and s['title'].startswith('More') for s in no) else '.'))
    if dem and dem.get('markets'):
        fast = [n for n, v in sorted(dem['markets'], key=lambda x: -x[1]) if v > dem['world']][:3]; slow = [n for n, v in dem['markets'] if v < 2][:2]
        lead.append(f'Imports grow fastest in {", ".join(fast)}' + (f'; {" and ".join(slow)} {"is" if len(slow) == 1 else "are"} flat or down.' if slow else '.'))
    out = {'meta': {'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'), 'note': 'Signals ranked by how unusual they are against their own history (score). Effect: supports / weighs on prices, risk, watch.'},
           'lead': ' '.join(lead), 'signals': sig[:9], 'supply': sup, 'demand': dem, 'basins': B, 'agenda': ag[:8]}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, indent=1))
    print(f'data/summary.json : {len(sig)} signaux ;', ' | '.join(f'{s["basin"]}: {s["title"]} ({s["score"]})' for s in sig[:9]))


if __name__ == '__main__':
    main()
