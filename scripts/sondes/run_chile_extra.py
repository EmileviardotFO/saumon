"""Lance build_chile_regional.py et build_chile_caligus.py ; renvoie les JSON (gzip+base64) dans le journal."""
import subprocess, gzip, base64, sys, os
for s in ['scripts/build_chile_regional.py', 'scripts/build_chile_caligus.py']: subprocess.run([sys.executable, s], check=False)
for t, f in [('RG', 'data/chile_regional.json'), ('CG', 'data/chile_caligus.json')]:
    if os.path.exists(f): print(f'=={t}=='); print(base64.b64encode(gzip.compress(open(f, 'rb').read())).decode()); print(f'==/{t}==')
