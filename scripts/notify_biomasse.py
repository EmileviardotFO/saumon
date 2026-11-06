"""Notification ntfy quand de nouveaux chiffres du registre de la biomasse sont publies.

Lit data/data.json (deja reconstruit), resume le dernier mois disponible pour la
Norvege entiere et l'envoie au sujet ntfy donne par la variable NTFY_TOPIC.
Les donnees sont publiques ; le nom du sujet reste dans un secret du repo pour
que des inconnus ne s'y abonnent pas en le lisant dans le code.
"""
import json
import os
import sys
import urllib.request

PAGE = "https://emileviardotfo.github.io/saumon/docs/production.html"
MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
        "aout", "septembre", "octobre", "novembre", "decembre"]


def totaux(records, year, month):
    rows = [r for r in records if r["year"] == year and r["month"] == month]
    if not rows:
        return None
    return {
        "recolte_t": sum(r.get("uttak_kg") or 0 for r in rows) / 1000,
        "biomasse_t": sum(r.get("biomasse_kg") or 0 for r in rows) / 1000,
        "poissons": sum(r.get("behfisk_stk") or 0 for r in rows),
    }


def variation(n, n1):
    if not n1:
        return ""
    return f" ({(n / n1 - 1) * 100:+.1f} % sur un an)"


def fmt(x):
    return f"{x:,.0f}".replace(",", " ")


def gen_vs_last_year(year, month):
    """G(annee-1) a la fin du mois face a G(annee-2) un an plus tot : poissons restants, survie, part deja abattue, kilos produits."""
    d = json.load(open("data/data.json", encoding="utf-8"))
    k, k1, H = year * 100 + month, (year - 1) * 100 + month, year - 1
    def gen(g, kk):
        o = dict(fish=0.0, bio=0.0, h=0.0, hkg=0.0, dead=0.0)
        for c in d.get("cohort", []):
            if not c["po"] or c["cohort"] != g:
                continue
            ck = c["year"] * 100 + c["month"]
            if ck > kk:
                continue
            if ck == kk:
                o["fish"] += c["stock"] or 0; o["bio"] += (c["stock"] or 0) * (c["weight_kg"] or 0)
            o["h"] += c["harv_stk"] or 0; o["hkg"] += c["harv_kg"] or 0; o["dead"] += (c["dead_stk"] or 0) + (c["loss_stk"] or 0)
        o["start"] = o["fish"] + o["h"] + o["dead"]
        return o
    a, b = gen(H, k), gen(H - 1, k1)
    if not (a["start"] and b["start"] and b["fish"]):
        return ""
    p = lambda x, y: f"{100 * (x / y - 1):+.0f} %"
    return (f"\nG{H} vs G{H - 1} au meme stade : poissons restants {p(a['fish'], b['fish'])}, "
            f"deja abattus {100 * a['h'] / a['start']:.0f} % vs {100 * b['h'] / b['start']:.0f} %, "
            f"survivants {p(a['start'] - a['dead'], b['start'] - b['dead'])}, kilos produits {p(a['hkg'] + a['bio'], b['hkg'] + b['bio'])}")


def nowcast_next(year, month):
    """Recolte (t vives) du mois suivant le dernier mois du registre, d'apres les exportations de saumon entier (SSB 03024)."""
    import calendar
    import datetime as dt
    d = json.load(open("data/data.json", encoding="utf-8"))
    rows = (d.get("ssb_weekly") or {}).get("rows") or []
    W = {}
    for yw, _p, w, *_ in rows:
        W[yw] = W.get(yw, 0) + (w or 0)
    ex, days = {}, {}
    for yw, t in W.items():
        try:
            mon = dt.date.fromisocalendar(yw // 100, yw % 100, 1)
        except ValueError:
            continue
        for i in range(7):
            x = mon + dt.timedelta(days=i); k = x.year * 100 + x.month
            ex[k] = ex.get(k, 0) + t / 7; days[k] = days.get(k, 0) + 1
    full = lambda k: days.get(k, 0) >= calendar.monthrange(k // 100, k % 100)[1]
    H = {}
    for r in d["records"]:
        k = r["year"] * 100 + r["month"]; H[k] = H.get(k, 0) + (r.get("uttak_kg") or 0) / 1000
    ks = sorted(H)
    last = year * 100 + month
    nxt = last + 1 if month < 12 else (year + 1) * 100 + 1
    if not full(nxt):
        return None
    R = [H[k] / ex[k] for k in ks if k <= last and ex.get(k) and full(k)][-25:]
    if len(R) < 6:
        return None
    ws = sum(0.7 ** (len(R) - 1 - i) for i in range(len(R)))
    r = sum(0.7 ** (len(R) - 1 - i) * x for i, x in enumerate(R)) / ws
    t = ex[nxt] * r
    ly = H.get(nxt - 100)
    return {"m": nxt % 100, "t": t, "yoy": 100 * (t / ly - 1) if ly else 0}


def main():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC absent : pas de notification.")
        return 0

    records = json.load(open("data/data.json", encoding="utf-8"))["records"]
    year, month = max((r["year"], r["month"]) for r in records)
    n = totaux(records, year, month)
    n1 = totaux(records, year - 1, month) or {}

    titre = f"Biomasse Norvege : chiffres de {MOIS[month - 1]} {year} publies"
    corps = (
        f"Recolte : {fmt(n['recolte_t'])} t{variation(n['recolte_t'], n1.get('recolte_t'))}\n"
        f"Biomasse en mer : {fmt(n['biomasse_t'])} t{variation(n['biomasse_t'], n1.get('biomasse_t'))}\n"
        f"Poissons en mer : {n['poissons'] / 1e6:.1f} M{variation(n['poissons'], n1.get('poissons'))}"
    )

    # mois suivant estime d'apres les exportations hebdomadaires SSB (meme methode que Supply outlook)
    try:
        nc = nowcast_next(year, month)
        if nc:
            corps += f"\nRecolte {MOIS[nc['m'] - 1]} estimee (exportations) : {fmt(nc['t'])} t ({nc['yoy']:+.0f} % sur un an)"
    except Exception as e:
        print(f"Estimation par les exportations impossible : {e}")

    # generation recoltee face a celle de l'an dernier au meme stade (onglet Generations vs last year)
    try:
        corps += gen_vs_last_year(year, month)
    except Exception as e:
        print(f"Comparaison des generations impossible : {e}")

    # durees de cycle (data/big_fish.json, reconstruit dans le meme passage) : sites proches du vidage, eleveurs qui accelerent
    try:
        C = json.load(open("data/big_fish.json", encoding="utf-8"))["cycles"]
        no = C.get("norway", {})
        if no.get("due_2m") is not None:
            corps += f"\nSites a ~2 mois du vidage : {no['due_2m']} sur {no['active_sites']}"
        acc = [c for c in C["farmers"] if c["po"] == 0 and c.get("accel")]
        acc.sort(key=lambda c: -c["cycles"])
        if acc:
            corps += "\nCycles qui raccourcissent : " + ", ".join(
                f"{c['co'].title() if c['co'].isupper() else c['co']} ({c['trend'][0]}->{c['trend'][-1]} mois)" for c in acc[:5])
    except Exception as e:
        print(f"Cycles non lus : {e}")

    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=corps.encode("utf-8"),
        headers={
            "Title": titre,
            "Tags": "fish",
            "Click": PAGE,
            "Actions": f"view, Ouvrir le tableau de bord, {PAGE}",
        },
        method="POST",
    )
    if os.environ.get("NTFY_DRY_RUN"):
        print(titre)
        print(corps)
        return 0
    with urllib.request.urlopen(req, timeout=20) as resp:
        print(f"Notification envoyee ({resp.status}) : {titre}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
