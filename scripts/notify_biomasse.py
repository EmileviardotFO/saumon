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
