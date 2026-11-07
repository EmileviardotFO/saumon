"""Lance scripts/build_canada_trade.py et renvoie data/canada_trade.json (gzip+base64) dans le journal."""
import subprocess, gzip, base64, sys
subprocess.run([sys.executable, 'scripts/build_canada_trade.py'], check=False)
b = open('data/canada_trade.json', 'rb').read()
print('==CT=='); print(base64.b64encode(gzip.compress(b)).decode()); print('==/CT==')
