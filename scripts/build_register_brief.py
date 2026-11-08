#!/usr/bin/env python3
"""
Brief shown at the top of the News page for 7 days after each new month of the Directorate of Fisheries' biomass register.

    python3 scripts/build_register_brief.py        -> data/register_brief.json

Runs every day after the register step: it only writes a new brief when the register has a new month. Every line is
computed from the dashboard's own data (data.json, big_fish.json); nothing is written by hand, no paid call.
The size forecast of the previous brief is kept, so the new brief says whether the forecast was revised up or down.
"""
import datetime as dt
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
BIG = os.path.join(ROOT, 'data', 'big_fish.json')
OUT = os.path.join(ROOT, 'data', 'register_brief.json')
GUT = 0.888
MOIS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
ml = lambda k: f'{MOIS[k % 100 - 1]} {k // 100}'
pc = lambda a, b: 100 * (a / b - 1) if b else None
sg = lambda v, d=None: ('+' if v >= 0 else '−') + f'{abs(v):.{(1 if abs(v) < 0.95 else 0) if d is None else d}f}'   # une decimale sous 1 % (pas de « −0 % »)


def main():
    d = json.load(io.open(DATA, encoding='utf-8'))
    C = d.get('cohort', [])                          # toutes les licences, comme le resume de Generations map
    if not C: return print('no register data')
    k = max(c['year'] * 100 + c['month'] for c in C); y, m = divmod(k, 100)
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    if ancien.get('month') == k:
        return print(f'register_brief : {ml(k)} already briefed on {ancien.get("published")}')
    M = lambda yy, mm: [c for c in C if c['year'] == yy and c['month'] == mm]
    cur, ly = M(y, m), M(y - 1, m)
    sum_ = lambda L, f: sum(f(c) or 0 for c in L)
    lines = []
    # 1) recolte et biomasse
    h, hl = sum_(cur, lambda c: c['harv_kg']) * GUT / 1e6, sum_(ly, lambda c: c['harv_kg']) * GUT / 1e6
    hw = sum_(cur, lambda c: c['harv_kg']) / (sum_(cur, lambda c: c['harv_stk']) or 1) * GUT
    hwl = sum_(ly, lambda c: c['harv_kg']) / (sum_(ly, lambda c: c['harv_stk']) or 1) * GUT
    b, bl = sum_(cur, lambda c: (c['stock'] or 0) * (c['weight_kg'] or 0)) * GUT / 1e6, sum_(ly, lambda c: (c['stock'] or 0) * (c['weight_kg'] or 0)) * GUT / 1e6
    # meme base que la page (Generations map, Registre) : toutes les licences en mer, zone 0 comprise, puisque la biomasse b comprend la zone 0
    R = d.get('bw_register') or {}
    mtb = sum((R.get('mtb_po_all') or R.get('mtb_po') or {}).values()) / 1000
    lines.append(f"Harvest in {ml(k)}: {h:,.0f} kt gutted ({sg(pc(h, hl))} % on {ml(k - 100)}), average fish {hw:.2f} kg ({hwl:.2f} a year earlier). "
                 f"Biomass at sea {b:,.0f} kt gutted ({sg(pc(b, bl))} %)" + (f", {100 * b / GUT / mtb:.0f} % of the sea MTB (all licences, live weight)." if mtb else '.'))
    # 2) generations : celle qu'on recolte et la suivante, contre les memes generations les 5 annees passees au meme mois
    def gen(g, yy, mm):
        L = [c for c in M(yy, mm) if c['cohort'] == g]
        n = sum(c['stock'] or 0 for c in L); bio = sum((c['stock'] or 0) * (c['weight_kg'] or 0) for c in L)
        return n, bio, (bio / n if n else None)
    tete = None
    for g, role in ((y - 1, 'being harvested'), (y, 'next in line')):
        n, bio, w = gen(g, y, m)
        hist = [gen(g - j, y - j, m) for j in range(1, 6)]
        bios = [x[1] for x in hist if x[1]]; ws = [x[2] for x in hist if x[2]]
        if not w or not ws: continue
        dw = pc(w, sum(ws) / len(ws)); db = pc(bio, sum(bios) / len(bios)) if bios else None
        avance = 'ahead of' if dw > 2 else 'behind' if dw < -2 else 'in line with'
        lines.append(f"Generation {g}, {role}: {w * GUT:.2f} kg gutted on average, {sg(dw)} % against the same generation stage of the past 5 years ({avance} usual)"
                     + (f"; {bio * GUT / 1e6:,.0f} kt gutted left at sea, {sg(db)} %." if db is not None and role == 'being harvested' else '.'))
        if role == 'being harvested': tete = (g, avance, dw, db)
    # 3) mortalite
    mo = 100 * sum_(cur, lambda c: c['dead_stk']) / (sum_(cur, lambda c: c['stock']) or 1)
    mol = 100 * sum_(ly, lambda c: c['dead_stk']) / (sum_(ly, lambda c: c['stock']) or 1)
    lines.append(f"Mortality: {mo:.2f} % of the stock in the month ({mol:.2f} % a year earlier).")
    # 4) prevision des calibres (classement des gros poissons) et revision par rapport au precedent bulletin
    prev = {}
    if os.path.exists(BIG):
        rk = (json.load(io.open(BIG, encoding='utf-8')).get('ranking') or {})
        for x in rk.get('norway', []):
            prev[str(x['month'])] = {'share6': x['share6'], 'share56': x['share56']}
        old = ancien.get('forecast') or {}
        parts = []
        for mk, v in prev.items():
            o = old.get(mk)
            rev = f" (revised {sg(v['share6'] - o['share6'], 1)} pt from last month's forecast)" if o else ''
            parts.append(f"{ml(int(mk))}: 6 kg+ {v['share6']:.1f} %, 5–6 kg {v['share56']:.1f} %{rev}")
        if parts: lines.append('Sizes expected (share of harvest volume): ' + '; '.join(parts) + '.')
        ck = [c for c in rk.get('checks', []) if c.get('month') == k]
        if ck:
            c = ck[-1]
            lines.append(f"Check of last forecast for {ml(k)}: 6 kg+ forecast {c['forecast_share6']} %, actual {c['actual_share6']} %; 5–6 kg forecast {c['forecast_share56']} %, actual {c['actual_share56']} %.")
    titre = f"Biomass register — {ml(k)}"
    if tete:
        g, avance, dw, db = tete
        titre += f": generation {g} {avance} usual ({sg(dw)} % weight)" + (f", {sg(db)} % stock left" if db is not None else '')
    if prev:
        mk = sorted(prev)[0]; titre += f"; 6 kg+ expected {prev[mk]['share6']:.1f} % in {MOIS[int(mk) % 100 - 1]}"
    today = dt.date.today()
    out = {'month': k, 'published': today.isoformat(), 'valid_until': (today + dt.timedelta(days=7)).isoformat(),
           'title': titre, 'lines': lines, 'forecast': prev, 'source': 'Fiskeridirektoratet biomass register; dashboard forecasts'}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, indent=1))
    print('register_brief :', titre)


if __name__ == '__main__':
    main()
