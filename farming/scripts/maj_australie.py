#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maj_australie.py : relit les deux sources primaires australiennes et tient les données à jour.

  1. EPA Tasmanie, page « Salmon Waste Management » : mortalités mensuelles (poids, toutes
     entreprises) avec ventilation par méthode de traitement.
  2. Portail NRE Tasmanie (Salmon Farming Data Portal) : production par entreprise et par exercice
     (poids HOG), et période de déclaration courante.

Ce que fait le script à chaque passage
  - télécharge les pages (3 essais, délai de 60 s), normalise le texte (espaces de largeur nulle,
    lettres grecques collées dans « Nil », barres de tableau) ;
  - extrait chaque ligne « <Mois> <année> Tonnage » et vérifie que la somme des méthodes
    égale le total (tolérance 1 t : arrondi de la source) ;
  - compare à ce qui est déjà en base : nouveaux mois, RÉVISIONS d'un chiffre déjà publié,
    anomalies de lecture ;
  - écrit donnees_au/au_mensuel.csv, au_entreprises.csv et au_journal.csv (historique) ;
  - avec --xlsx, remplit AU_Mensuel (colonnes D à I, R, S) et AU_Entreprises du classeur ;
  - signale un RETARD si la publication attendue (fin de trimestre + 21 jours + tolérance)
    est dépassée sans nouveau mois. L'état « à jour » repose sur le dernier mois réellement
    lu, jamais sur le calendrier seul.

Usage
    python maj_australie.py --seche                       # lit et affiche, n'écrit rien
    python maj_australie.py --xlsx farming_canada_australie.xlsx
    python maj_australie.py --epa-fichier epa.html --nre-fichier nre.html   # hors ligne

Fréquence conseillée : une fois par jour. L'EPA publie par trimestre (vers le 21 janvier, avril,
juillet, octobre) mais la date réelle varie (cinq semaines après le trimestre en 2025, 17 avril
pour le T1 2026) : un passage quotidien attrape la sortie le jour même. Voir maj_australie.yml.

Limite connue : écrit sans avoir pu être lancé sur les vraies pages (l'environnement de
développement n'avait pas accès à ces sites). Testé sur le texte réel des pages. Au premier
passage, utiliser --seche et contrôler la sortie.
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, sys, time, urllib.request
from html.parser import HTMLParser

EPA_URL = 'https://epa.tas.gov.au/business-industry/regulation/salmon-aquaculture/salmon-waste-management'
NRE_URLS = ['https://salmonfarming.nre.tas.gov.au/tamar-estuary', 'https://salmonfarming.nre.tas.gov.au/']
ENTREPRISES = ['Tassal', 'Huon Aquaculture', 'Petuna']
MOIS = {m: i for i, m in enumerate(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                    'September', 'October', 'November', 'December'], 1)}
METHODES = ['rendering', 'compost', 'decharge', 'ensilage', 'enfouissement']
DELAI_EPA, TOLERANCE = 21, 14
UA = 'Mozilla/5.0 (compatible; suivi-salmonicole/1.0)'


# ----------------------------------------------------------------------------- lecture
class _Texte(HTMLParser):
    def __init__(self):
        super().__init__(); self.out = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
        self.out.append(' ')
    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip: self.skip -= 1
        self.out.append(' ')
    def handle_data(self, data):
        if not self.skip: self.out.append(data)


def normaliser(brut):
    if '<' in brut and '>' in brut:
        p = _Texte(); p.feed(brut); brut = ' '.join(p.out)
    brut = re.sub('[\u200b-\u200f\u2060\ufeff]', '', brut)       # espaces de largeur nulle
    brut = brut.replace('\xa0', ' ').replace('|', ' ')
    return re.sub(r'\s+', ' ', brut).strip()


def telecharger(url, essais=3):
    for k in range(essais):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            return urllib.request.urlopen(req, timeout=60).read().decode('utf-8', errors='replace')
        except Exception as e:                                    # noqa: BLE001
            derniere = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(f'injoignable : {url} ({derniere})')


def nombre(tok):
    """'1,250' -> 1250 ; 'Nil', 'N​il', 'ΝίΙ' ou tout non-numérique -> 0."""
    t = tok.replace(',', '')
    return int(t) if re.fullmatch(r'\d+', t) else 0


# ----------------------------------------------------------------------------- EPA
def lire_epa(texte):
    """-> ({(année, mois): {...}}, [anomalies])"""
    t = normaliser(texte)
    motif = re.compile(r'(' + '|'.join(MOIS) + r')\s+(\d{4})\s+Tonnage\s+' + r'\s+'.join([r'(\S+)'] * 6))
    res, anomalies = {}, []
    for m in motif.finditer(t):
        mois, an = MOIS[m.group(1)], int(m.group(2))
        vals = [nombre(x) for x in m.groups()[2:]]
        ligne = dict(zip(METHODES + ['total'], vals))
        ecart = sum(vals[:5]) - vals[5]
        if abs(ecart) > 1:
            anomalies.append(f'{an}-{mois:02d} : somme des méthodes {sum(vals[:5])} ≠ total {vals[5]}')
        elif ecart:
            ligne['note'] = f'somme des méthodes {sum(vals[:5])} pour un total de {vals[5]} (arrondi de la source)'
        if (an, mois) in res and res[(an, mois)] != ligne:
            anomalies.append(f'{an}-{mois:02d} : deux lignes différentes sur la page')
        res[(an, mois)] = ligne
    if not res:
        anomalies.append('aucune ligne « <Mois> <année> Tonnage » trouvée : la mise en page a peut-être changé')
    return res, anomalies


# ----------------------------------------------------------------------------- NRE
def lire_nre(texte):
    """-> ({(entreprise, fin_exercice): (libellé, tonnes)}, période_courante, [anomalies])"""
    t = normaliser(texte)
    anomalies, res = [], {}
    periode = None
    q = re.findall(r'Quarter\s*(\d)\s*,?\s*(\d{4})', t)
    if q: periode = max(q, key=lambda x: (int(x[1]), int(x[0])))
    i = t.find('tonnes produced state-wide')
    if i < 0:
        return res, periode, ['bloc « tonnes produced state-wide » introuvable']
    seg = t[i:i + 900]
    exercices = re.findall(r'FY(\d{4})/(\d{2})', seg)
    if not exercices:
        return res, periode, ['aucun en-tête FY aaaa/aa dans le bloc de production']
    pos = [(seg.find(e), e) for e in ENTREPRISES if seg.find(e) >= 0]
    pos.sort()
    for k, (p, ent) in enumerate(pos):
        fin = pos[k + 1][0] if k + 1 < len(pos) else min(len(seg), p + 200)
        corps = seg[p + len(ent):fin]
        run = re.match(r'\s*((?:\d[\d,]*(?:\.\d+)?\s+)*\d[\d,]*(?:\.\d+)?)(?=\s|$)', corps)   # suite de nombres collés au nom
        nums = re.findall(r'\d[\d,]*(?:\.\d+)?', run.group(1)) if run else []
        if len(nums) < len(exercices):
            anomalies.append(f'{ent} : {len(nums)} valeur(s) pour {len(exercices)} exercice(s)')
        for (a, b), tok in zip(exercices, nums):
            res[(ent, 2000 + int(b))] = (f'{a}/{b}', float(tok.replace(',', '')))
    manquantes = [e for e in ENTREPRISES if e not in [p[1] for p in pos]]
    if manquantes: anomalies.append('entreprises absentes : ' + ', '.join(manquantes))
    return res, periode, anomalies


# ----------------------------------------------------------------------------- stockage
def charger_csv(chemin, cles):
    if not os.path.exists(chemin): return {}
    with open(chemin, encoding='utf-8-sig', newline='') as fh:
        return {tuple(r[c] for c in cles): r for r in csv.DictReader(fh)}


def ecrire_csv(chemin, champs, lignes):
    with open(chemin, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=champs); w.writeheader(); w.writerows(lignes)


def journal(dossier, source, statut, detail):
    chemin = os.path.join(dossier, 'au_journal.csv')
    neuf = not os.path.exists(chemin)
    with open(chemin, 'a', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        if neuf: w.writerow(['horodatage', 'source', 'statut', 'detail'])
        w.writerow([dt.datetime.now().isoformat(timespec='seconds'), source, statut, detail])
    print(f'[{statut}] {source} : {detail}')


def fin_trimestre_suivant(mois_max):
    """Fin du premier trimestre pas encore couvert par le dernier mois lu."""
    import calendar
    an, m = mois_max
    q_end = ((m - 1) // 3 + 1) * 3
    cible = q_end + 3 if m == q_end else q_end
    an2, m2 = (an, cible) if cible <= 12 else (an + 1, cible - 12)
    return dt.date(an2, m2, calendar.monthrange(an2, m2)[1])


# ----------------------------------------------------------------------------- classeur
def maj_classeur(chemin, mensuel, entreprises, releve):
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill
    wb = load_workbook(chemin)
    notes = []
    wm = wb['AU_Mensuel']
    for r in range(6, wm.max_row + 1):
        d = wm.cell(row=r, column=1).value
        if not isinstance(d, (dt.date, dt.datetime)): continue
        cle = (d.year, d.month)
        if cle not in mensuel: continue
        v = mensuel[cle]
        ancien = wm.cell(row=r, column=4).value
        if ancien not in (None, v['total']):
            notes.append(f'AU_Mensuel {cle[0]}-{cle[1]:02d} : {ancien} -> {v["total"]}')
        wm.cell(row=r, column=4, value=v['total']).fill = PatternFill(fill_type=None)
        for j, mth in enumerate(METHODES): wm.cell(row=r, column=5 + j, value=v[mth])
        wm.cell(row=r, column=18, value='oui')
        wm.cell(row=r, column=19, value=f'Page EPA, relevé du {releve}' + (f' ; {v["note"]}' if v.get('note') else ''))
    we = wb['AU_Entreprises']
    lignes = {(we.cell(row=r, column=1).value, we.cell(row=r, column=3).value): r for r in range(5, 41)
              if we.cell(row=r, column=1).value}
    libres = [r for r in range(5, 41) if not we.cell(row=r, column=1).value]
    for (ent, fin), (lib, t) in entreprises.items():
        if (ent, fin) in lignes:
            r = lignes[(ent, fin)]
            if we.cell(row=r, column=4).value not in (None, t):
                notes.append(f'AU_Entreprises {ent} {lib} : {we.cell(row=r, column=4).value} -> {t}')
        elif libres:
            r = libres.pop(0)
            we.cell(row=r, column=1, value=ent); we.cell(row=r, column=2, value=lib); we.cell(row=r, column=3, value=fin)
        else:
            notes.append('AU_Entreprises : plus de ligne libre'); continue
        we.cell(row=r, column=4, value=t); we.cell(row=r, column=7, value='AU23')
        we.cell(row=r, column=8, value=f'Portail NRE, relevé du {releve}')
    wb.save(chemin)
    return notes


# ----------------------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sortie', default='donnees_au')
    ap.add_argument('--xlsx')
    ap.add_argument('--seche', action='store_true', help='lit et affiche sans rien écrire')
    ap.add_argument('--epa-fichier'); ap.add_argument('--nre-fichier')
    ap.add_argument('--strict', action='store_true', help='code de sortie 1 en cas d\'anomalie ou de retard')
    a = ap.parse_args()
    aujourdhui = dt.date.today(); releve = aujourdhui.isoformat()
    os.makedirs(a.sortie, exist_ok=True)
    alertes = []

    # EPA
    try:
        brut = open(a.epa_fichier, encoding='utf-8').read() if a.epa_fichier else telecharger(EPA_URL)
        mensuel, anom = lire_epa(brut)
        alertes += [f'EPA : {x}' for x in anom]
        base = charger_csv(os.path.join(a.sortie, 'au_mensuel.csv'), ['mois'])
        nouveaux, revisions = [], []
        for (an, m), v in sorted(mensuel.items()):
            k = (f'{an}-{m:02d}',)
            if k not in base: nouveaux.append(k[0])
            elif int(base[k]['total']) != v['total']: revisions.append(f'{k[0]} : {base[k]["total"]} -> {v["total"]}')
        if not a.seche:
            lignes = [{'mois': f'{an}-{m:02d}', **{x: v[x] for x in METHODES + ['total']},
                       'note': v.get('note', ''), 'source': EPA_URL, 'releve': releve}
                      for (an, m), v in sorted(mensuel.items())]
            ecrire_csv(os.path.join(a.sortie, 'au_mensuel.csv'),
                       ['mois'] + METHODES + ['total', 'note', 'source', 'releve'], lignes)
        dernier = max(mensuel) if mensuel else None
        journal(a.sortie, 'EPA', 'changement' if (nouveaux or revisions) else 'inchangé',
                f'{len(mensuel)} mois lus, dernier {dernier[0]}-{dernier[1]:02d}' if dernier else 'rien lu')
        if nouveaux: journal(a.sortie, 'EPA', 'nouveaux mois', ', '.join(nouveaux))
        for x in revisions: journal(a.sortie, 'EPA', 'RÉVISION', x); alertes.append(f'EPA révision {x}')
        if dernier:
            attendu = fin_trimestre_suivant(dernier) + dt.timedelta(days=DELAI_EPA)
            if aujourdhui > attendu + dt.timedelta(days=TOLERANCE):
                alertes.append(f'EPA : publication attendue le {attendu} dépassée, dernier mois lu {dernier[0]}-{dernier[1]:02d}')
    except Exception as e:                                         # noqa: BLE001
        mensuel = {}
        journal(a.sortie, 'EPA', 'ERREUR', str(e)); alertes.append(f'EPA : {e}')

    # NRE
    entreprises, periode = {}, None
    try:
        sources = [a.nre_fichier] if a.nre_fichier else NRE_URLS
        for s in sources:
            brut = open(s, encoding='utf-8').read() if a.nre_fichier else telecharger(s)
            ent, per, anom = lire_nre(brut)
            if ent:
                entreprises, periode = ent, per
                alertes += [f'NRE : {x}' for x in anom]
                break
        else:
            alertes.append('NRE : bloc de production introuvable sur toutes les pages essayées')
        base = charger_csv(os.path.join(a.sortie, 'au_entreprises.csv'), ['entreprise', 'fin_exercice'])
        rev = [f'{e} {l}: {base[(e, str(f))]["tonnes"]} -> {t}' for (e, f), (l, t) in entreprises.items()
               if (e, str(f)) in base and abs(float(base[(e, str(f))]['tonnes']) - t) > 0.5]
        if not a.seche and entreprises:
            ecrire_csv(os.path.join(a.sortie, 'au_entreprises.csv'),
                       ['entreprise', 'exercice', 'fin_exercice', 'tonnes', 'source', 'releve'],
                       [{'entreprise': e, 'exercice': l, 'fin_exercice': f, 'tonnes': t, 'source': 'portail NRE', 'releve': releve}
                        for (e, f), (l, t) in sorted(entreprises.items())])
        journal(a.sortie, 'NRE', 'ok' if entreprises else 'ERREUR',
                f'{len(entreprises)} valeurs, période courante {("T%s %s" % periode) if periode else "inconnue"}')
        for x in rev: journal(a.sortie, 'NRE', 'RÉVISION', x); alertes.append(f'NRE révision {x}')
    except Exception as e:                                         # noqa: BLE001
        journal(a.sortie, 'NRE', 'ERREUR', str(e)); alertes.append(f'NRE : {e}')

    if a.xlsx and not a.seche and (mensuel or entreprises):
        for n in maj_classeur(a.xlsx, mensuel, entreprises, releve):
            journal(a.sortie, 'classeur', 'RÉVISION', n)
        print('classeur mis à jour : ouvrir dans Excel pour recalculer les formules')
    if alertes:
        print('\nALERTES :'); [print(' -', x) for x in alertes]
    sys.exit(1 if (alertes and a.strict) else 0)


if __name__ == '__main__':
    main()
