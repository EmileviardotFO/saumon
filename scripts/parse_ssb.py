#!/usr/bin/env python3
"""
Extracteur SSB (Statistikkbanken, table 08799) pour les exports de saumon
par pays -- alternative a la table 7 des rapports Akvafakta maned.

Usage :
    python3 scripts/parse_ssb.py 2026M07              # un seul mois
    python3 scripts/parse_ssb.py 2026M01 2026M07       # plage de mois

Ecrit/met a jour data/data.json, cle 'country_ssb' -- separee de 'country'
(issue d'Akvafakta) pour pouvoir comparer les deux sources sans que l'une
n'ecrase l'autre.

Structure ecrite, un objet par mois :
    {"year":2026,"month":7,"pays":[
        {"pays":"Polen","q":..., "v":...}, ...
    ]}
    q en tonnes (poids rond), v en NOK (pas en milliers -- SSB donne des
    valeurs en couronnes entieres, a verifier au premier import reel).

Table 08799 : "External trade in goods, by commodity number (HS) and
country". Variables confirmees le 18/08/2026 :
    Varekoder   = code douanier (HS)
    ImpEks       = direction, "2" = Export
    Land         = pays partenaire (codes ISO 2 lettres)
    ContentsCode = Mengde1 (quantite) / Verdi (valeur NOK) / Mengde2
    Tid          = mois, format AAAAMxx (ex. 2026M07)
"""
import sys, json, io, os, argparse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
TABLE = "08799"
BASE = f"https://data.ssb.no/api/pxwebapi/v2/tables/{TABLE}/data"

# Codes douaniers du saumon d'elevage. A confirmer au premier essai reel --
# ce sont les codes generalement cites dans la documentation SSB (03024,
# et les tables fillet 03044/03048), mais les tables changent parfois de
# nomenclature d'une annee sur l'autre (ex. 2012 -> 03021411/03021419).
HS_SALMON = [
    '03021411', '03021419',   # entier, frais/refrigere
    '03031311', '03031319',   # entier, congele
    '03044100',                # filet, frais/refrigere
    '03048100',                # filet, congele
]

# Codes ISO SSB (2 lettres) -> noms utilises cote Akvafakta dans data.json,
# pour pouvoir comparer les deux sources sur les memes cles. Liste partielle
# volontairement -- les pays absents d'ici s'affichent avec leur code ISO
# brut plutot que de faire planter le script.
ISO_TO_AKVA = {
    'PL': 'Polen', 'DK': 'Danmark', 'NL': 'Nederland', 'FR': 'Frankrike',
    'ES': 'Spania', 'IT': 'Italia', 'DE': 'Tyskland', 'LT': 'Litauen',
    'SE': 'Sverige', 'FI': 'Finland', 'BE': 'Belgia', 'EE': 'Estland',
    'PT': 'Portugal', 'IE': 'Irland', 'CZ': 'Tsjekkia', 'GR': 'Hellas',
    'LV': 'Latvia', 'RO': 'Romania', 'BG': 'Bulgaria', 'CY': 'Kypros',
    'AT': 'Østerrike', 'HR': 'Kroatia', 'SK': 'Slovakia', 'SI': 'Slovenia',
    'HU': 'Ungarn', 'MT': 'Malta', 'LU': 'Luxembourg',
    'JP': 'Japan', 'CN': 'Kina', 'HK': 'Hongkong',
    'KR': 'Sør-Korea', 'IL': 'Israel', 'TH': 'Thailand',
    'AE': 'De Forente Arabiske Emirater', 'SA': 'Saudi-Arabia',
    'TW': 'Taiwan', 'SG': 'Singapore', 'VN': 'Vietnam',
    'US': 'Usa', 'CA': 'Canada', 'MX': 'Mexico', 'GB': 'Storbritannia',
    'UA': 'Ukraina', 'KZ': 'Kasakhstan', 'TR': 'Tyrkia', 'ZA': 'Sør-Afrika',
    'EG': 'Egypt', 'AU': 'Australia', 'CH': 'Sveits', 'RS': 'Serbia',
}


def build_url(tid_values):
    """tid_values : liste de mois au format '2026M07'."""
    commodity = ",".join(HS_SALMON)
    tid = ",".join(tid_values)
    return (f"{BASE}?lang=en"
            f"&valueCodes[Varekoder]={commodity}"
            f"&valueCodes[ImpEks]=2"
            f"&valueCodes[Land]=*"
            f"&valueCodes[ContentsCode]=Mengde1,Verdi"
            f"&valueCodes[Tid]={tid}"
            f"&outputFormat=json-stat2")


def fetch(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # L'API SSB explique generalement en clair, dans le corps de la
        # reponse, quel parametre a ete rejete -- urllib le masque par
        # defaut derriere un simple "400 Bad Request". On l'affiche ici
        # pour ne plus avoir a deviner d'un essai a l'autre.
        body = e.read().decode('utf-8', errors='replace')
        print("=== Reponse d'erreur de l'API SSB ===")
        print(body)
        print("======================================")
        raise


def parse_jsonstat2(data):
    """Decode une reponse json-stat2 generique (dimensions quelconques,
    ordre donne par data['id']) en liste de dict {dim: valeur, ...,
    'value': x}. Le decodage json-stat2 standard : chaque dimension a un
    'category.index' qui mappe id -> position ; 'value' est un tableau a
    plat parcouru en "row-major" selon l'ordre de data['id'], la derniere
    dimension variant le plus vite."""
    dims = data['id']
    sizes = [data['size'][i] for i in range(len(dims))]
    cats = []
    for d in dims:
        idx = data['dimension'][d]['category']['index']
        # idx peut etre un dict {code: position} ou une liste ordonnee
        if isinstance(idx, dict):
            ordered = sorted(idx.items(), key=lambda kv: kv[1])
            cats.append([code for code, _ in ordered])
        else:
            cats.append(list(idx))

    values = data['value']
    rows = []
    n = len(values)
    # position multi-dimensionnelle -> indices par dimension
    strides = [1] * len(dims)
    for i in range(len(dims) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    for flat in range(n):
        v = values[flat]
        if v is None:
            continue
        rem = flat
        row = {}
        for i, d in enumerate(dims):
            pos = rem // strides[i]
            rem = rem % strides[i]
            row[d] = cats[i][pos]
        row['value'] = v
        rows.append(row)
    return rows


def to_country_records(rows):
    """Regroupe les lignes plates par (annee, mois, pays) -> {q, v}."""
    by_key = {}
    for r in rows:
        tid = r['Tid']                       # ex. '2026M07'
        year, month = int(tid[:4]), int(tid[5:])
        land = r['Land']
        pays = ISO_TO_AKVA.get(land, land)
        content = r['ContentsCode']
        key = (year, month, pays)
        entry = by_key.setdefault(key, {'q': None, 'v': None})
        if content == 'Mengde1':
            entry['q'] = (entry['q'] or 0) + r['value']
        elif content == 'Verdi':
            entry['v'] = (entry['v'] or 0) + r['value']

    by_month = {}
    for (year, month, pays), vals in by_key.items():
        if vals['q'] is None and vals['v'] is None:
            continue
        m = by_month.setdefault((year, month), [])
        m.append({'pays': pays, 'q': vals['q'] or 0, 'v': vals['v'] or 0})
    return by_month


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('start', help="premier mois, ex 2026M01")
    ap.add_argument('end', nargs='?', help="dernier mois (optionnel)")
    ap.add_argument('--dry-run', action='store_true',
                    help="affiche l'URL et un extrait sans ecrire data.json")
    args = ap.parse_args()

    if args.end:
        # construire la liste des mois entre start et end inclus
        sy, sm = int(args.start[:4]), int(args.start[5:])
        ey, em = int(args.end[:4]), int(args.end[5:])
        months = []
        y, m = sy, sm
        while (y, m) <= (ey, em):
            months.append(f"{y}M{m:02d}")
            m += 1
            if m > 12:
                m = 1; y += 1
    else:
        months = [args.start]

    url = build_url(months)
    print("URL :", url)
    if args.dry_run:
        return

    raw = fetch(url)
    rows = parse_jsonstat2(raw)
    print(f"{len(rows)} lignes decodees")
    by_month = to_country_records(rows)

    data = json.load(io.open(DATA)) if os.path.exists(DATA) else {}
    data.setdefault('country_ssb', [])
    existing = {(r['year'], r['month']) for r in data['country_ssb']}

    added = 0
    for (year, month), pays in by_month.items():
        key = (year, month)
        data['country_ssb'] = [r for r in data['country_ssb']
                               if (r['year'], r['month']) != key]
        data['country_ssb'].append({'year': year, 'month': month, 'pays': pays})
        if key not in existing:
            added += 1

    data['country_ssb'].sort(key=lambda r: (r['year'], r['month']))
    io.open(DATA, 'w').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f"{added} nouveaux mois, {len(data['country_ssb'])} au total dans country_ssb")


if __name__ == '__main__':
    main()
