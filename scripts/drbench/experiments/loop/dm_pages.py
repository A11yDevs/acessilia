import sys,glob,os
sys.path.insert(0,'scripts')
from page_fuse import norm
from rapidfuzz import fuzz
D,M,th,out=sys.argv[1],sys.argv[2],float(sys.argv[3]),sys.argv[4]
r=lambda p:open(p).read() if os.path.exists(p) else ''
L=[]
for f in sorted(glob.glob(D+'/*.drbench.md')):
    n=os.path.basename(f);d,m=norm(r(f)),norm(r(os.path.join(M,n)))
    if (fuzz.ratio(d,m)/100 if d and m else 0)<th:L.append(n.split('.drbench')[0])
open(out,'w').write('\n'.join(L)+'\n');print(len(L))
