#!/usr/bin/env python
"""Drop prediction blocks that are not supported by a layout-based source (text inside pictures).
usage: support_filter.py SRC_PRED OUT_DIR --ref mineru-hyb+rot[,docling+rot] --thr 0.5 --minlen 20
A plain-text block is dropped when its normalised text (\\w only, lowercase) has fuzz.partial_ratio
< thr*100 against EVERY reference page text."""
import sys, os, re, glob, argparse
from rapidfuzz import fuzz
ap = argparse.ArgumentParser()
ap.add_argument('src'); ap.add_argument('out')
ap.add_argument('--ref', default='mineru-hyb+rot'); ap.add_argument('--thr', type=float, default=0.5)
ap.add_argument('--minlen', type=int, default=20); ap.add_argument('--mode', default='all')
a = ap.parse_args()
FULL = os.environ.get('DRBENCH_FULL', '/raid/user_marcospaulo/drdocbench/runs/dev-full')
os.makedirs(a.out, exist_ok=True)
norm = lambda s: re.sub(r'[\W_]', '', re.sub(r'!\[.*?\]\(.*?\)', '', s)).lower()
def blocks(s): return [b for b in re.split(r'\n\s*\n', s.strip()) if b.strip()]
special = lambda b: b.lstrip().startswith(('<table', '$$', '\\[', '!['))
nd = nb = 0
for f in sorted(glob.glob(f'{a.src}/*.drbench.md')):
    name = os.path.basename(f)
    B = blocks(open(f, encoding='utf-8').read())
    refs = []
    for r in a.ref.split(','):
        p = f'{FULL}/{r}/predictions/{name}'
        refs.append(norm(open(p, encoding='utf-8').read()) if os.path.exists(p) else '')
    keep = []
    for b in B:
        n = norm(b); nb += 1
        if special(b) or len(n) < a.minlen or not any(refs):
            keep.append(b); continue
        sup = max(fuzz.partial_ratio(n, r) if r else 0 for r in refs) / 100
        if sup < a.thr:
            nd += 1; continue
        keep.append(b)
    open(f'{a.out}/{name}', 'w', encoding='utf-8').write('\n\n'.join(keep) + '\n')
print(f'dropped {nd}/{nb} blocks', file=sys.stderr)
