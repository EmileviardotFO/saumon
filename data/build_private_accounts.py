#!/usr/bin/env python3
"""
Annual accounts of Norway's private salmon farmers (those that publish no quarterly report), from the public
Brønnøysund registers: free API, no key.

    python3 scripts/build_private_accounts.py        -> data/private_accounts.json

The companies are the licence holders of the farmer groups in the site register (data.json, bw_register.mtb_groups),
listed groups left out (their quarterly reports are read elsewhere). For each holder: its organisation number
(Enhetsregisteret, by exact name), then its latest annual accounts (Regnskapsregisteret): revenue, operating result,
pre-tax and net result. Years already stored are kept, so a history builds up year after year.
"""
import datetime as dt
import io
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
OUT = os.path.join(ROOT, 'data', 'private_accounts.json')
ENH = 'https://data.brreg.no/enhetsregisteret/api/enheter'
REG = 'https://data.brreg.no/regnskapsregisteret/regnskap/'
COTES = {'mowi', 'salmar', 'lerøy', 'grieg seafood', 'måsøval', 'bakkafrost', 'ocean farming as', 'mariculture as'}
EN_PLUS = ['CERMAQ NORWAY SALMON AS']        # prive (Mitsubishi) mais suivi trimestriellement par sa maison mere : comptes annuels aussi
MAX_GROUPES = 45


def get(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'salmon-dashboard/1.0'})
    return json.loads(urllib.request.urlopen(req, timeout=40).read().decode('utf-8'))


def cherche(o, cle):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == cle: yield v
            yield from cherche(v, cle)
    elif isinstance(o, list):
        for x in o: yield from cherche(x, cle)


def premier(o, cle):
    return next((v for v in cherche(o, cle) if isinstance(v, (int, float))), None)


def orgnr(nom):
    j = get(ENH + '?' + urllib.parse.urlencode({'navn': nom, 'size': 20}))
    for e in next(cherche(j, 'enheter'), []) or []:
        if (e.get('navn') or '').strip().upper() == nom.strip().upper():
            return e.get('organisasjonsnummer')
    return None


def comptes(nr):
    """Derniers comptes publies -> {annee: {...}} (le registre ne rend souvent que la derniere annee)."""
    j = get(REG + str(nr))
    out = {}
    for r in (j if isinstance(j, list) else [j]):
        fin = ((r.get('regnskapsperiode') or {}).get('tilDato') or '')[:10]
        if not fin: continue
        out[fin[:4]] = {'period_end': fin, 'type': r.get('regnskapstype'), 'currency': r.get('valuta') or 'NOK',
                        'revenue': premier(r, 'sumDriftsinntekter'), 'operating_result': premier(r.get('resultatregnskapResultat') or r, 'driftsresultat'),
                        'pre_tax': premier(r, 'ordinaertResultatFoerSkattekostnad'), 'net_result': premier(r, 'aarsresultat')}
    return out


def main():
    d = json.load(io.open(DATA, encoding='utf-8'))
    groupes = [g for g in d['bw_register']['mtb_groups'] if g['group'].lower() not in COTES][:MAX_GROUPES]
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'companies': {}}
    soc = ancien.get('companies', {})
    a_lire = [(g['group'], h, g['mtb'], g['po']) for g in groupes for h in g['holders']] + [('Cermaq', h, None, None) for h in EN_PLUS]
    echecs = []
    for groupe, nom, mtb, po in a_lire:
        x = soc.setdefault(nom, {'group': groupe, 'orgnr': None, 'years': {}})
        x.update({'group': groupe, 'mtb': mtb, 'zones': po})
        try:
            if not x.get('orgnr'): x['orgnr'] = orgnr(nom)
            if x['orgnr']:
                x['years'].update(comptes(x['orgnr']))
            else:
                echecs.append(f'{nom}: organisation number not found')
        except Exception as e:  # noqa: BLE001
            echecs.append(f'{nom}: {str(e)[:80]}')
        time.sleep(0.3)
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                    'source': 'Brønnøysundregistrene: Enhetsregisteret and Regnskapsregisteret (public API)',
                    'note': 'Company accounts of each licence holder (not consolidated group accounts unless the holder files them).',
                    'failed': echecs[:30]},
           'companies': soc}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    ok = sum(1 for v in soc.values() if v.get('years'))
    print(f'data/private_accounts.json : {ok}/{len(soc)} companies with accounts' + (f' — {len(echecs)} failed' if echecs else ''))
    if not ok: raise SystemExit('no accounts read: ' + '; '.join(echecs[:3]))


if __name__ == '__main__':
    main()
