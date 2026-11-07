"""Lance scripts/build_canada_atlantic.py et renvoie data/canada_atl.json (gzip+base64) dans le journal."""
import subprocess, gzip, base64, sys
subprocess.run([sys.executable, 'scripts/build_canada_atlantic.py'], check=False)
print('==CA=='); print(base64.b64encode(gzip.compress(open('data/canada_atl.json', 'rb').read())).decode()); print('==/CA==')
