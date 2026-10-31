#!/usr/bin/env python3
"""Ecosse : rapports mensuels des fermes marines a la SEPA (biomasse en mer, mortalites, aliment, traitements).

Source : Scotland's Aquaculture, "Fish Farm Monthly Biomass and Treatment Reports" (bouton CSV Export de
https://aquaculture.scotland.gov.uk/Data/FishFarmMonthlyBiomassAndTreatmentReports). Les eleveurs declarent chaque
trimestre, d'ou environ 6 mois de retard. Le fichier brut est depose a la main dans xlsx/scotland/ (le plus recent
est utilise) ; ce script en tire data/scotland.json, des series mensuelles compactes :
  - Ecosse entiere, par region (conseil local) et par operateur : biomasse en mer (t vif), mortalites (t),
    aliment (t), sites actifs, biomasse maximale autorisee des sites actifs ;
  - mortalites mensuelles inhabituelles par region (meme regle que pour les zones norvegiennes).
"""
import glob, json, os, sys, datetime as dt
import pandas as pd

RAW = sorted(glob.glob('xlsx/scotland/*.csv'), key=os.path.getmtime)
OUT = 'data/scotland.json'
REGION = {'Shetland Islands': 'Shetland', 'Orkney Islands': 'Orkney', 'Eilean Siar': 'Western Isles',
          'Highland': 'Highland', 'Argyll and Bute': 'Argyll and Bute'}

def osgb_to_latlon(E, N):
    """Grille nationale britannique (OSGB36) -> latitude/longitude, formules de l'Ordnance Survey puis Helmert vers WGS84."""
    import math
    a, b = 6377563.396, 6356256.909; F0 = 0.9996012717; lat0, lon0 = math.radians(49), math.radians(-2); N0, E0 = -100000, 400000
    e2 = 1 - (b * b) / (a * a); n = (a - b) / (a + b)
    lat, M = lat0, 0
    while True:
        lat = (N - N0 - M) / (a * F0) + lat
        Ma = (1 + n + 5 / 4 * n ** 2 + 5 / 4 * n ** 3) * (lat - lat0); Mb = (3 * n + 3 * n ** 2 + 21 / 8 * n ** 3) * math.sin(lat - lat0) * math.cos(lat + lat0)
        Mc = (15 / 8 * n ** 2 + 15 / 8 * n ** 3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0)); Md = 35 / 24 * n ** 3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0))
        M = b * F0 * (Ma - Mb + Mc - Md)
        if abs(N - N0 - M) < 1e-5: break
    s, c, t = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * s * s); rho = a * F0 * (1 - e2) / (1 - e2 * s * s) ** 1.5; eta2 = nu / rho - 1
    VII = t / (2 * rho * nu); VIII = t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2); IX = t / (720 * rho * nu ** 5) * (61 + 90 * t * t + 45 * t ** 4)
    X = 1 / (c * nu); XI = 1 / (c * 6 * nu ** 3) * (nu / rho + 2 * t * t); XII = 1 / (c * 120 * nu ** 5) * (5 + 28 * t * t + 24 * t ** 4); XIIA = 1 / (c * 5040 * nu ** 7) * (61 + 662 * t * t + 1320 * t ** 4 + 720 * t ** 6)
    dE = E - E0
    phi = lat - VII * dE ** 2 + VIII * dE ** 4 - IX * dE ** 6; lam = lon0 + X * dE - XI * dE ** 3 + XII * dE ** 5 - XIIA * dE ** 7
    # Helmert OSGB36 -> WGS84
    H = 0
    x1 = (nu / F0 if False else a / math.sqrt(1 - e2 * math.sin(phi) ** 2))
    X1, Y1, Z1 = (x1 + H) * math.cos(phi) * math.cos(lam), (x1 + H) * math.cos(phi) * math.sin(lam), ((1 - e2) * x1 + H) * math.sin(phi)
    tx, ty, tz, s_ = 446.448, -125.157, 542.060, -20.4894e-6; rx, ry, rz = [math.radians(v / 3600) for v in (0.1502, 0.2470, 0.8421)]
    X2 = tx + (1 + s_) * X1 - rz * Y1 + ry * Z1; Y2 = ty + rz * X1 + (1 + s_) * Y1 - rx * Z1; Z2 = tz - ry * X1 + rx * Y1 + (1 + s_) * Z1
    a2, b2 = 6378137.000, 6356752.3141; e22 = 1 - (b2 * b2) / (a2 * a2); p = math.sqrt(X2 * X2 + Y2 * Y2)
    phi2 = math.atan2(Z2, p * (1 - e22))
    for _ in range(10):
        nu2 = a2 / math.sqrt(1 - e22 * math.sin(phi2) ** 2); phi2 = math.atan2(Z2 + e22 * nu2 * math.sin(phi2), p)
    return math.degrees(phi2), math.degrees(math.atan2(Y2, X2))

def main():
    if not RAW: print('scotland: no raw file in xlsx/scotland/, nothing to do'); return
    f = RAW[-1]
    df = pd.read_csv(f, low_memory=False)
    df['k'] = pd.to_datetime(df['Year'], format='%d-%b-%Y').dt.strftime('%Y%m').astype(int)
    df = df[df['Water Type'].fillna('Seawater').str.lower().str.startswith('sea')]
    bio, mort, feed, mtb = 'Actual Biomass on Site (tonnes)', 'Mortalities Kilograms', 'Feed Kilograms', 'Maximum Biomass Allowed (tonnes)'
    df['region'] = df['Local Authority'].map(REGION).fillna('Other')
    df['act'] = df[bio] > 0
    df['mtb_act'] = df[mtb].where(df['act'], 0)

    def agg(g):
        a = g.groupby('k').agg(bio=(bio, 'sum'), mort=(mort, 'sum'), feed=(feed, 'sum'), sites=('act', 'sum'), mtb=('mtb_act', 'sum'))
        a['mort'] = (a['mort'] / 1000).round(1); a['feed'] = (a['feed'] / 1000).round(0)
        return {int(k): [int(r.bio), float(r.mort), int(r.feed), int(r.sites), int(r.mtb)] for k, r in a.iterrows()}

    nat = agg(df)
    regions = {r: agg(g) for r, g in df.groupby('region')}
    ops = {}
    for o, g in df.groupby('Operator'):
        if g[bio].sum() > 0 and g['k'].max() >= df['k'].max() - 300: ops[o] = agg(g)   # operateurs actifs ces 3 dernieres annees
    # ---- par site (depuis 2018) : coordonnees, operateur mois par mois, biomasse, morts, aliment, traitements
    K0 = 201801
    months = sorted(k for k in df['k'].unique() if k >= K0)
    idx = {k: i for i, k in enumerate(months)}
    med = ['Deltamethrin grams', 'Cypermethrin grams', 'Azamethiphos grams', 'Teflubenzuron grams', 'Emamectin Benzoate grams']
    df['med'] = df[[c for c in med if c in df.columns]].fillna(0).sum(axis=1) > 0
    opl = sorted(df.loc[df['k'] >= K0, 'Operator'].dropna().unique().tolist())
    opi = {o: i for i, o in enumerate(opl)}
    sites = {}
    for sid, g in df[df['k'] >= K0].groupby('SEPA Site'):
        if g[bio].sum() <= 0 and g[mort].fillna(0).sum() <= 0: continue
        last = g.sort_values('k').iloc[-1]
        lat, lon = osgb_to_latlon(float(last['Easting']), float(last['Northing']))
        n = len(months); B, Mo, F, O, T = [None] * n, [None] * n, [None] * n, [None] * n, [0] * n
        for _, r in g.iterrows():
            i = idx[r['k']]; B[i] = int(r[bio]); Mo[i] = round(float(r[mort]) / 1000, 2) if pd.notna(r[mort]) else 0
            F[i] = int(round(float(r[feed]) / 1000)); O[i] = opi.get(r['Operator']); T[i] = 1 if r['med'] else 0
        sites[sid] = {'n': str(last['Site Name']), 'r': str(last['region']), 'w': str(last['Receiving Water'] or ''), 'mtb': int(last[mtb]),
                      'lat': round(lat, 4), 'lon': round(lon, 4), 'o': O, 'b': B, 'm': Mo, 'f': F, 't': T}
    out_sites = {'months': [int(k) for k in months], 'operators': opl, 'sites': sites}

    out = {'site_data': out_sites, 'meta': {'generated': dt.date.today().isoformat(), 'source': 'SEPA monthly biomass and treatment reports (Scotland\'s Aquaculture)',
                    'url': 'https://aquaculture.scotland.gov.uk/Data/FishFarmMonthlyBiomassAndTreatmentReports', 'raw': os.path.basename(f),
                    'first': int(df['k'].min()), 'last': int(df['k'].max()), 'sites': int(df['SEPA Site'].nunique()),
                    'cols': ['biomass_t_live', 'mortalities_t', 'feed_t', 'active_sites', 'max_biomass_allowed_t'],
                    'note': 'biomass on site at month end (live weight, t); mortalities and feed over the month; regions = local authorities'},
           'national': nat, 'regions': regions, 'operators': ops}
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    last = max(nat); print(f'scotland: {f} -> {OUT}, {len(nat)} months to {last}, biomass {nat[last][0]} t, {len(ops)} operators')

if __name__ == '__main__':
    main()
