#!/usr/bin/env python3
"""docs/beta.html = docs/production.html + la couche de mise en page "beta" (scripts/beta_layer.html).
La page de production n'est pas touchee ; les donnees sont les memes (data/*.json)."""
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, 'docs', 'production.html'), encoding='utf-8').read()
layer = open(os.path.join(ROOT, 'scripts', 'beta_layer.html'), encoding='utf-8').read()
i = src.rfind('</body>')
out = src[:i] + layer + src[i:]
out = out.replace("navigator.serviceWorker.register('sw.js')", "0", 1)
open(os.path.join(ROOT, 'docs', 'beta.html'), 'w', encoding='utf-8').write(out)
print('docs/beta.html', len(out))
