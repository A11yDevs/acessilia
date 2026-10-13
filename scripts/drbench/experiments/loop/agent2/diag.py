import json, sys, re, Levenshtein as L
from collections import defaultdict
P=json.load(open(sys.argv[1]))
def typ(s):
    if re.fullmatch(r'\d{1,4}',s): return 'num'
    if re.fullmatch(r'[ivxlcIVXLC]{1,6}',s): return 'roman'
    if len(s)<15: return 'short<15'
    if len(s)<60: return 'mid<60'
    return 'long'
agg=defaultdict(float); cnt=defaultdict(int); n=0
for w,pairs in P.items():
    den=sum(max(len(a),len(b)) for a,b in pairs)
    if not den: continue
    n+=1
    for a,b in pairs:
        if not a and not b: continue
        k=('MISS ' + typ(a)) if not b else ('EXTRA '+typ(b)) if not a else ('MATCH ratio' + ('<.7' if len(b)<.7*len(a) else '>1.4' if len(b)>1.4*len(a) else 'ok'))
        agg[k]+=100*L.distance(a,b)/den; cnt[k]+=1
for k in sorted(agg,key=lambda k:-agg[k]): print(f'{k:22s} loss/page={agg[k]/n:.3f}  n={cnt[k]}')
