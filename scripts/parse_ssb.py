#!/usr/bin/env python3
"""
Exports norvegiens de saumon par pays ET par produit, depuis SSB
(Statistikkbanken, table 08799, mensuel).

Usage :
    python3 scripts/parse_ssb.py                 # mode normal (automatisation)
    python3 scripts/parse_ssb.py 2026M07         # un seul mois
    python3 scripts/parse_ssb.py 2026M01 2026M07 # une plage de mois
    python3 scripts/parse_ssb.py --dry-run       # affiche ce qui serait fait

Ecrit dans data/data.json, cle 'ssb_exports'. Les cles existantes
('country' d'Akvafakta, 'country_ssb' d'essais anterieurs) ne sont pas touchees.

POIDS PRODUIT, VOLONTAIREMENT
-----------------------------
SSB donne le poids net du produit tel qu'il passe la frontiere : un kilo de
filet compte pour un kilo. Akvafakta, lui, ramene tout en equivalent poids
rond. Les deux sont gardes separes a dessein : l'ecart entre eux renseigne
sur le degre de transformation de chaque marche. On ne convertit donc rien,
et on ne somme JAMAIS les quatre codes entre eux -- chaque produit reste
une serie distincte.

REVISIONS
---------
SSB publie un mois, puis le revise. D'apres le calendrier que SSB documente
pour ses chiffres annuels : premiere publication, revision en mai de l'annee
suivante, chiffres definitifs en mai de l'annee d'apres. Un mois de janvier
de l'annee t n'est donc definitif qu'en mai t+2, soit 28 mois plus tard.

A chaque passage, le script re-telecharge :
  - tous les mois qui ne sont pas encore definitifs ;
  - tout mois manquant dans data.json (auto-reparation apres un echec) ;
  - au tout premier passage, l'historique complet depuis BACKFILL_FROM.
Les mois deja definitifs et presents ne sont plus jamais interroges.

Chaque mois porte un statut : 'provisional', 'revised' ou 'final'. Le
tableau de bord peut s'en servir pour distinguer les chiffres fragiles.

STRUCTURE ECRITE
----------------
    "ssb_exports": {
      "meta": {
        "products":  {"03021411": "Fresh whole ...", ...},
        "cols":      ["k", "hs", "iso", "kg", "nok"],
        "countries": {"PL": {"name": "Poland", "akva": "Polen"}, ...},
        "months":    {"202607": {"status": "provisional", "fetched": "2026-09-21"}, ...},
        "updated":   "2026-09-21"
      },
      "rows": [[202607, 0, "PL", 12345678, 987654321], ...]
    }
  k   = annee*100+mois (meme convention que le reste du tableau de bord)
  hs  = index dans la liste des produits (compacite : ~40 000 lignes)
  kg  = poids produit net, en kilos
  nok = valeur FOB en couronnes
Seules les cellules non nulles sont stockees.

Verifie le 21/09/2026 sur un export Excel de la table (recoupe avec le
Sjomatrad, ecart < 0,3 % sur juin 2024) :
    - quantite en kg, valeur en couronnes ENTIERES (pas en milliers) ;
    - pays en codes ISO 2 lettres ;
    - codes marchandise SUFFIXES par l'annee de la nomenclature :
      '03021411_2012', pas '03021411'. Le script lit donc les codes exacts
      dans les metadonnees de la table au lieu de les supposer, et
      ramene chaque ligne au code a 8 chiffres pour le stockage.

Variables de la table 08799 confirmees le 18/08/2026 :
    Varekoder = code douanier (HS 8 chiffres)
    ImpEks    = direction, "2" = Export
    Land      = pays partenaire (codes ISO 2 lettres)
    ContentsCode = Mengde1 (kg) / Verdi (NOK) / Mengde2 (inutilise ici)
    Tid       = mois, format AAAAMxx
"""
import sys, json, io, os, argparse, time
import datetime as dt
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
TABLE = "08799"
BASE = f"https://data.ssb.no/api/pxwebapi/v2/tables/{TABLE}"
KEY = 'ssb_exports'

# Les quatre codes retenus : 99,5 % du volume de saumon exporte en 2024.
# L'ordre compte : l'index sert de reference compacte dans les lignes.
PRODUCTS = {
    '03021411': 'Fresh whole, farmed, head on',
    '03044100': 'Fresh fillet',
    '03048100': 'Frozen fillet',
    '03031311': 'Frozen whole, farmed, head on',
}
CODES = list(PRODUCTS)

BACKFILL_FROM = '2018M01'   # debut de la serie, aligne sur Akvafakta
CHUNK = 12                  # mois par requete, pour rester sous la limite de cellules
PAUSE = 1.0                 # secondes entre deux requetes, par courtoisie envers l'API

# Codes ISO SSB -> noms utilises par Akvafakta dans data.json, pour pouvoir
# joindre les deux sources dans le tableau de bord. Un pays absent d'ici
# garde son nom anglais SSB, sans que rien ne casse.
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


# ---------------------------------------------------------------------------
#  Mois : conversions et statut de revision
# ---------------------------------------------------------------------------
def tid_to_k(tid):
    """'2026M07' -> 202607"""
    return int(tid[:4]) * 100 + int(tid[5:])


def k_to_tid(k):
    return f"{k // 100}M{k % 100:02d}"


def month_range(start_tid, end_tid):
    y, m = int(start_tid[:4]), int(start_tid[5:])
    ey, em = int(end_tid[:4]), int(end_tid[5:])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y}M{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def status_of(k, today):
    """Statut d'un mois selon le calendrier de revision SSB : definitif en
    mai de l'annee t+2, revise une premiere fois en mai de t+1."""
    y = k // 100
    if today >= dt.date(y + 2, 5, 1):
        return 'final'
    if today >= dt.date(y + 1, 5, 1):
        return 'revised'
    return 'provisional'


# ---------------------------------------------------------------------------
#  API SSB
# ---------------------------------------------------------------------------
def http_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # L'API SSB explique en clair, dans le corps de la reponse, quel
        # parametre elle rejette ; urllib le masque derriere un simple code.
        body = e.read().decode('utf-8', errors='replace')
        print("=== Reponse d'erreur de l'API SSB ===")
        print(body[:2000])
        print("======================================")
        raise


API_CODES = {c: c + '_2012' for c in CODES}   # repli si les metadonnees echouent


def _cats(meta, dim):
    idx = meta['dimension'][dim]['category']['index']
    return sorted(idx, key=lambda c: idx[c]) if isinstance(idx, dict) else list(idx)


def resolve_codes(varekoder):
    """Pour chaque code a 8 chiffres, retrouve sa forme exacte dans la table
    ('03021411_2012'). S'il en existe plusieurs versions, prend la plus
    recente : c'est elle qui porte les mois actuels."""
    out = {}
    for base in CODES:
        cand = [c for c in varekoder if c.split('_')[0] == base]
        if not cand:
            print(f"  ATTENTION : {base} introuvable dans la table -- repli sur {API_CODES[base]}")
            out[base] = API_CODES[base]
            continue
        suffix = lambda c: int(c.split('_')[1]) if '_' in c and c.split('_')[1].isdigit() else 0
        out[base] = max(cand, key=suffix)
    return out


def load_metadata():
    """Lit les mois publies et les codes marchandise exacts. Met a jour
    API_CODES en place. Renvoie la liste des mois, ou None si la lecture
    echoue -- l'appelant bascule alors sur une estimation par la date."""
    try:
        meta = http_json(f"{BASE}/metadata?lang=en&outputFormat=json-stat2")
        tids = [t for t in _cats(meta, 'Tid') if len(t) == 7 and t[4] == 'M']
        try:
            API_CODES.update(resolve_codes(_cats(meta, 'Varekoder')))
        except KeyError:
            print("  Dimension Varekoder absente des metadonnees -- codes suffixes _2012 par defaut.")
        return tids
    except Exception as e:
        print(f"  Metadonnees illisibles ({e.__class__.__name__}: {e}) -- estimation par la date.")
        return None


def base_code(api_code):
    """'03021411_2012' -> '03021411'."""
    return str(api_code).split('_')[0]


def build_url(tids):
    return (f"{BASE}/data?lang=en"
            f"&valueCodes[Varekoder]={','.join(API_CODES[c] for c in CODES)}"
            f"&valueCodes[ImpEks]=2"
            f"&valueCodes[Land]=*"
            f"&valueCodes[ContentsCode]=Mengde1,Verdi"
            f"&valueCodes[Tid]={','.join(tids)}"
            f"&outputFormat=json-stat2")


def parse_jsonstat2(data):
    """Decode une reponse json-stat2 quelconque en lignes {dim: code, ...,
    'value': x}, et renvoie aussi les libelles par dimension. Les valeurs
    sont parcourues en ordre 'row-major' selon data['id'], la derniere
    dimension variant le plus vite."""
    dims = data['id']
    sizes = [data['size'][i] for i in range(len(dims))]
    cats, labels = [], {}
    for d in dims:
        cat = data['dimension'][d]['category']
        idx = cat['index']
        if isinstance(idx, dict):
            cats.append([c for c, _ in sorted(idx.items(), key=lambda kv: kv[1])])
        else:
            cats.append(list(idx))
        labels[d] = cat.get('label', {})

    strides = [1] * len(dims)
    for i in range(len(dims) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    rows = []
    for flat, v in enumerate(data['value']):
        if v is None:          # cellule absente ou confidentielle
            continue
        rem, row = flat, {}
        for i, d in enumerate(dims):
            row[d] = cats[i][rem // strides[i]]
            rem %= strides[i]
        row['value'] = v
        rows.append(row)
    return rows, labels


def fetch(tids):
    """Telecharge des mois par paquets de CHUNK. Renvoie
    ({(k, code, iso): [kg, nok]}, {iso: libelle})."""
    cells, names = {}, {}
    for i in range(0, len(tids), CHUNK):
        part = tids[i:i + CHUNK]
        print(f"  requete {part[0]} -> {part[-1]} ...")
        rows, labels = parse_jsonstat2(http_json(build_url(part)))
        names.update(labels.get('Land', {}))
        for r in rows:
            key = (tid_to_k(r['Tid']), base_code(r['Varekoder']), r['Land'])
            slot = cells.setdefault(key, [0, 0])
            if r['ContentsCode'] == 'Mengde1':
                slot[0] += r['value']
            elif r['ContentsCode'] == 'Verdi':
                slot[1] += r['value']
        if i + CHUNK < len(tids):
            time.sleep(PAUSE)
    return cells, names


# ---------------------------------------------------------------------------
#  Fusion dans data.json
# ---------------------------------------------------------------------------
def merge(store, cells, names, fetched_tids, today):
    """Remplace dans 'store' tous les mois re-telecharges. Garde-fou : un mois
    qui revient entierement vide n'ecrase PAS ce qui existe deja -- c'est
    presque toujours un mois annonce mais pas encore rempli, pas un vrai zero."""
    meta = store.setdefault('meta', {})
    meta['products'] = PRODUCTS
    meta['cols'] = ['k', 'hs', 'iso', 'kg', 'nok']
    meta.setdefault('countries', {})
    meta.setdefault('months', {})
    rows = store.setdefault('rows', [])

    fetched_k = {tid_to_k(t) for t in fetched_tids}
    nonempty = {k for (k, _, _), (kg, nok) in cells.items() if kg or nok}
    skipped = sorted(fetched_k - nonempty)
    replace = fetched_k & nonempty

    # Totaux avant, pour mesurer l'ampleur des revisions.
    before = {}
    for k, hs, iso, kg, nok in rows:
        if k in replace:
            before[(k, hs)] = before.get((k, hs), 0) + kg

    rows[:] = [r for r in rows if r[0] not in replace]
    added = 0
    for (k, code, iso), (kg, nok) in sorted(cells.items()):
        if k not in replace or code not in PRODUCTS or not (kg or nok):
            continue
        rows.append([k, CODES.index(code), iso, int(round(kg)), int(round(nok))])
        added += 1
        if iso not in meta['countries']:
            entry = {'name': names.get(iso, iso)}
            if iso in ISO_TO_AKVA:
                entry['akva'] = ISO_TO_AKVA[iso]
            meta['countries'][iso] = entry
    rows.sort(key=lambda r: (r[0], r[1], r[2]))

    for k in replace:
        meta['months'][str(k)] = {'status': status_of(k, today),
                                  'fetched': today.isoformat()}
    meta['updated'] = today.isoformat()

    # Rapport de revisions : on ne signale que les ecarts notables.
    after = {}
    for k, hs, iso, kg, nok in rows:
        if k in replace:
            after[(k, hs)] = after.get((k, hs), 0) + kg
    revisions = []
    for key, old in before.items():
        new = after.get(key, 0)
        if old and abs(new - old) / old > 0.005:
            revisions.append((key, old, new))
    return added, skipped, sorted(revisions)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('start', nargs='?', help="premier mois, ex 2026M01")
    ap.add_argument('end', nargs='?', help="dernier mois (optionnel)")
    ap.add_argument('--dry-run', action='store_true',
                    help="affiche les mois et l'URL sans rien ecrire")
    args = ap.parse_args()
    today = dt.date.today()

    data = json.load(io.open(DATA, encoding='utf-8')) if os.path.exists(DATA) else {}
    store = data.get(KEY, {})
    stored = {int(k) for k in store.get('meta', {}).get('months', {})}

    if args.start:
        load_metadata()   # pour les codes marchandise exacts
        tids = month_range(args.start, args.end) if args.end else [args.start]
        print(f"Mode manuel : {len(tids)} mois demandes.")
    else:
        avail = load_metadata()
        if avail is None:
            # Repli : SSB publie le commerce exterieur avec environ un mois
            # de decalage. Un mois pas encore rempli reviendra vide et sera
            # ignore par le garde-fou de merge().
            last = today.replace(day=1) - dt.timedelta(days=1)
            avail = month_range(BACKFILL_FROM, f"{last.year}M{last.month:02d}")
        avail = [t for t in avail if tid_to_k(t) >= tid_to_k(BACKFILL_FROM)]
        tids = [t for t in avail
                if tid_to_k(t) not in stored
                or status_of(tid_to_k(t), today) != 'final']
        if not stored:
            print(f"Premier passage : historique complet depuis {BACKFILL_FROM}.")
        print(f"Mode automatique : {len(tids)} mois a (re)telecharger "
              f"sur {len(avail)} publies.")

    if not tids:
        print("Rien a faire.")
        return
    if args.dry_run:
        print("Mois :", ', '.join(tids))
        print("Premiere URL :", build_url(tids[:CHUNK]))
        return

    cells, names = fetch(tids)
    added, skipped, revisions = merge(store, cells, names, tids, today)
    data[KEY] = store

    # Ecriture atomique : un plantage en cours d'ecriture ne doit jamais
    # laisser un data.json tronque, que tous les autres scripts relisent.
    tmp = DATA + '.tmp'
    io.open(tmp, 'w', encoding='utf-8').write(
        json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    os.replace(tmp, DATA)

    months = store['meta']['months']
    n_by = {s: sum(1 for m in months.values() if m['status'] == s)
            for s in ('provisional', 'revised', 'final')}
    print(f"\n{added} lignes ecrites pour {len(tids) - len(skipped)} mois.")
    if skipped:
        print(f"  {len(skipped)} mois revenus vides, NON ecrases : "
              + ', '.join(k_to_tid(k) for k in skipped))
    if revisions:
        print(f"  {len(revisions)} revision(s) de plus de 0,5 % :")
        for (k, hs), old, new in revisions[:15]:
            print(f"    {k_to_tid(k)} {CODES[hs]} : {old/1000:,.0f} t -> "
                  f"{new/1000:,.0f} t ({100*(new-old)/old:+.1f} %)")
    print(f"Stock : {len(store['rows'])} lignes, {len(months)} mois "
          f"({n_by['final']} definitifs, {n_by['revised']} revises, "
          f"{n_by['provisional']} provisoires), "
          f"{len(store['meta']['countries'])} pays.")
    print(f"data.json : {os.path.getsize(DATA)/1e6:.1f} Mo")


if __name__ == '__main__':
    main()
