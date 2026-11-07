"""Lance build_scotland.py (SEPA telecharge) et build_scotland_extra.py ; renvoie les deux JSON (gzip+base64) dans le journal."""
import subprocess, gzip, base64, sys
subprocess.run([sys.executable, 'scripts/build_scotland.py'], check=False)
subprocess.run([sys.executable, 'scripts/build_scotland_extra.py'], check=False)
for t, f in [('SC', 'data/scotland.json'), ('SX', 'data/scotland_extra.json')]:
    print(f'=={t}=='); print(base64.b64encode(gzip.compress(open(f, 'rb').read())).decode()); print(f'==/{t}==')
