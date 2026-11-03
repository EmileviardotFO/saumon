#!/usr/bin/env python3
"""
Ecrit dans data/data.json la cle 'status' : resultat de chaque etape du
dernier passage du workflow et du test de fumee, pour le panneau "Sources"
du tableau de bord.

Les resultats des etapes arrivent par variables d'environnement STEP_<nom>
(success, failure, skipped, cancelled), posees par le workflow.

La cle 'farming' donne, pour l'Australie et le Canada, la derniere periode
reellement presente dans les fichiers de farming/ (et non une date de
calendrier), plus les revisions ou erreurs du dernier passage.

    python3 scripts/write_status.py
"""
import datetime as dt
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
SMOKE = os.path.join(ROOT, 'data', 'smoke.json')

# nom de la variable -> libelle affiche, dans l'ordre du workflow
STEPS = [
    ('AKVA_FETCH', 'Akvafakta — download'),
    ('AKVA_PARSE', 'Akvafakta — parse'),
    ('BIOMASSE_FETCH', 'Biomasseregisteret — download'),
    ('BIOMASSE_BUILD', 'Biomasseregisteret — rebuild'),
    ('SSB', 'SSB exports'),
    ('SSB_WEEKLY', 'SSB weekly exports (volumes)'),
    ('SSB_COPROD', 'SSB co-products (frozen heads, frames)'),
    ('ARCHIVE', 'Forecast archive'),
    ('BW_HEALTH', 'BarentsWatch — fish health'),
    ('BW_SITES', 'BarentsWatch — site register'),
    ('ESTAB', 'Mattilsynet — establishments'),
    ('CHINA', 'GACC — establishments registered for China'),
    ('EUROSTAT', 'Eurostat — EU salmon flows'),
    ('NATIONAL', 'National export statistics (Faroes, Iceland, UK, Chile, Canada)'),
    ('JAPAN', 'Japan imports of salmon and trout by form and origin (UN Comtrade)'),
    ('WORLD', 'World salmon imports by importing country (UN Comtrade)'),
    ('SCOTLAND', 'Scotland — SEPA monthly site reports'),
    ('SCOTLAND_SURVEY', 'Scotland — annual production survey'),
    ('CHILE_SITES', 'Chile — Subpesca concessions map'),
    ('EVENTS', 'Mortality events watch (press, Scotland FHI)'),
    ('NEWS', 'This week — headlines'),
    ('STORIES', 'This week — stories by basin and company'),
    ('AUSTRALIA', 'Australia — EPA Tasmania mortalities, NRE production'),
    ('CANADA_BC', 'Canada BC — DFO catalogue (sea lice, mortalities)'),
    ('FAROE', 'Faroe Islands — Bakkafrost fish per farm (monthly), harvest'),
    ('SMOKE', 'Dashboard test'),
]


def _csv(path):
    import csv
    if not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def _epa_attendu(dernier):
    """Publication EPA attendue : fin du trimestre suivant le dernier mois lu + 21 jours."""
    import calendar
    an, m = int(dernier[:4]), int(dernier[5:7])
    q_end = ((m - 1) // 3 + 1) * 3
    cible = q_end + 3 if m == q_end else q_end
    an2, m2 = (an, cible) if cible <= 12 else (an + 1, cible - 12)
    return (dt.date(an2, m2, calendar.monthrange(an2, m2)[1]) + dt.timedelta(days=21)).isoformat()


def farming_status():
    """Derniere periode REELLEMENT chargee pour l'Australie et le Canada (pas la date du calendrier)."""
    base = os.path.join(ROOT, 'farming')
    if not os.path.isdir(base):
        return None
    out = {}
    mens = _csv(os.path.join(base, 'donnees_au', 'au_mensuel.csv'))
    ent = _csv(os.path.join(base, 'donnees_au', 'au_entreprises.csv'))
    jour = _csv(os.path.join(base, 'donnees_au', 'au_journal.csv'))
    if mens:
        dernier = max(r['mois'] for r in mens)
        out['australia_mortality'] = {'last': dernier, 'next_expected': _epa_attendu(dernier),
                                      'source': 'EPA Tasmania', 'frequency': 'monthly, published quarterly'}
    if ent:
        fin = max(int(r['fin_exercice']) for r in ent)
        out['australia_production'] = {'last': f'FY{fin - 1}/{str(fin)[2:]}', 'source': 'NRE Tasmania data portal',
                                       'frequency': 'financial year (Jul-Jun), by company'}
    if jour:
        derniere_date = max((r.get('horodatage') or '')[:10] for r in jour)
        alertes = [f"{r.get('source')}: {r.get('detail')}" for r in jour
                   if (r.get('horodatage') or '')[:10] == derniere_date and r.get('statut') in ('RÉVISION', 'ERREUR')]
        out['australia_alerts'] = alertes[:10]
    etat = os.path.join(base, 'etat_catalogue_bc.json')
    if os.path.exists(etat):
        try:
            out['canada_bc'] = {jeu: {'dfo_modified': modif, 'source': 'DFO open.canada.ca'}
                                for jeu, modif in json.load(io.open(etat, encoding='utf-8')).items()}
        except ValueError:
            pass
    return out or None


def _farming_sans_risque():
    # l'etat des sources doit toujours s'ecrire : un fichier farming/ illisible ne fait que vider ce bloc
    try:
        return farming_status()
    except Exception as e:  # noqa: BLE001
        print('Bloc farming ignore :', e)
        return None


def main():
    data = json.load(io.open(DATA, encoding='utf-8'))
    steps = [{'id': k, 'name': n, 'outcome': os.environ.get('STEP_' + k, '') or 'unknown'} for k, n in STEPS]
    smoke = None
    if os.path.exists(SMOKE):
        try:
            smoke = json.load(io.open(SMOKE, encoding='utf-8'))
        except ValueError:
            smoke = None
    server, repo, run = (os.environ.get('GITHUB_SERVER_URL', ''), os.environ.get('GITHUB_REPOSITORY', ''),
                         os.environ.get('GITHUB_RUN_ID', ''))
    eu = None
    EUF = os.path.join(ROOT, 'data', 'eurostat.json')
    if os.path.exists(EUF):
        try:
            m = json.load(io.open(EUF, encoding='utf-8'))['meta']
            eu = {'fetched': m.get('fetched'), 'last_period': m.get('last_period'), 'source_update': m.get('source_update')}
        except (ValueError, KeyError):
            eu = None
    nat = None
    NTF = os.path.join(ROOT, 'data', 'national_trade.json')
    if os.path.exists(NTF):
        try:
            m = json.load(io.open(NTF, encoding='utf-8'))['meta']
            nat = {k: {'last': v.get('last'), 'source': v.get('source')} for k, v in m.get('sources', {}).items()}
            nat['fetched'] = m.get('fetched')
        except (ValueError, KeyError):
            nat = None
    data['status'] = {
        'eurostat': eu,
        'national': nat,
        'farming': _farming_sans_risque(),
        'run_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'run_url': f'{server}/{repo}/actions/runs/{run}' if server and repo and run else None,
        'steps': steps,
        'smoke': smoke,
    }
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    bad = [s['name'] for s in steps if s['outcome'] == 'failure']
    print('Etat enregistre.', ('Etapes en echec : ' + ', '.join(bad)) if bad else 'Aucune etape en echec.')


if __name__ == '__main__':
    main()
