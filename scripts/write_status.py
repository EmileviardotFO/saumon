#!/usr/bin/env python3
"""
Ecrit dans data/data.json la cle 'status' : resultat de chaque etape du
dernier passage du workflow et du test de fumee, pour le panneau "Sources"
du tableau de bord.

Les resultats des etapes arrivent par variables d'environnement STEP_<nom>
(success, failure, skipped, cancelled), posees par le workflow.

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
    ('BW_HEALTH', 'BarentsWatch — fish health'),
    ('BW_SITES', 'BarentsWatch — site register'),
    ('ESTAB', 'Mattilsynet — establishments'),
    ('CHINA', 'GACC — establishments registered for China'),
    ('EUROSTAT', 'Eurostat — EU salmon flows'),
    ('NATIONAL', 'National export statistics (Faroes, Iceland, UK, Chile, Canada)'),
    ('SMOKE', 'Dashboard test'),
]


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
