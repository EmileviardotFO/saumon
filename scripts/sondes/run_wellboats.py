"""Lance scripts/build_wellboats.py et renvoie data/wellboats.json et data/wellboats_hist.json dans le journal."""
import subprocess, gzip, base64, sys
subprocess.run([sys.executable, 'scripts/build_wellboats.py'], check=False)
for f in ['wellboats.json', 'wellboats_hist.json']:
    try: b = open('data/' + f, 'rb').read()
    except Exception: continue
    print(f'=={f}=='); print(base64.b64encode(gzip.compress(b)).decode()); print(f'==/{f}==')
