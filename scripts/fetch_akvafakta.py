#!/usr/bin/env python3
"""
Telecharge les derniers rapports Akvafakta (hebdo + mensuel) depuis
akvafakta.no et les enregistre sous le bon nom pour parse_akvafakta.py.

akvafakta.no publie deux permaliens qui pointent toujours vers le
DERNIER rapport en date :
    https://akvafakta.no/wp-content/uploads/Ukestat/siste.pdf
    https://akvafakta.no/wp-content/uploads/Maned/siste.pdf
Ce script les telecharge, lit la semaine/le mois directement dans le
texte du PDF (pdftotext), et enregistre le fichier sous le nom attendu
par parse_akvafakta.py -- pdf/uke/AA-SS.pdf et pdf/mane/AAAAMM_Akvafakta.pdf.

Idempotent : si le fichier correspondant a la semaine/au mois courant
existe deja, rien n'est re-telecharge ni ecrase.

Usage :
    python3 scripts/fetch_akvafakta.py

Prerequis : pdftotext (poppler-utils / poppler), comme parse_akvafakta.py.
"""
import os, re, subprocess, sys, tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UKE_DIR = os.path.join(ROOT, 'pdf', 'uke')
MANE_DIR = os.path.join(ROOT, 'pdf', 'mane')
UKE_URL = 'https://akvafakta.no/wp-content/uploads/Ukestat/siste.pdf'
MANE_URL = 'https://akvafakta.no/wp-content/uploads/Maned/siste.pdf'

MONTHS = {'januar': 1, 'februar': 2, 'mars': 3, 'april': 4, 'mai': 5, 'juni': 6,
          'juli': 7, 'august': 8, 'september': 9, 'oktober': 10,
          'november': 11, 'desember': 12}


def download(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def pdftext(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'],
                          capture_output=True, text=True).stdout


def fetch_weekly():
    os.makedirs(UKE_DIR, exist_ok=True)
    raw = download(UKE_URL)
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(raw)
        tmp = f.name
    txt = pdftext(tmp)
    # Ex. dans le PDF : "Uke 31 torsdag 30. juli 2026" -- tous les noms de
    # jour norvegiens (mandag..sondag) se terminent par "dag".
    m = re.search(r'Uke\s+(\d+)\s+\w+dag\s+\d+\.\s+\w+\s+(\d{4})', txt)
    if not m:
        print('  ATTENTION : semaine/annee introuvables dans le PDF hebdo, ignore.')
        os.remove(tmp)
        return
    week, year = int(m.group(1)), int(m.group(2))
    fname = f'{year % 100:02d}-{week:02d}.pdf'
    dest = os.path.join(UKE_DIR, fname)
    if os.path.exists(dest):
        print(f'  hebdo {fname} deja present, rien a faire')
        os.remove(tmp)
        return
    os.replace(tmp, dest)
    print(f'  hebdo telecharge : {fname}')


def fetch_monthly():
    os.makedirs(MANE_DIR, exist_ok=True)
    raw = download(MANE_URL)
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(raw)
        tmp = f.name
    txt = pdftext(tmp)
    # Meme logique que parse_akvafakta.parse_monthly pour identifier le mois :
    # la page de garde donne "Status per utgangen av <Mois>" et un tableau
    # "Endring fra <annee-1>".
    my = re.search(r'Endring fra\s*(\d{4})', txt.replace('\t', ' '))
    mm = re.search(r'Status per utgangen av\s*\n\s*'
                   r'([A-Za-z\u00e6\u00f8\u00e5\u00c6\u00d8\u00c5]+)', txt)
    if not my or not mm or mm.group(1).strip().lower() not in MONTHS:
        print('  ATTENTION : mois/annee introuvables dans le PDF mensuel, ignore.')
        os.remove(tmp)
        return
    year = int(my.group(1)) + 1
    month = MONTHS[mm.group(1).strip().lower()]
    fname = f'{year}{month:02d}_Akvafakta.pdf'
    dest = os.path.join(MANE_DIR, fname)
    if os.path.exists(dest):
        print(f'  mensuel {fname} deja present, rien a faire')
        os.remove(tmp)
        return
    os.replace(tmp, dest)
    print(f'  mensuel telecharge : {fname}')


def main():
    if subprocess.run(['which', 'pdftotext'], capture_output=True).returncode:
        sys.exit("ERREUR : pdftotext introuvable.\n"
                 "  macOS  : brew install poppler\n"
                 "  Ubuntu : sudo apt install poppler-utils")
    print('Verification du rapport hebdomadaire (Akvafakta uke)...')
    fetch_weekly()
    print('Verification du rapport mensuel (Akvafakta maned)...')
    fetch_monthly()


if __name__ == '__main__':
    main()
