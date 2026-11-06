"""Sonde 3 MAST : toutes les tables et colonnes, valeurs distinctes des colonnes courtes, et un echantillon du dernier mois
(biomasse et poids par site ? elevage a terre ?)."""
import json, os, sys, traceback
sys.path.insert(0, 'scripts')
import build_iceland_mast as B
os.makedirs('sonde_out', exist_ok=True)
meta = json.load(open('data/iceland.json', encoding='utf-8'))['meta']
embeds = [u.strip() for u in str(meta.get('dashboard_embed', '')).split(',') if 'powerbi' in u]
for e in embeds:
    try:
        r = B.Report(e)
    except Exception as ex:
        print('rapport non lu', ex); continue
    print('==== rapport', r.key[:8])
    for s in r.mx['exploration']['sections']:
        print('  page :', s.get('displayName'))
    for t, cols in r.tables.items():
        print('  TABLE', t, cols)
        # valeurs distinctes des colonnes texte (une a une)
        for c in cols:
            if any(w in c.lower() for w in ('kg', 'count', 'fjöldi', 'lífmass', 'þyngd', 'weight', 'mortal', 'feed', 'magn')):
                continue
            try:
                rows = r.query(t, [c], [], count=60)
                vals = [x[c] for x in rows][:60]
                if len(vals) < 60:
                    print('     ', c, '->', vals)
            except Exception as ex:
                pass
    if 'cage_report' in r.tables:
        cols = r.tables['cage_report']
        num = [c for c in cols if any(w in c for w in ('Kg', 'Count', 'Weight', 'weight', 'Avg', 'Þyngd', 'Lífmass'))]
        try:
            rows = r.query('cage_report', ['Lok tímabils', 'Svæði', 'Tegund'], num, count=30000)
            last = max(str(x['Lok tímabils']) for x in rows if x['Lok tímabils'])
            sample = [x for x in rows if str(x['Lok tímabils']) == last][:15]
            print('  cage_report dernier mois', last); [print('    ', x) for x in sample]
        except Exception:
            print(traceback.format_exc()[-600:])
print('fin')
