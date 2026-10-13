#!/usr/bin/env python
"""Write transformed copies of a prediction dir.  usage: variants.py SRC_PRED_DIR VARIANT OUT_DIR"""
import sys, os, re, glob
src, var, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)

def blocks(s):
    return [b for b in re.split(r'\n\s*\n', s.strip()) if b.strip()]

def is_special(b):
    b = b.strip()
    return b.startswith('<table') or b.startswith('$$') or b.startswith('\\[') or b.startswith('![')

NUM = re.compile(r'\s*(\d{1,4}|[ivxlcIVXLC]{1,6})\s*')
HNUM = re.compile(r'^\s*(#+\s*)?(\d{1,4}\s*[|•·]?\s*\S.{0,70}|\S.{0,70}?\s*[|•·]?\s*\d{1,4})\s*$')

def norm(b):
    return re.sub(r'[^\w]', '', re.sub(r'\d+', '', b)).lower()

def furn_last(B, var, name):
    """Move page furniture found at the top of the page (bare page number, header line holding a
    page number, running head repeated on other pages of the doc) to the end of the page."""
    mv = []
    for i in range(min(3, len(B))):
        b = B[i]
        if is_special(b) or '\n' in b.strip():
            break
        if NUM.fullmatch(b):
            mv.append(i); continue
        if var in ('nl2', 'nl3') and HNUM.match(b) and len(b) < 80:
            mv.append(i); continue
        if var == 'nl3' and len(b) < 80 and norm(b) and norm(b) in HEADS.get(name.split('_p')[0], {}).get('set', ()) :
            mv.append(i); continue
        break
    if not mv or len(mv) == len(B):
        return B
    return [b for j, b in enumerate(B) if j not in mv] + [B[j] for j in mv]

import collections
HEADS = collections.defaultdict(lambda: {'cnt': collections.Counter()})
if var == 'nl3':
    for f in glob.glob(f'{src}/*.drbench.md'):
        doc = os.path.basename(f).split('_p')[0]
        bl = blocks(open(f, encoding='utf-8').read())[:3]
        for b in bl:
            if len(b) < 80 and norm(b): HEADS[doc]['cnt'][norm(b)] += 1
    for d in HEADS: HEADS[d]['set'] = {k for k, v in HEADS[d]['cnt'].items() if v >= 2}

def T(s, name):
    B = blocks(s)
    if var == 'nonum':          # drop bare page-number blocks
        B = [b for b in B if not re.fullmatch(r'\s*\d{1,4}\s*', b)]
    elif var == 'lines':        # every line its own block
        nb = []
        for b in B:
            nb += [b] if is_special(b) else [l for l in b.split('\n') if l.strip()]
        B = nb
    elif var == 'onebl':        # merge all consecutive plain-text blocks into one
        nb, cur = [], []
        for b in B:
            if is_special(b):
                if cur: nb.append('\n'.join(cur)); cur = []
                nb.append(b)
            else:
                cur.append(b)
        if cur: nb.append('\n'.join(cur))
        B = nb
    elif var == 'nohead':       # strip markdown heading markers
        B = [re.sub(r'^#+\s*', '', b, flags=re.M) for b in B]
    elif var in ('nl1', 'nl2', 'nl3'):
        B = furn_last(B, var, name)
    return '\n\n'.join(B) + '\n'

for f in glob.glob(f'{src}/*.drbench.md'):
    s = open(f, encoding='utf-8').read()
    open(os.path.join(out, os.path.basename(f)), 'w', encoding='utf-8').write(T(s, os.path.basename(f)))
